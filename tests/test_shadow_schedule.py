import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier

import pytest

from app.agent.trader import StubTraderAgent
from app.config import Settings
from app.domain.models import AccountState, ExecutionResult, MarketPacket
from app.risk.governor import govern
from app.robinhood.schedule import SessionWindow, ShadowScheduler, XNYSCalendar
from app.storage.db import make_engine, make_session_factory
from app.storage.repository import Repository


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.parametrize("instant, expected", [
    ("2026-10-03T17:52:06Z", None),  # Saturday, matching the live smoke check.
    ("2026-12-25T15:00:00Z", None),
    ("2026-10-05T13:29:59Z", None),
    ("2026-10-05T13:30:00Z", "2026-10-05T13:30:00+00:00"),
    ("2026-10-05T13:44:59Z", "2026-10-05T13:30:00+00:00"),
    ("2026-10-05T13:45:00Z", "2026-10-05T13:45:00+00:00"),
    ("2026-10-05T19:59:59Z", "2026-10-05T19:45:00+00:00"),
    ("2026-10-05T20:00:00Z", None),
    ("2026-11-27T17:59:59Z", "2026-11-27T17:45:00+00:00"),  # Early close.
    ("2026-11-27T18:00:00Z", None),
    ("2026-03-06T14:30:00Z", "2026-03-06T14:30:00+00:00"),  # Before DST.
    ("2026-03-09T13:30:00Z", "2026-03-09T13:30:00+00:00"),
])
def test_xnys_actual_calendar_boundaries(instant, expected):
    window = XNYSCalendar().current_window(stamp(instant))
    assert (window.scheduled_for.isoformat() if window else None) == expected


def test_calendar_requires_aware_clock_and_does_not_guess_outside_coverage():
    calendar = XNYSCalendar()
    with pytest.raises(ValueError):
        calendar.current_window(datetime(2026, 10, 5, 13, 30))
    with pytest.raises(ValueError):
        calendar.current_window(stamp("2100-01-05T15:00:00Z"))


def window_at(now):
    return XNYSCalendar().current_window(now)


def complete(repo, window, token, *, error=None):
    packet = MarketPacket(
        as_of=window.scheduled_for, candidates=[], session_context=window.context(),
        account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
    )
    decision = StubTraderAgent().decide(packet).decision
    return repo.save_shadow_cycle(
        packet, decision, govern(decision, packet, Settings(mode="SHADOW")),
        ExecutionResult(status="SKIPPED", agent_error=error), "stub",
        prompt_version="v3-session-shadow", latency_ms=1,
        input_tokens=0, output_tokens=0, input_price=Decimal("0.1"),
        output_price=Decimal("0.5"), benchmark_symbol="SPY",
        reconciliation={"reconciled": True, "reasons": []},
        slot_key=window.key, claim_token=token,
    )


@pytest.mark.anyio
async def test_same_slot_is_never_replayed_after_restart(repo, settings):
    now = stamp("2026-10-05T13:40:00Z")
    calls = []

    async def run(window, token):
        calls.append(window.key)
        complete(repo, window, token)
        return 0

    scheduler = ShadowScheduler(repo, run, clock=lambda: now)
    first = await scheduler.tick()
    assert first["status"] == "COMPLETED"
    assert first["cycle_id"] is not None
    assert repo.active_shadow_slot() is None
    reopened = Repository(make_session_factory(make_engine(settings.db_url)))
    repeated = await ShadowScheduler(reopened, run, clock=lambda: now).tick()
    assert repeated["reason"] == "SLOT_ALREADY_ATTEMPTED"
    assert len(calls) == 1
    assert len(repo.recent_cycles()) == 1
    assert repo.shadow_slot(calls[0]).status == "COMPLETED"


@pytest.mark.anyio
async def test_restart_selects_current_slot_without_catch_up(repo):
    calls = []

    async def run(window, token):
        calls.append(window.scheduled_for)
        complete(repo, window, token)
        return 0

    now = stamp("2026-10-05T17:07:00Z")
    assert (await ShadowScheduler(repo, run, clock=lambda: now).tick())["exit_code"] == 0
    assert calls == [stamp("2026-10-05T17:00:00Z")]
    assert len(repo.shadow_schedule_slots()) == 1


