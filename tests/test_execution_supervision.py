import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.models import TradeDecision
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from tests.test_execution_rehearsal import NOW, decision, packet

pytest_plugins = ["tests.test_execution_rehearsal"]

D = Decimal


def hold_position(context, *, at=NOW, overnight=False, partial=False):
    engine, venue, _ = context
    engine.reconcile(venue.snapshot(at), now=at)
    proposal = decision().model_copy(update={"hold_overnight": overnight})
    intent = engine.prepare("entry", proposal, packet(at), now=at)
    engine.dispatch(intent.client_id, venue, now=at, packet=packet(at))
    quantity = (intent.quantity / 2).quantize(D(".00000001")) if partial else intent.quantity
    venue.fill(intent.client_id, quantity, D(10), at, fill_id="entry-fill")
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    return intent


def observe(context, at, bid="10", ask="10.01"):
    engine, venue, _ = context
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    return packet(at, bid, ask)


def test_stop_latches_across_rebound_restart_and_model_hold(ctx):
    engine, venue, settings = ctx
    entry = hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at, "9.40", "9.41")
    hold = TradeDecision(
        action="HOLD",
        confidence=0,
        setup_quality=0,
        thesis="Model wants to hold",
        invalidation_reason="Wait",
        why_now="Wait",
    )
    assert engine.prepare("model-hold", hold, p, now=at) is None
    state = engine.journal.report()["ledger"]
    assert state["management"]["exit_reason"] == "INVALIDATION"
    assert D(state["position"]["original_invalidation"]) == D("9.50")
    assert venue.submit_count == 1
    restarted = ExecutionEngine(engine.journal.path, settings)
    p = observe((restarted, venue, settings), at)
    protective = restarted.prepare_protective_exit(p, now=at)
    assert protective.side == "SELL" and protective.quantity == entry.quantity
    assert protective.original_invalidation == D("9.5")
    assert restarted.prepare_protective_exit(packet(at, "10.01", "10.02"), now=at) == protective
    assert venue.submit_count == 1
    restarted.dispatch(protective.client_id, venue, now=at, packet=packet(at))
    venue.fill(protective.client_id, protective.quantity, protective.limit_price, at)
    assert restarted.reconcile(venue.snapshot(at), now=at)["reconciled"]
    assert restarted.journal.report()["ledger"]["management"] is None
    assert restarted.prepare_protective_exit(p, now=at) is None


@pytest.mark.parametrize("early", [False, True])
def test_session_exit_uses_actual_regular_close(ctx, early):
    engine, _, _ = ctx
    at = NOW.replace(month=11, day=27, hour=15) if early else NOW
    hold_position(ctx, at=at)
    window = engine.calendar.current_window(at)
    assert window.closes_at.hour == (18 if early else 20)
    trigger = window.closes_at - timedelta(minutes=15)
    p = observe(ctx, trigger)
    assert engine.supervise(p, now=trigger)["exit_reason"] == "SESSION_EXIT"
    assert engine.prepare_protective_exit(p, now=trigger).side == "SELL"


@pytest.mark.parametrize("overnight,expected", [(False, "MISSED_SESSION_EXIT"), (True, None)])
def test_explicit_overnight_permission_survives_restart(ctx, overnight, expected):
    engine, venue, settings = ctx
    hold_position(ctx, overnight=overnight)
    at = NOW + timedelta(days=1)
    restarted = ExecutionEngine(engine.journal.path, settings)
    p = observe((restarted, venue, settings), at)
    assert restarted.supervise(p, now=at)["exit_reason"] == expected
    assert restarted.journal.report()["ledger"]["management"]["hold_overnight"] is overnight


def test_overnight_permission_never_disables_stop(ctx):
    engine, _, _ = ctx
    hold_position(ctx, overnight=True)
    at = NOW + timedelta(days=1)
    p = observe(ctx, at, "9", "9.01")
    assert engine.supervise(p, now=at)["exit_reason"] == "INVALIDATION"


