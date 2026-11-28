import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.agent.trader import AgentRun
from app.config import Settings
from app.domain.models import Action
from app.experiment.ledger import ExperimentConfig
from app.experiment.runner import synthetic_cycle
from app.experiment.storage import SyntheticStore, annotate_tick
from app.robinhood import cli
from app.robinhood.gateway import RobinhoodReadOnlyGateway, UnsafeRobinhoodToolError
from app.robinhood.models import RobinhoodTruth
from app.robinhood.schedule import ShadowScheduler, XNYSCalendar
from app.robinhood.service import ShadowService, service_preflight
from app.robinhood.shadow import ShadowOrchestrator
from app.storage.db import make_engine, make_session_factory
from app.storage.models import (
    DecisionCycleRow,
    FillRow,
    ModelUsageRow,
    OrderRow,
    SyntheticCycleRow,
    SyntheticFillRow,
)
from app.web.shadow import create_shadow_app
from tests.test_synthetic_ledger import START, decision, packet


@pytest.fixture
def experiment(repo, settings, tmp_path):
    cfg = Settings(
        mode="SHADOW",
        robinhood_db_url=settings.db_url,
        synthetic_experiment_id="test-v1",
        shadow_service_lock_path=str(tmp_path / "service.lock"),
    )
    store = SyntheticStore(repo.session_factory)
    store.initialize("test-v1", ExperimentConfig.capture(cfg, cfg.model_name))
    truth = RobinhoodTruth.model_validate(
        {
            "account": {
                "account_number": "PRIVATE-ACCOUNT",
                "type": "cash",
                "brokerage_account_type": "individual",
                "agentic_allowed": True,
                "state": "active",
                "deactivated": False,
                "permanently_deactivated": False,
            },
            "portfolio": {
                "total_value": "90",
                "equity_value": "0",
                "cash": "90",
                "buying_power": "90",
                "unleveraged_buying_power": "90",
                "unsupported_value": "0",
            },
        }
    )
    ctx = SimpleNamespace(
        settings=cfg,
        store=store,
        at=START,
        truth=truth,
        seen=[],
        next_decision=decision(),
        error=None,
        tokens=True,
    )

    class Agent:
        model_identifier = cfg.model_name

        def decide(self, p):
            ctx.seen.append(p)
            if ctx.error:
                raise ctx.error
            return AgentRun(
                ctx.next_decision,
                input_tokens=100 if ctx.tokens else 0,
                output_tokens=40 if ctx.tokens else 0,
            )

    class Reads:
        async def truth(self):
            return ctx.truth

    class Market:
        async def candidates(self, account_number, symbols):
            return packet(ctx.at).candidates

        def regime(self, candidates):
            return "test"

    class Gateway:
        async def call_safe(self, *args):
            raise AssertionError("Synthetic execution must never call review/write")

    ctx.orchestrator = ShadowOrchestrator(cfg, repo, Gateway(), Agent(), clock=lambda: ctx.at)
    ctx.orchestrator.reads, ctx.orchestrator.market = Reads(), Market()

    async def cycle(window, token):
        result = await synthetic_cycle(ctx.orchestrator, window, token)
        return result["exit_code"]

    ctx.scheduler = ShadowScheduler(repo, cycle, clock=lambda: ctx.at)
    return ctx


def row_count(repo, model):
    with repo.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model))


