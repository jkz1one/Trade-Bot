import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import event, func, select

from app.config import Settings
from app.domain.models import (
    AccountState, Action, Candidate, ExecutionResult, MarketPacket, Quote, TradeDecision,
)
from app.metrics.shadow_outcomes import forward_outcomes_report
from app.risk.governor import govern
from app.robinhood.cli import shadow_outcomes
from app.robinhood.schedule import XNYSCalendar
from app.storage.db import Base, init_db, make_engine, make_session_factory
from app.storage.models import (
    FillRow, OrderRow, ShadowForwardOutcomeRow,
)
from app.storage.repository import Repository


START = datetime.fromisoformat("2026-10-05T14:00:05+00:00")


def save_at(
    repo, at=START, *, action=Action.OPEN_LONG, stock_bid="100", stock_ask="100.10",
    spy_bid="200", spy_ask="200.10", stock_time=None, spy_time=None,
    reviewed=True, paid=True, model="gpt-6-luna", reconciled=True,
    error=None, blocked=False, scheduled=True, completion=None, missing=(),
    approved=None,
):
    settings = Settings(mode="SHADOW")
    window = XNYSCalendar().current_window(at)
    quotes = [
        Quote(symbol="AAPL", timestamp=stock_time or at, bid=stock_bid, ask=stock_ask, last=stock_bid),
        Quote(symbol="SPY", timestamp=spy_time or at, bid=spy_bid, ask=spy_ask, last=spy_bid),
    ]
    packet = MarketPacket(
        as_of=at, account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
        candidates=[Candidate(quote=q, atr_fraction="0.01", realized_vol_fraction="0.01")
                    for q in quotes if q.symbol not in missing],
        session_context=window.context() if scheduled and window else None,
    )
    decision = TradeDecision(
        action=action, symbol="AAPL" if action != Action.HOLD else None,
        confidence=.8, setup_quality=.8, desired_exposure_fraction=.5,
        invalidation_price=98, thesis="Supplied quote evidence", invalidation_reason="Test stop",
        why_now="Test observation",
    )
    risk = govern(decision, packet, settings, broker_reconciled=reconciled, now=at)
    if approved is not None:
        risk = risk.model_copy(update={"approved": approved})
    execution = ExecutionResult(
        status="SKIPPED", broker_review={} if reviewed and action == Action.OPEN_LONG else None,
        agent_error=error, session_blocked=blocked,
    )
    return repo.save_shadow_cycle(
        packet, decision, risk, execution, model, prompt_version="v3-session-shadow",
        latency_ms=10, input_tokens=100 if paid else 0, output_tokens=40 if paid else 0,
        input_price=Decimal("0.1"), output_price=Decimal("0.5"), benchmark_symbol="SPY",
        reconciliation={"reconciled": reconciled, "reasons": []},
        outcome_settings=settings, completed_at=completion or at + timedelta(seconds=1),
    )


def outcome(repo, source, horizon=15):
    return next(o for o in forward_outcomes_report(repo, 100)["outcomes"]
                if o["source_cycle_id"] == source and o["horizon_minutes"] == horizon)


def test_reviewed_entry_observation_has_exact_cost_and_paired_benchmark(repo, settings):
    source = save_at(repo)
    assert outcome(repo, source)["status"] == "PENDING"
    later = START + timedelta(minutes=15)
    measured = save_at(repo, later, stock_bid=102, stock_ask="102.10", spy_bid=201, spy_ask="201.10")
    result = outcome(repo, source)
    assert result["status"] == "OBSERVED"
    assert result["measurement_cycle_id"] == measured
    stock_return = Decimal("102") / Decimal("100.10") - 1
    benchmark_return = Decimal("201") / Decimal("200.10") - 1
    notional = Decimal(result["baseline"]["reference_notional"])
    cost = Decimal("0.00003")
    assert Decimal(result["result"]["quote_mark_return_fraction"]) == stock_return
    assert Decimal(result["result"]["benchmark_quote_mark_return_fraction"]) == benchmark_return
    assert Decimal(result["result"]["after_model_cost_change_dollars"]) == notional * stock_return - cost
    assert Decimal(result["result"]["after_model_cost_excess_fraction"]) == stock_return - cost / notional - benchmark_return
    assert outcome(repo, source, 60)["status"] == "PENDING"
    reopened = Repository(make_session_factory(make_engine(settings.db_url)))
    assert outcome(reopened, source) == result
    assert repo.load_open_position() is None
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FillRow)) == 0
        assert session.scalar(select(func.count()).select_from(OrderRow)) == 0