@pytest.mark.parametrize(
    "change,issue",
    [
        ("missing", "POSITION_QUOTE_MISSING"),
        ("stale", "POSITION_QUOTE_NOT_FRESH"),
        ("future", "POSITION_QUOTE_NOT_FRESH"),
        ("naive", "POSITION_QUOTE_NOT_FRESH"),
        ("crossed", "INSANE_POSITION_QUOTE"),
    ],
)
def test_unusable_quotes_halt_until_fresh_supervision(ctx, change, issue):
    engine, venue, settings = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at)
    if change == "missing":
        p.candidates = []
    elif change == "stale":
        p.candidates[0].quote.timestamp = at - timedelta(seconds=91)
    elif change == "future":
        p.candidates[0].quote.timestamp = at + timedelta(seconds=1)
    elif change == "naive":
        p.candidates[0].quote.timestamp = at.replace(tzinfo=None)
    else:
        p.candidates[0].quote.bid = D(11)
    result = engine.supervise(p, now=at)
    assert result["status"] == "BLOCKED" and result["issue"] == issue
    restarted = ExecutionEngine(engine.journal.path, settings)
    restarted.reconcile(venue.snapshot(at), now=at)
    with pytest.raises(ExecutionBlocked, match="SUPERVISION_REQUIRED"):
        restarted.resume("only account refreshed", now=at)
    assert restarted.supervise(packet(at), now=at)["status"] == "HOLD_POSITION"
    assert restarted.journal.report()["halted"]
    restarted.resume("fresh quote and account inspected", now=at)
    assert not restarted.journal.report()["halted"] and venue.submit_count == 1


def test_partial_entry_stop_requires_remainder_resolution(ctx):
    engine, venue, _ = ctx
    entry = hold_position(ctx, partial=True)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at, "9.40", "9.41")
    result = engine.supervise(p, now=at)
    assert (
        result["exit_reason"] == "INVALIDATION" and result["issue"] == "ENTRY_REMAINDER_UNRESOLVED"
    )
    with pytest.raises(ExecutionBlocked, match="REMAINDER"):
        engine.prepare_protective_exit(p, now=at)
    assert venue.submit_count == 1
    venue.terminal(entry.client_id, "CANCELED", at)
    engine.reconcile(venue.snapshot(at), now=at)
    assert engine.supervise(p, now=at)["status"] == "EXIT_REQUIRED"
    engine.resume("entry remainder conclusively canceled", now=at)
    assert engine.prepare_protective_exit(p, now=at).quantity == venue.position.quantity


def test_partial_exit_reuses_active_order_then_closes_known_remainder(ctx):
    engine, venue, _ = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at, "9.40", "9.41")
    first = engine.prepare_protective_exit(p, now=at)
    engine.dispatch(first.client_id, venue, now=at, packet=packet(at))
    half = (first.quantity / 2).quantize(D(".00000001"))
    venue.fill(first.client_id, half, first.limit_price, at)
    engine.reconcile(venue.snapshot(at), now=at)
    assert engine.supervise(p, now=at)["status"] == "EXIT_PENDING"
    assert engine.prepare_protective_exit(p, now=at) == first
    assert venue.submit_count == 2
    venue.terminal(first.client_id, "CANCELED", at)
    engine.reconcile(venue.snapshot(at), now=at)
    second = engine.prepare_protective_exit(p, now=at)
    assert second.client_id != first.client_id and second.quantity == venue.position.quantity


def test_expired_unattempted_exit_gets_new_identity(ctx):
    engine, venue, _ = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    first = engine.prepare_protective_exit(observe(ctx, at, "9.40", "9.41"), now=at)
    assert (
        engine.dispatch(
            first.client_id, venue, now=first.expires_at, packet=packet(first.expires_at)
        )
        == "EXPIRED"
    )
    at = first.expires_at
    second = engine.prepare_protective_exit(observe(ctx, at, "9.30", "9.31"), now=at)
    assert second.client_id != first.client_id and second.limit_price == D("9.30")
    assert venue.submit_count == 1


def test_entry_prepare_and_dispatch_block_late_session(ctx):
    engine, venue, _ = ctx
    at = NOW.replace(hour=19, minute=44, second=30)
    entry = engine.prepare("entry", decision(), observe(ctx, at), now=at)
    at += timedelta(seconds=30)
    assert engine.dispatch(entry.client_id, venue, now=at, packet=packet(at)) == "REJECTED"
    with pytest.raises(ExecutionBlocked, match="NO_FORWARD_SESSION"):
        engine.prepare("late", decision(), observe(ctx, at), now=at)
    assert venue.submit_count == 0


def test_bid_already_below_stop_cannot_open(ctx):
    engine, venue, _ = ctx
    with pytest.raises(ExecutionBlocked, match="ENTRY_INVALIDATED"):
        engine.prepare("invalidated", decision(), packet(NOW, "9.40", "10"), now=NOW)
    assert venue.submit_count == 0


def test_supervision_marks_high_watermark_without_orders(ctx):
    engine, venue, _ = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    assert engine.supervise(observe(ctx, at, "11", "11.01"), now=at)["status"] == "HOLD_POSITION"
    assert D(engine.journal.report()["ledger"]["high_watermark"]) > D(10)
    assert venue.submit_count == 1