@pytest.mark.anyio
async def test_scheduler_restart_pending_fill_close_isolation_and_duplicate(
    experiment, repo, settings
):
    e = experiment
    assert (await e.scheduler.tick())["status"] == "COMPLETED"
    assert len(e.seen) == 1
    assert e.seen[0].account.equity == 10  # Real brokerage equity is 90.
    assert e.seen[0].session_context["account_context"] == "SYNTHETIC_PAPER"
    initial = e.store.report("test-v1")
    assert initial["latest"]["position"] is None and initial["latest"]["pending"]
    assert (await e.scheduler.tick())["reason"] == "SLOT_ALREADY_ATTEMPTED"
    assert len(e.seen) == 1
    e.at += timedelta(minutes=15)
    e.next_decision = decision(Action.CLOSE)
    assert (await e.scheduler.tick())["status"] == "COMPLETED"
    assert e.seen[-1].account.position.symbol == "AAPL"
    assert repo.load_open_position() is None
    reopened = SyntheticStore(make_session_factory(make_engine(settings.db_url)))
    assert reopened.load("test-v1")[1].pending.decision.action == Action.CLOSE
    assert reopened.load("test-v1")[1].position.symbol == "AAPL"
    e.at += timedelta(minutes=15)
    e.next_decision = decision(Action.HOLD)
    result = annotate_tick(e.settings, repo, await e.scheduler.tick())
    assert result["synthetic_cycle_id"] == 3 and result["population"] == "SYNTHETIC_PAPER"
    report = e.store.report("test-v1")
    assert report["revision"] == 3 and len(report["fills"]) == 2
    assert report["fills"][0]["source_cycle_id"] == 1
    assert report["fills"][1]["source_cycle_id"] == 2
    assert report["latest"]["position"] is None and report["known_model_cost"] == "0.00009"
    for table in (DecisionCycleRow, ModelUsageRow, FillRow, OrderRow):
        assert row_count(repo, table) == 0
    assert row_count(repo, SyntheticCycleRow) == 3
    assert all(s.cycle_id is None for s in repo.shadow_schedule_slots())
    # Even after switching profiles, the original scheduler claim prevents replay.
    assert not repo.claim_shadow_slot(XNYSCalendar().current_window(e.at), "other-population", e.at)


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["model-error", "missing-usage", "broker-mismatch"])
async def test_service_persists_failure_and_halts_without_later_model_calls(
    experiment, repo, fault, capsys
):
    e = experiment
    if fault == "model-error":
        e.error = RuntimeError("secret-api-value")
    elif fault == "missing-usage":
        e.tokens = False
    else:
        e.truth.portfolio.unsupported_value = Decimal(1)

    async def preflight(*args):
        return None

    service = ShadowService(e.settings, repo, e.scheduler, clock=lambda: e.at, preflight=preflight)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    try:
        for _ in range(200):
            if repo.shadow_service_state() and repo.shadow_service_state()["status"] == "HALTED":
                break
            await asyncio.sleep(0.005)
        assert repo.shadow_service_state()["last_result"]["exit_code"] == (
            3 if fault == "broker-mismatch" else 8
        )
    finally:
        stop.set()
        assert await task == 0
    report = e.store.report("test-v1")
    assert report["cycles"][0]["decision"]["action"] == "HOLD"
    assert report["latest"]["position"] is None and not report["fills"]
    assert report["unknown_model_calls"] == (0 if fault == "broker-mismatch" else 1)
    if fault != "broker-mismatch":
        assert report["latest"]["net_after_model_cost_equity"] is None
    assert "secret-api-value" not in json.dumps(report) + capsys.readouterr().out
    before = len(e.seen)
    e.at += timedelta(minutes=15)
    stopped = asyncio.Event()
    stopped.set()
    assert (
        await ShadowService(
            e.settings, repo, e.scheduler, clock=lambda: e.at, preflight=preflight
        ).run(stopped)
        == 0
    )
    assert len(e.seen) == before and repo.active_shadow_slot() is None


@pytest.mark.anyio
async def test_cancelled_cycle_keeps_claim_and_commits_no_transition(experiment, repo):
    e = experiment
    entered = asyncio.Event()

    async def blocked(packet):
        entered.set()
        await asyncio.Event().wait()

    e.orchestrator._decide = blocked
    task = asyncio.create_task(e.scheduler.tick())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert e.store.report("test-v1")["revision"] == 0
    assert e.store.report("test-v1")["unknown_model_calls"] == 1
    assert repo.active_shadow_slot().status == "CLAIMED"
    e.at += timedelta(minutes=15)
    assert (await e.scheduler.tick())["reason"] == "RUN_IN_PROGRESS"


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["revision", "fill"])
async def test_atomic_transition_rolls_back_cash_journal_and_slot(experiment, repo, fault):
    e = experiment
    await e.scheduler.tick()
    before = e.store.report("test-v1")
    e.at += timedelta(minutes=15)
    e.next_decision = decision(Action.HOLD)
    if fault == "revision":
        from app.storage.models import SyntheticExperimentRow

        original = e.orchestrator._decide

        async def conflict(p):
            with repo.session_factory.begin() as s:
                s.get(SyntheticExperimentRow, "test-v1").revision += 1
            return await original(p)

        e.orchestrator._decide = conflict
    else:

        def fail(*args):
            raise RuntimeError("late-fill-insert-failure")

        event.listen(SyntheticFillRow, "before_insert", fail)
    try:
        result = await e.scheduler.tick()
    finally:
        if fault == "fill":
            event.remove(SyntheticFillRow, "before_insert", fail)
    after = e.store.report("test-v1")
    assert result["exit_code"] == 11
    assert len(after["cycles"]) == 1 and not after["fills"]
    assert after["latest"]["cash"] == before["latest"]["cash"]
    assert after["latest"]["net_after_model_cost_equity"] is None
    assert after["unknown_model_calls"] == 1
    assert e.store.load("test-v1")[1].position is None
    assert e.store.load("test-v1")[1].known_model_cost == Decimal(".00003")
    assert repo.active_shadow_slot() is None


