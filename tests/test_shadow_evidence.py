import json
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select

from app.agent.trader import OpenAIAgentsTrader, StubTraderAgent, fail_closed_agent_run
from app.config import Settings
from app.domain.models import AccountState, Candidate, ExecutionResult, MarketPacket, Quote, utc_now
from app.metrics.shadow import shadow_history_report
from app.risk.governor import govern
from app.robinhood.cli import shadow_audit, shadow_history
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.models import (
    AccountSnapshotRow, Base, BenchmarkSnapshotRow, DecisionCycleRow,
    ModelUsageRow, ShadowCycleEvidenceRow,
)
from app.storage.repository import Repository


def save_evidence(repo, *, price="100", paid=False, failed=False, stub=False):
    now = utc_now()
    packet = MarketPacket(
        as_of=now,
        account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
        candidates=[Candidate(
            quote=Quote(symbol="SPY", timestamp=now, bid=price, ask=price, last=price),
            atr_fraction="0.01", realized_vol_fraction="0.01",
        )] if price else [],
    )
    run = (fail_closed_agent_run(RuntimeError("secret")) if failed
           else StubTraderAgent().decide(packet))
    risk = govern(run.decision, packet, Settings(mode="SHADOW"))
    execution = ExecutionResult(status="SKIPPED", agent_error=run.error)
    cycle_id = repo.save_shadow_cycle(
        packet, run.decision, risk, execution, "stub" if stub else "gpt-6-luna",
        prompt_version="v2-live-shadow", latency_ms=1,
        input_tokens=100 if paid else 0, output_tokens=40 if paid else 0,
        input_price=Decimal("0.10"), output_price=Decimal("0.50"),
        benchmark_symbol="SPY", reconciliation={"reconciled": True, "reasons": []},
    )
    return cycle_id


def test_failed_cycle_does_not_inherit_previous_usage(repo, settings, capsys):
    paid_id = save_evidence(repo, paid=True)
    failed_id = save_evidence(repo, failed=True)
    assert repo.latest_model_usage() is not None
    assert repo.shadow_cycle_evidence(paid_id)["model_usage"]["input_tokens"] == 100
    assert repo.shadow_cycle_evidence(failed_id)["model_usage"] is None
    assert shadow_audit(Settings(robinhood_db_url=settings.db_url)) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["cycle_id"] == failed_id
    assert audit["latest_model_usage"] is None
    assert audit["cycle_evidence_status"] == "LINKED"
    assert audit["execution"]["agent_error"] == "RuntimeError"
    assert Decimal(audit["model_cost_total"]) == Decimal("0.00003")


def test_atomic_evidence_rolls_back_all_rows_on_late_failure(repo):
    factory = repo.session_factory

    def fail_on_link(session, flush_context, instances):
        if any(isinstance(row, ShadowCycleEvidenceRow) for row in session.new):
            raise RuntimeError("injected persistence failure")

    event.listen(factory, "before_flush", fail_on_link)
    try:
        with pytest.raises(RuntimeError, match="injected persistence failure"):
            save_evidence(repo, paid=True)
    finally:
        event.remove(factory, "before_flush", fail_on_link)
    with factory() as session:
        for model in (DecisionCycleRow, ModelUsageRow, AccountSnapshotRow,
                      BenchmarkSnapshotRow, ShadowCycleEvidenceRow):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_existing_database_upgrade_preserves_legacy_and_does_not_guess_usage(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    legacy_tables = [t for t in Base.metadata.sorted_tables if t.name != "shadow_cycle_evidence"]
    Base.metadata.create_all(engine, tables=legacy_tables)
    repo = Repository(make_session_factory(engine))
    packet = MarketPacket(
        as_of=utc_now(), candidates=[],
        account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
    )
    decision = StubTraderAgent().decide(packet).decision
    repo.save_cycle(packet, decision, govern(decision, packet, Settings()),
                    ExecutionResult(status="SKIPPED"), "gpt-6-luna")
    repo.save_model_usage("gpt-6-luna", 100, 40, Decimal("0.1"), Decimal("0.5"))
    legacy_id = repo.recent_cycles()[0].id
    init_db(engine)
    assert len(repo.recent_cycles()) == 1
    evidence = repo.shadow_cycle_evidence(legacy_id)
    assert evidence["status"] == "LEGACY_UNLINKED"
    assert evidence["model_usage"] is None
    assert repo.model_cost_total() == Decimal("0.00003")
    save_evidence(repo, stub=True)
    assert len(repo.recent_cycles()) == 2
    assert repo.shadow_cycle_evidence(legacy_id)["status"] == "LEGACY_UNLINKED"


def test_history_survives_restart_distinguishes_errors_and_reports_only_known_cost(
    repo, settings, capsys,
):
    first_id = save_evidence(repo, paid=True)
    save_evidence(repo, failed=True, price="105")
    last_id = save_evidence(repo, stub=True, price="110")
    reopened = Repository(make_session_factory(make_engine(settings.db_url)))
    report = shadow_history_report(reopened, "SPY", 100)
    assert report["cycle_count"] == 3
    assert report["action_counts"] == {"HOLD": 3}
    assert report["model_counts"] == {"gpt-6-luna": 2, "stub": 1}
    assert report["genuine_hold_count"] == 2
    assert report["agent_failure_count"] == 1
    assert report["linked_cycle_count"] == 3
    assert report["usage_reported_cycle_count"] == 1
    assert Decimal(report["window_reported_model_cost"]) == Decimal("0.00003")
    assert report["benchmark"]["first"]["cycle_id"] == first_id
    assert report["benchmark"]["last"]["cycle_id"] == last_id
    assert Decimal(report["benchmark"]["raw_price_return_fraction"]) == Decimal("0.1")
    assert report["strategy_pnl"] is None
    assert report["economic_pnl"] is None
    window = shadow_history_report(reopened, "SPY", 1)
    assert window["cycle_count"] == 1
    assert Decimal(window["window_reported_model_cost"]) == 0
    assert window["benchmark"]["raw_price_return_fraction"] is None
    assert shadow_history(Settings(robinhood_db_url=settings.db_url), 1) == 0
    assert json.loads(capsys.readouterr().out)["cycle_count"] == 1


def test_no_benchmark_or_usage_is_reported_as_missing(repo):
    cycle_id = save_evidence(repo, price=None)
    assert repo.shadow_cycle_evidence(cycle_id)["model_usage"] is None
    assert repo.benchmark_range("SPY") is None
    report = shadow_history_report(repo, "SPY", 10)
    assert report["benchmark"]["sample_count"] == 0
    assert report["benchmark"]["raw_price_return_fraction"] is None


def test_empty_history_and_limit_validation(repo):
    assert shadow_history_report(repo, "SPY", 100)["status"] == "EMPTY"
    for limit in (0, -1, 10001):
        with pytest.raises(ValueError):
            shadow_history_report(repo, "SPY", limit)


def test_stub_and_model_identity_are_distinct():
    assert StubTraderAgent().model_identifier == "stub"
    assert OpenAIAgentsTrader("gpt-6-luna").model_identifier == "gpt-6-luna"