def test_cash_hold_is_first_class_and_cost_is_not_doubled_across_horizons(repo):
    source = save_at(repo, action=Action.HOLD)
    save_at(repo, START + timedelta(minutes=15), action=Action.HOLD, spy_bid=202, spy_ask="202.10")
    save_at(repo, START + timedelta(minutes=60), action=Action.HOLD, spy_bid=204, spy_ask="204.10")
    for horizon in (15, 60):
        row = outcome(repo, source, horizon)
        assert row["status"] == "OBSERVED"
        assert row["baseline"]["kind"] == "CASH_HOLD"
        assert row["baseline"]["reference_notional"] == "10"
        assert Decimal(row["result"]["quote_mark_change_dollars"]) == 0
        assert Decimal(row["result"]["after_model_cost_change_dollars"]) == Decimal("-0.00003")
    report = forward_outcomes_report(repo, 100)
    assert Decimal(report["database_reported_model_cost"]) == Decimal("0.00009")
    assert report["strategy_pnl"] is None and report["economic_pnl"] is None
    assert {g["horizon_minutes"] for g in report["groups"]} == {15, 60}


@pytest.mark.parametrize("kwargs, reason", [
    ({"reviewed": False}, "ENTRY_NOT_APPROVED_AND_REVIEWED"),
    ({"approved": False}, "ENTRY_NOT_APPROVED_AND_REVIEWED"),
    ({"model": "stub"}, "NO_LINKED_MODEL_USAGE"),
    ({"paid": False}, "NO_LINKED_MODEL_USAGE"),
    ({"error": "RateLimitError"}, "AGENT_FAILURE"),
    ({"reconciled": False}, "RECONCILIATION_FAILED"),
    ({"blocked": True}, "SESSION_BLOCKED"),
    ({"scheduled": False}, "OUTSIDE_SCHEDULED_SESSION"),
    ({"action": Action.CLOSE}, "UNSUPPORTED_ACTION_OR_POSITION"),
    ({"action": Action.HOLD, "spy_bid": 201, "spy_ask": 200}, "CROSSED_QUOTES"),
    ({"action": Action.HOLD, "spy_time": START + timedelta(seconds=1)}, "STALE_OR_FUTURE_QUOTES"),
    ({"action": Action.HOLD, "spy_time": START - timedelta(seconds=91)}, "STALE_OR_FUTURE_QUOTES"),
    ({"action": Action.HOLD, "spy_time": START.replace(tzinfo=None)}, "INVALID_QUOTE_TIME"),
])
def test_ineligible_sources_are_explicitly_excluded(repo, kwargs, reason):
    source = save_at(repo, **kwargs)
    for horizon in (15, 60):
        row = outcome(repo, source, horizon)
        assert row["status"] == "EXCLUDED" and row["reason"] == reason
        assert row["result"] is None


@pytest.mark.parametrize("invalid", ["stale", "future", "missing", "pre_target", "crossed", "mismatch", "unscheduled"])
def test_invalid_future_pair_waits_for_fresh_pair_without_inventing_measurement(repo, invalid):
    source = save_at(repo)
    due = START.replace(second=0) + timedelta(minutes=15)
    at = due + timedelta(seconds=10)
    kwargs = {"stock_bid": 102, "stock_ask": "102.10", "spy_bid": 201, "spy_ask": "201.10"}
    if invalid == "stale":
        kwargs["spy_time"] = at - timedelta(seconds=91)
    elif invalid == "future":
        kwargs["stock_time"] = at + timedelta(seconds=1)
    elif invalid == "missing":
        kwargs["missing"] = ("AAPL",)
    elif invalid == "pre_target":
        kwargs["spy_time"] = due - timedelta(seconds=1)
    elif invalid == "crossed":
        kwargs["spy_ask"] = 200
    elif invalid == "mismatch":
        kwargs["reconciled"] = False
    else:
        kwargs["scheduled"] = False
    save_at(repo, at, **kwargs)
    row = outcome(repo, source)
    assert row["status"] == "PENDING" and row["reason"]
    assert row["measurement_cycle_id"] is None and row["result"] is None
    observed = save_at(repo, at + timedelta(seconds=30), stock_bid=102, stock_ask="102.10",
                       spy_bid=201, spy_ask="201.10")
    assert outcome(repo, source)["status"] == "OBSERVED"
    assert outcome(repo, source)["measurement_cycle_id"] == observed


def test_first_eligible_future_observation_never_changes_on_later_cycles(repo):
    source = save_at(repo)
    save_at(repo, START + timedelta(minutes=14), stock_bid=101, stock_ask="101.10")
    assert outcome(repo, source)["status"] == "PENDING"
    save_at(repo, START + timedelta(minutes=15), stock_bid=102, stock_ask="102.10")
    first = outcome(repo, source)
    save_at(repo, START + timedelta(minutes=16), stock_bid=103, stock_ask="103.10")
    assert outcome(repo, source) == first