@pytest.mark.anyio
async def test_no_claim_no_reads_model_or_state_write(experiment, repo):
    e = experiment
    with pytest.raises(RuntimeError, match="own a scheduled claim"):
        await synthetic_cycle(e.orchestrator, XNYSCalendar().current_window(e.at), "wrong-owner")
    assert not e.seen and e.store.report("test-v1")["revision"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "model_name",
        "model_input_usd_per_million",
        "max_daily_entries",
        "initial_symbols",
        "shadow_bar_interval",
    ],
)
def test_frozen_experiment_config_requires_new_identity(experiment, change):
    e = experiment
    values = {
        "model_name": "other-model",
        "model_input_usd_per_million": Decimal(1),
        "max_daily_entries": 1,
        "initial_symbols": ["SPY"],
        "shadow_bar_interval": "day",
    }
    modified = e.settings.model_copy(update={change: values[change]})
    with pytest.raises(ValueError, match="changed"):
        e.store.validate_profile(modified, modified.model_name)
    with pytest.raises(ValueError, match="cannot be reset"):
        e.store.initialize("test-v1", ExperimentConfig.capture(e.settings, e.settings.model_name))


@pytest.mark.anyio
async def test_profile_preflight_fails_before_auth_or_network(experiment, repo):
    cfg = experiment.settings.model_copy(update={"model_name": "different"})
    assert (await service_preflight(cfg, repo))["reason"] == "SYNTHETIC_PROFILE_INVALID"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool", ["review_equity_order", "place_equity_order", "cancel_equity_order", "update_account"]
)
async def test_read_only_gateway_blocks_review_and_writes(tool):
    async def forbidden(*args):
        raise AssertionError("Blocked tool reached transport")

    gateway = RobinhoodReadOnlyGateway(
        SimpleNamespace(call_tool=forbidden), "https://agent.robinhood.com/mcp/trading"
    )
    with pytest.raises(UnsafeRobinhoodToolError):
        await gateway.call_safe(tool, {})


@pytest.mark.anyio
async def test_dashboard_readonly_auth_and_separate_cost_populations(experiment, repo, tmp_path):
    e = experiment
    await e.scheduler.tick()
    e.at += timedelta(minutes=15)
    e.next_decision = decision(Action.HOLD)
    await e.scheduler.tick()
    secret = tmp_path / "password"
    password = "test-private-observer-password-that-is-long"
    secret.write_text(password)
    cfg = e.settings.model_copy(update={"dashboard_password_file": str(secret)})
    client = TestClient(create_shadow_app(cfg, clock=lambda: e.at))
    assert client.get("/api/synthetic/test-v1").status_code == 401
    client.auth = ("trader", password)
    before = Path(cfg.robinhood_db_url.removeprefix("sqlite:///")).read_bytes()
    response = client.get("/api/synthetic/test-v1")
    assert response.status_code == 200
    assert response.json() == e.store.report("test-v1")
    overview = client.get("/api/shadow").json()
    assert overview["synthetic_experiments"][0]["known_model_cost"] == "0.00006"
    page = client.get("/")
    assert page.status_code == 200
    assert "Synthetic portfolio" in page.text and "PAPER / ASSUMED FILLS" in page.text
    assert "PRIVATE-ACCOUNT" not in response.text + page.text
    assert password not in page.text
    assert "Content-Security-Policy" in page.headers and page.headers["cache-control"] == "no-store"
    assert client.get("/api/synthetic/test-v1?limit=101").status_code == 422
    assert client.get("/api/synthetic/no-such-experiment").status_code == 404
    assert client.post("/api/synthetic/test-v1").status_code == 405
    assert Path(cfg.robinhood_db_url.removeprefix("sqlite:///")).read_bytes() == before
    assert row_count(repo, DecisionCycleRow) == row_count(repo, ModelUsageRow) == 0