def test_legacy_policy_is_recovered_from_approved_entry(ctx):
    engine, venue, settings = ctx
    hold_position(ctx, overnight=True)
    with engine.journal.write() as db:
        state = json.loads(engine._control(db)["ledger_json"])
        state.pop("management")
        db.execute("UPDATE execution_control SET ledger_json=? WHERE id=1", (json.dumps(state),))
    restarted = ExecutionEngine(engine.journal.path, settings)
    at = NOW + timedelta(seconds=1)
    assert (
        restarted.supervise(observe((restarted, venue, settings), at), now=at)["status"]
        == "HOLD_POSITION"
    )
    assert restarted.journal.report()["ledger"]["management"]["hold_overnight"] is True


def test_missing_entry_policy_and_calendar_failure_fail_closed(ctx):
    engine, venue, _ = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at)

    class BrokenCalendar:
        def current_window(self, now):
            raise RuntimeError("fixture failure")

    original = engine.calendar
    engine.calendar = BrokenCalendar()
    assert engine.supervise(p, now=at)["issue"] == "CALENDAR_FAILURE"
    engine.calendar = original
    with engine.journal.write() as db:
        state = json.loads(engine._control(db)["ledger_json"])
        state.pop("management")
        db.execute("UPDATE execution_control SET ledger_json=? WHERE id=1", (json.dumps(state),))
        approval = json.loads(
            db.execute("SELECT approval_json FROM execution_orders LIMIT 1").fetchone()[0]
        )
        approval["packet"]["session_context"] = None
        db.execute("UPDATE execution_orders SET approval_json=?", (json.dumps(approval),))
    assert engine.supervise(p, now=at)["issue"] == "POSITION_MANAGEMENT_NOT_PROVEN"
    with pytest.raises(ExecutionBlocked, match="SUPERVISION_REQUIRED"):
        engine.resume("cannot guess permission", now=at)
    assert venue.submit_count == 1


@pytest.mark.parametrize("change", ["clock", "quote", "packet", "closed", "account"])
def test_supervision_rejects_regression_and_unavailable_evidence(ctx, change):
    engine, _, _ = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=2)
    p = observe(ctx, at)
    assert engine.supervise(p, now=at)["status"] == "HOLD_POSITION"
    expected = {
        "clock": "SUPERVISION_TIME_REGRESSION",
        "quote": "POSITION_QUOTE_TIME_REGRESSION",
        "packet": "INVALID_SUPERVISION_PACKET_TIME",
        "closed": "OUTSIDE_REGULAR_SESSION",
        "account": "STALE_EXECUTION_SNAPSHOT",
    }[change]
    if change == "clock":
        with engine.journal.write() as db:
            state = json.loads(engine._control(db)["ledger_json"])
            state["management"]["last_supervised_at"] = (at + timedelta(seconds=1)).isoformat()
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1", (json.dumps(state),)
            )
    elif change == "quote":
        p.candidates[0].quote.timestamp -= timedelta(seconds=1)
    elif change == "packet":
        p.as_of -= timedelta(seconds=100)
    elif change == "closed":
        at = NOW.replace(hour=21)
        p = observe(ctx, at)
    else:
        at += timedelta(seconds=100)
        p = packet(at)
    result = engine.supervise(p, now=at)
    assert result["issue"] == expected and result["execution_halted"]
    with pytest.raises(ExecutionBlocked):
        engine.prepare_protective_exit(p, now=at)


def test_concurrent_protective_preparation_has_one_reservation(ctx):
    engine, venue, settings = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at, "9.4", "9.41")
    restarted = ExecutionEngine(engine.journal.path, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda e: e.prepare_protective_exit(p, now=at), [engine, restarted])
        )
    assert results[0] == results[1]
    assert sum(order["active"] for order in engine.journal.report()["orders"]) == 1
    assert venue.submit_count == 1


def test_supervision_persistence_failure_rolls_back_without_dispatch(ctx):
    engine, venue, _ = ctx
    hold_position(ctx)
    at = NOW + timedelta(seconds=1)
    p = observe(ctx, at, "9.4", "9.41")
    before = engine.journal.report()
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER fail_supervision BEFORE INSERT ON execution_events "
            "WHEN NEW.kind='POSITION_SUPERVISED' BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture"):
        engine.prepare_protective_exit(p, now=at)
    assert engine.journal.report() == before
    assert venue.submit_count == 1