@pytest.mark.anyio
async def test_two_workers_do_not_run_two_cycles(repo):
    entered = asyncio.Event()
    finish = asyncio.Event()
    now = stamp("2026-10-05T13:40:00Z")

    async def run(window, token):
        entered.set()
        await finish.wait()
        complete(repo, window, token)
        return 0

    first = asyncio.create_task(ShadowScheduler(repo, run, clock=lambda: now).tick())
    await entered.wait()
    second = await ShadowScheduler(repo, run, clock=lambda: now).tick()
    assert second["reason"] == "RUN_IN_PROGRESS"
    assert second["exit_code"] == 10
    finish.set()
    assert (await first)["status"] == "COMPLETED"
    assert len(repo.recent_cycles()) == 1


def test_database_constraints_arbitrate_independent_concurrent_connections(repo, settings):
    now = stamp("2026-10-05T13:40:00Z")
    barrier = Barrier(2)

    def claim(index):
        independent = Repository(make_session_factory(make_engine(settings.db_url)))
        barrier.wait(timeout=5)
        return independent.claim_shadow_slot(window_at(now), str(index), now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [1, 2]))
    assert sorted(results) == [False, True]
    assert len(repo.shadow_schedule_slots()) == 1


@pytest.mark.anyio
async def test_crashed_claim_blocks_even_the_next_interval(repo, settings):
    first = stamp("2026-10-05T13:40:00Z")
    window = window_at(first)
    assert repo.claim_shadow_slot(window, "crashed-owner", first)
    reopened = Repository(make_session_factory(make_engine(settings.db_url)))

    async def forbidden_run(*args):
        raise AssertionError("Crash must not trigger automatic replay")

    result = await ShadowScheduler(reopened, forbidden_run,
                                   clock=lambda: first + timedelta(minutes=20)).tick()
    assert result["reason"] == "RUN_IN_PROGRESS"
    assert result["slot_key"] == window.key
    assert reopened.shadow_slot(window.key).status == "CLAIMED"
    assert len(reopened.shadow_schedule_slots()) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["exception", "missing_cycle", "model"])
async def test_failure_stops_and_never_replays_same_slot(repo, failure):
    calls = []
    now = stamp("2026-10-05T13:40:00Z")

    async def run(window, token):
        calls.append(1)
        if failure == "exception":
            raise RuntimeError("secret token detail")
        if failure == "model":
            complete(repo, window, token, error="RateLimitError")
            return 8
        return 0

    scheduler = ShadowScheduler(repo, run, clock=lambda: now)
    result = await scheduler.tick()
    assert result["status"] == "ERROR"
    assert result["exit_code"] == (8 if failure == "model" else 11)
    assert "secret token detail" not in str(result)
    assert repo.active_shadow_slot() is None
    assert (await scheduler.tick())["reason"] == "SLOT_ALREADY_ATTEMPTED"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_calendar_failure_and_closed_session_make_no_cycle_call(repo):
    async def forbidden_run(*args):
        raise AssertionError("No broker/model call allowed")

    class BrokenCalendar:
        def current_window(self, now):
            raise ValueError("invalid calendar")

    scheduler = ShadowScheduler(repo, forbidden_run, calendar=BrokenCalendar())
    assert (await scheduler.tick())["reason"] == "CALENDAR_FAILURE"
    closed = ShadowScheduler(repo, forbidden_run, clock=lambda: stamp("2026-10-03T17:00:00Z"))
    assert (await closed.tick())["reason"] == "MARKET_CLOSED"
    assert repo.shadow_schedule_slots() == []