@pytest.mark.anyio
async def test_cli_routes_selected_profile_through_readonly_gateway(experiment, repo, monkeypatch):
    e = experiment
    observed = []

    class FakeConnection:
        @asynccontextmanager
        async def client(self):
            yield object()

    monkeypatch.setattr(cli, "_connection", lambda settings: FakeConnection())
    monkeypatch.setattr(cli, "_configured_openai_key_problem", lambda settings: None)
    monkeypatch.setattr(cli, "OpenAIAgentsTrader", lambda model: e.orchestrator.agent)

    def construct(settings, repo, gateway, agent):
        observed.append(type(gateway))
        return e.orchestrator

    monkeypatch.setattr(cli, "ShadowOrchestrator", construct)
    w = XNYSCalendar().current_window(e.at)
    assert repo.claim_shadow_slot(w, "owner", e.at)
    assert (
        await cli.shadow_cycle(
            e.settings, "openai", repo=repo, schedule_window=w, claim_token="owner"
        )
        == 0
    )
    assert observed == [RobinhoodReadOnlyGateway]
    assert await cli.shadow_cycle(e.settings, "openai", repo=repo) == 14
    assert len(e.seen) == 1


@pytest.mark.anyio
async def test_closed_market_skips_all_network_and_model_calls(experiment):
    e = experiment
    e.at = START - timedelta(days=1)
    assert (await e.scheduler.tick())["reason"] == "MARKET_CLOSED"
    assert not e.seen and e.store.report("test-v1")["revision"] == 0


@pytest.mark.parametrize("fee", [5, 10])
def test_benchmark_cannot_start_with_insufficient_execution_fee_budget(fee):
    with pytest.raises(ValueError, match="cover both"):
        ExperimentConfig.capture(Settings(), "test", fee_per_fill=Decimal(fee))


@pytest.mark.anyio
async def test_private_backup_preserves_virtual_positions_costs_and_attempt_receipts(
    experiment, tmp_path
):
    from app.robinhood.backup import backup_database

    e = experiment
    await e.scheduler.tick()
    e.at += timedelta(minutes=15)
    e.next_decision = decision(Action.HOLD)
    await e.scheduler.tick()
    target = tmp_path / "backup.db"
    backup_database(e.settings, target)
    restored = SyntheticStore(make_session_factory(make_engine(f"sqlite:///{target}")))
    assert restored.report("test-v1") == e.store.report("test-v1")
    assert restored.load("test-v1")[1].position.symbol == "AAPL"
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.anyio
async def test_unaccounted_attempt_prevents_post_recovery_entries(experiment, repo):
    e = experiment
    entered = asyncio.Event()

    async def blocked(p):
        entered.set()
        await asyncio.Event().wait()

    e.orchestrator._decide = blocked
    task = asyncio.create_task(e.scheduler.tick())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    repo.abandon_shadow_slot(XNYSCalendar().current_window(e.at).key, e.at)
    e.at += timedelta(minutes=15)
    # Explicit operator abandonment can free the slot but cannot erase unknown cost.
    assert (await e.scheduler.tick())["status"] == "COMPLETED"
    report = e.store.report("test-v1")
    assert report["unknown_model_calls"] == 1
    assert report["latest"]["net_after_model_cost_equity"] is None
    assert report["cycles"][0]["model"] == "session-guard"
    assert not report["fills"] and report["latest"]["pending"] is None


def test_blank_profile_keeps_default_real_shadow_and_report_limit_is_bounded(monkeypatch):
    monkeypatch.setenv("TRADER_SYNTHETIC_EXPERIMENT_ID", "")
    assert Settings().synthetic_experiment_id is None
    assert Settings().normalized_mode == "PAPER"
    assert cli._synthetic_limit("100") == 100
    import argparse

    for value in ("0", "101"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._synthetic_limit(value)