def test_concurrent_connections_record_only_one_immutable_measurement(repo, settings):
    source = save_at(repo)
    barrier = Barrier(2)

    def measure(index):
        independent = Repository(make_session_factory(make_engine(settings.db_url)))
        barrier.wait(timeout=5)
        at = START + timedelta(minutes=15, seconds=index)
        return save_at(independent, at, stock_bid=102 + index, stock_ask=Decimal("102.10") + index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cycle_ids = list(pool.map(measure, [0, 1]))
    row = outcome(repo, source)
    assert row["status"] == "OBSERVED" and row["measurement_cycle_id"] in cycle_ids
    assert len([o for o in repo.shadow_forward_outcomes() if o.source_cycle_id == source]) == 2
    first = row.copy()
    save_at(repo, START + timedelta(minutes=16), stock_bid=104, stock_ask="104.10")
    assert outcome(repo, source) == first


def test_missing_window_expires_and_next_session_cannot_backfill(repo):
    source = save_at(repo)
    save_at(repo, START.replace(second=0) + timedelta(minutes=20))
    assert outcome(repo, source)["status"] == "EXPIRED"
    assert outcome(repo, source)["result"] is None
    save_at(repo, START + timedelta(days=1), stock_bid=102, stock_ask="102.10")
    assert outcome(repo, source)["status"] == "EXPIRED"
    assert outcome(repo, source, 60)["status"] == "EXPIRED"


@pytest.mark.parametrize("late_slot", ["2026-10-05T19:45:05+00:00", "2026-11-27T17:45:05+00:00"])
def test_end_of_session_and_slow_decision_do_not_create_backward_marks(repo, late_slot):
    source = save_at(repo, datetime.fromisoformat(late_slot))
    assert all(outcome(repo, source, h)["reason"] == "NO_FORWARD_WINDOW_IN_SESSION" for h in (15, 60))
    slow = save_at(repo, completion=START + timedelta(minutes=16))
    assert outcome(repo, slow)["status"] == "EXCLUDED"
    assert outcome(repo, slow, 60)["status"] == "PENDING"


def test_market_quotes_can_measure_prior_proposal_even_if_current_model_fails(repo):
    source = save_at(repo)
    save_at(repo, START + timedelta(minutes=15), action=Action.HOLD, error="RateLimitError", paid=False)
    assert outcome(repo, source)["status"] == "OBSERVED"


def test_atomic_failure_rolls_back_new_cycle_and_prior_measurement(repo):
    source = save_at(repo)

    def fail_on_outcome(session, flush_context, instances):
        if any(isinstance(row, ShadowForwardOutcomeRow) for row in session.new):
            raise RuntimeError("injected late outcome persistence failure")

    event.listen(repo.session_factory, "before_flush", fail_on_outcome)
    try:
        with pytest.raises(RuntimeError, match="outcome persistence failure"):
            save_at(repo, START + timedelta(minutes=15))
    finally:
        event.remove(repo.session_factory, "before_flush", fail_on_outcome)
    assert len(repo.recent_cycles()) == 1
    assert outcome(repo, source)["status"] == "PENDING"
    assert Decimal(repo.model_cost_total()) == Decimal("0.00003")
    save_at(repo, START + timedelta(minutes=15))
    assert outcome(repo, source)["status"] == "OBSERVED"


def test_report_limits_whole_source_cycles_and_is_local_only(repo, settings, capsys):
    first = save_at(repo)
    last = save_at(repo, START + timedelta(minutes=15))
    report = forward_outcomes_report(repo, 1)
    assert len(report["outcomes"]) == 2
    assert {o["source_cycle_id"] for o in report["outcomes"]} == {last}
    assert first != last and report["groups"] == []
    assert shadow_outcomes(Settings(robinhood_db_url=settings.db_url), 100) == 0
    assert json.loads(capsys.readouterr().out)["network_calls"] is False
    for limit in (0, -1, 10001):
        with pytest.raises(ValueError):
            forward_outcomes_report(repo, limit)


def test_existing_database_adds_table_without_backfilling_legacy_cycles(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables
                                           if t.name != "shadow_forward_outcomes"])
    repo = Repository(make_session_factory(engine))
    packet = MarketPacket(as_of=START, candidates=[], account=AccountState(
        equity=10, cash=10, buying_power=10, high_watermark=10,
    ))
    decision = TradeDecision(action=Action.HOLD, confidence=0, setup_quality=0,
                             thesis="Legacy HOLD", invalidation_reason="No trade", why_now="Wait")
    repo.save_cycle(packet, decision, govern(decision, packet, Settings()),
                    ExecutionResult(status="SKIPPED"), "gpt-6-luna")
    init_db(engine)
    assert len(repo.recent_cycles()) == 1
    assert forward_outcomes_report(repo, 100)["status"] == "EMPTY"