def test_wrong_owner_cannot_complete_or_release_claim(repo):
    now = stamp("2026-10-05T13:40:00Z")
    window = window_at(now)
    assert repo.claim_shadow_slot(window, "owner", now)
    with pytest.raises(RuntimeError, match="own"):
        complete(repo, window, "wrong-owner")
    repo.fail_shadow_slot(window.key, "wrong-owner", 11, "attempt")
    assert repo.shadow_slot(window.key).status == "CLAIMED"
    assert repo.recent_cycles() == []


def test_late_persistence_failure_keeps_claim_and_rolls_back_evidence(repo):
    from sqlalchemy import event
    from app.storage.models import ShadowCycleEvidenceRow

    now = stamp("2026-10-05T13:40:00Z")
    window = window_at(now)
    assert repo.claim_shadow_slot(window, "owner", now)

    def fail_on_link(session, flush_context, instances):
        if any(isinstance(row, ShadowCycleEvidenceRow) for row in session.new):
            raise RuntimeError("injected transaction failure")

    event.listen(repo.session_factory, "before_flush", fail_on_link)
    try:
        with pytest.raises(RuntimeError, match="transaction failure"):
            complete(repo, window, "owner")
    finally:
        event.remove(repo.session_factory, "before_flush", fail_on_link)
    assert repo.recent_cycles() == []
    assert repo.shadow_slot(window.key).cycle_id is None
    assert repo.shadow_slot(window.key).status == "CLAIMED"
    assert repo.active_shadow_slot() is not None


def test_review_activity_uses_new_york_day_and_ignores_unreviewed_proposals(repo, settings):
    from app.domain.models import Action, TradeDecision

    # 04:00 UTC is local midnight in October. UTC midnight must not reset the count.
    now = stamp("2026-10-06T03:59:00Z")
    decision = TradeDecision(
        action=Action.OPEN_LONG, symbol="SPY", confidence=.8, setup_quality=.8,
        desired_exposure_fraction=.5, invalidation_price=98, thesis="t",
        invalidation_reason="i", why_now="n",
    )
    from app.domain.models import RiskDecision
    risk = RiskDecision(
        approved=True, risk_mode="SMALL", requested_notional=5, approved_notional=4,
        planned_risk_dollars="0.08", planned_risk_fraction="0.008",
        effective_loss_distance="0.02", drawdown_modifier=1, confidence_modifier="0.9",
    )
    for value, reviewed in [("2026-10-05T03:59:00Z", True),
                            ("2026-10-05T04:01:00Z", True),
                            ("2026-10-06T03:58:00Z", False)]:
        packet = MarketPacket(
            as_of=stamp(value), candidates=[],
            account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
        )
        repo.save_shadow_cycle(
            packet, decision, risk,
            ExecutionResult(status="SKIPPED", broker_review={} if reviewed else None),
            "stub", prompt_version="v3-session-shadow", latency_ms=0,
            input_tokens=0, output_tokens=0, input_price=Decimal("0.1"),
            output_price=Decimal("0.5"), benchmark_symbol="SPY",
            reconciliation={"reconciled": True, "reasons": []},
        )
    reopened = Repository(make_session_factory(make_engine(settings.db_url)))
    assert reopened.shadow_review_activity(now) == (1, None)
    assert reopened.shadow_review_activity(stamp("2026-10-06T04:00:00Z")) == (0, None)


@pytest.mark.anyio
async def test_cli_weekend_tick_does_not_require_credentials_or_connect(
    monkeypatch, tmp_path, capsys,
):
    from app.robinhood import cli

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "ShadowScheduler", lambda repo, run: ShadowScheduler(
        repo, run, clock=lambda: stamp("2026-10-03T17:00:00Z"),
    ))

    def forbidden(*args):
        raise AssertionError("Closed scheduler must not initialize broker or agent")

    monkeypatch.setattr(cli, "_connection", forbidden)
    monkeypatch.setattr(cli, "OpenAIAgentsTrader", forbidden)
    code = await cli.shadow_run(Settings(robinhood_db_url=f"sqlite:///{tmp_path / 'weekend.db'}"),
                                "openai", once=True)
    assert code == 0
    assert "MARKET_CLOSED" in capsys.readouterr().out
