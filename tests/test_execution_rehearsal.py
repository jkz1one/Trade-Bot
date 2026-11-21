from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.config import Settings
from app.domain.models import AccountState, Candidate, MarketPacket, Quote, TradeDecision
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.models import OrderState, Snapshot, VenuePosition

NOW = datetime(2026, 10, 6, 15, tzinfo=UTC)
D = Decimal


def decision(action="OPEN_LONG", symbol="SPY"):
    return TradeDecision(
        action=action,
        symbol=symbol,
        confidence=0.8,
        setup_quality=0.8,
        desired_exposure_fraction=1,
        invalidation_price=D("9.50"),
        thesis="Fixture setup",
        invalidation_reason="Below support",
        why_now="Fixture",
    )


def packet(at=NOW, bid="9.99", ask="10"):
    return MarketPacket(
        as_of=at,
        account=AccountState(cash=10, buying_power=10, equity=10, high_watermark=10),
        candidates=[
            Candidate(
                quote=Quote(symbol="SPY", timestamp=at, bid=D(bid), ask=D(ask), last=D(ask)),
                atr_fraction=D(".01"),
                realized_vol_fraction=D(".01"),
            )
        ],
    )


@pytest.fixture
def ctx(tmp_path):
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(tmp_path / "execution.db", settings)
    venue = LocalFixtureVenue(D(10))
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    return engine, venue, settings


def open_order(ctx):
    engine, venue, _ = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW)) == OrderState.OPEN
    return intent


def test_governor_sizing_is_persisted_and_account_proposals_cannot_grant_cash(ctx):
    engine, _, _ = ctx
    p = packet().model_copy(
        update={
            "account": AccountState(cash=9999, buying_power=9999, equity=9999, high_watermark=9999)
        }
    )
    intent = engine.prepare("cycle-1", decision(), p, now=NOW)
    assert intent.approved_notional <= D(10)
    assert intent.quantity * intent.limit_price <= intent.approved_notional
    assert engine.journal.report()["orders"][0]["status"] == "PREPARED"
    assert engine.journal.report()["events"][0]["payload"]["risk"]["approved"]


def test_hold_is_audited_without_order_even_when_halted(ctx):
    engine, venue, _ = ctx
    engine.halt("operator pause", now=NOW)
    assert engine.prepare("hold", decision("HOLD", None), packet(), now=NOW) is None
    report = engine.journal.report()
    assert report["halted"] and report["orders"] == []
    assert report["events"][0]["kind"] == "HOLD"
    assert venue.submit_count == 0


def test_preparation_duplicate_conflict_and_inflight_lock(ctx):
    engine, _, _ = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    assert engine.prepare("cycle-1", decision(), packet(), now=NOW) == intent
    with pytest.raises(ExecutionBlocked, match="CONTENT_CONFLICT"):
        engine.prepare("cycle-1", decision("CLOSE"), packet(), now=NOW)
    with pytest.raises(ExecutionBlocked, match="IN_FLIGHT"):
        engine.prepare("cycle-2", decision(), packet(), now=NOW)


def test_restart_and_concurrent_dispatch_cannot_repeat_attempt(ctx):
    engine, venue, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    restarted = ExecutionEngine(engine.journal.path, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda e: e.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW)),
                [engine, restarted],
            )
        )
    assert venue.submit_count == 1
    assert (
        restarted.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW)) == OrderState.OPEN
    )
    assert venue.submit_count == 1


def test_partial_cancel_preserves_position_and_cash_then_full_close(ctx):
    engine, venue, settings = ctx
    intent = open_order(ctx)
    half = (intent.quantity / 2).quantize(D(".00000001"))
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, half, D(10), at, fill_id="buy-part")
    assert engine.reconcile(venue.snapshot(at), now=at)["new_fills"] == 1
    partial = engine.journal.report()
    assert partial["orders"][0]["status"] == "PARTIAL"
    assert partial["orders"][0]["active"]
    assert D(partial["ledger"]["position"]["quantity"]) == half
    assert D(partial["ledger"]["cash"]) == D(10) - half * 10
    venue.terminal(intent.client_id, "CANCELED", at)
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    assert not engine.journal.report()["orders"][0]["active"]
    restarted = ExecutionEngine(engine.journal.path, settings)
    exit_intent = restarted.prepare("exit", decision("CLOSE"), packet(at, "11", "11.01"), now=at)
    assert exit_intent.quantity == half
    restarted.dispatch(exit_intent.client_id, venue, now=at, packet=packet(at))
    venue.fill(exit_intent.client_id, half, D(11), at, fill_id="sell")
    assert restarted.reconcile(venue.snapshot(at), now=at)["reconciled"]
    report = restarted.journal.report()
    assert report["ledger"]["position"] is None
    assert D(report["ledger"]["cash"]) == D(10) + half
    assert D(report["ledger"]["realized_pnl"]) == half
    with pytest.raises(ExecutionBlocked, match="EXIT_COOLDOWN"):
        restarted.prepare("new-entry", decision(), packet(at), now=at)


def test_cumulative_fill_replays_do_not_change_ledger_or_count(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, intent.quantity, D(10), at, fill_id="one")
    snapshot = venue.snapshot(at, snapshot_id="fixed")
    assert engine.reconcile(snapshot, now=at)["new_fills"] == 1
    ledger = engine.journal.report()["ledger"]
    assert engine.reconcile(snapshot, now=at)["new_fills"] == 0
    assert engine.reconcile(venue.snapshot(at), now=at)["new_fills"] == 0
    assert engine.journal.report()["ledger"] == ledger
    assert len(engine.journal.report()["fills"]) == 1


def test_lost_ack_missing_order_never_expires_or_resubmits(ctx):
    engine, venue, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    venue.lose_next_ack = True
    assert (
        engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW)) == OrderState.UNKNOWN
    )
    restarted = ExecutionEngine(engine.journal.path, settings)
    later = NOW + timedelta(hours=1)
    missing = venue.snapshot(later).model_copy(update={"orders": []})
    assert "ATTEMPTED_ORDER_MISSING" in restarted.reconcile(missing, now=later)["issues"]
    assert (
        restarted.dispatch(intent.client_id, venue, now=later, packet=packet(later))
        == OrderState.UNKNOWN
    )
    with pytest.raises(ExecutionBlocked):
        restarted.abandon_prepared(intent.client_id, "expired", now=later)
    with pytest.raises(ExecutionBlocked):
        restarted.resume("assume no order", now=later)
    assert venue.submit_count == 1
    assert restarted.journal.report()["orders"][0]["active"]


def test_lost_ack_recovers_with_fill_evidence_but_requires_explicit_resume(ctx):
    engine, venue, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    venue.lose_next_ack = True
    engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW))
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, intent.quantity, D(10), at)
    restarted = ExecutionEngine(engine.journal.path, settings)
    assert restarted.reconcile(venue.snapshot(at), now=at)["reconciled"]
    assert restarted.journal.report()["halted"]
    restarted.resume("verified terminal fill and account", now=at)
    assert not restarted.journal.report()["halted"]
    assert venue.submit_count == 1


def test_process_crash_after_acceptance_preserves_attempt_before_ack(ctx, monkeypatch):
    engine, venue, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    accept = venue.accept

    def crash(intent, now):
        accept(intent, now)
        raise KeyboardInterrupt("simulated process loss")

    monkeypatch.setattr(venue, "accept", crash)
    with pytest.raises(KeyboardInterrupt):
        engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW))
    restarted = ExecutionEngine(engine.journal.path, settings)
    assert (
        restarted.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW))
        == OrderState.UNKNOWN
    )
    assert restarted.journal.report()["halted"]
    assert venue.submit_count == 1
    assert restarted.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    assert restarted.journal.report()["orders"][0]["status"] == "OPEN"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"complete": False}, "INCOMPLETE_SNAPSHOT"),
        ({"captured_at": NOW + timedelta(seconds=1)}, "FUTURE"),
        ({"captured_at": NOW - timedelta(seconds=91)}, "STALE"),
        ({"cash": D(9), "safe_buying_power": D(9)}, "CASH_MISMATCH"),
        ({"safe_buying_power": D(11)}, "LEVERAGED"),
        ({"unsupported_value": D(1)}, "UNSUPPORTED"),
        (
            {"positions": [VenuePosition(symbol="SPY", quantity=1, entry_price=10)]},
            "POSITION_MISMATCH",
        ),
    ],
)
def test_invalid_snapshot_blocks_atomically_and_latches(ctx, change, reason):
    engine, venue, _ = ctx
    before = engine.journal.report()["ledger"]
    bad = venue.snapshot(NOW).model_copy(update=change)
    result = engine.reconcile(bad, now=NOW)
    assert not result["reconciled"]
    assert any(reason in issue for issue in result["issues"])
    assert engine.journal.report()["ledger"] == before
    assert engine.journal.report()["halted"]
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    assert engine.journal.report()["halted"]


def test_bad_fill_snapshot_does_not_partially_commit_other_valid_fills(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, intent.quantity, D(10), at)
    bad = venue.snapshot(at).model_copy(update={"cash": D(10)})
    result = engine.reconcile(bad, now=at)
    assert result["issues"] == ["CASH_MISMATCH"]
    report = engine.journal.report()
    assert report["fills"] == [] and report["ledger"]["position"] is None
    assert report["orders"][0]["status"] == "OPEN"
    assert engine.reconcile(venue.snapshot(at), now=at)["new_fills"] == 1


def test_changed_fill_identity_and_terminal_regression_are_blocked(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, intent.quantity, D(10), at, fill_id="stable")
    snap = venue.snapshot(at)
    engine.reconcile(snap, now=at)
    obs = snap.orders[0]
    changed = obs.model_copy(update={"fills": [obs.fills[0].model_copy(update={"fee": D(".01")})]})
    issues = engine.reconcile(snap.model_copy(update={"orders": [changed]}), now=at)["issues"]
    assert "FILL_ID_CONFLICT" in issues and "TERMINAL_ORDER_CHANGED" in issues
    assert len(engine.journal.report()["fills"]) == 1


def test_unowned_order_and_changed_quantity_block(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    snap = venue.snapshot(NOW)
    obs = snap.orders[0]
    unowned = obs.model_copy(update={"client_id": "other"})
    assert (
        "UNOWNED_ORDER"
        in engine.reconcile(snap.model_copy(update={"orders": [unowned]}), now=NOW)["issues"]
    )
    resized = obs.model_copy(update={"quantity": intent.quantity + 1})
    assert (
        "ORDER_TERMS_MISMATCH"
        in engine.reconcile(snap.model_copy(update={"orders": [resized]}), now=NOW)["issues"]
    )


def test_halt_and_prepared_abandonment_persist(ctx):
    engine, venue, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    engine.halt("operator kill switch", now=NOW)
    restarted = ExecutionEngine(engine.journal.path, settings)
    with pytest.raises(ExecutionBlocked, match="HALTED"):
        restarted.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW))
    restarted.abandon_prepared(intent.client_id, "never attempted", now=NOW)
    restarted.resume("account checked", now=NOW)
    assert not restarted.journal.report()["halted"]
    assert venue.submit_count == 0


def test_unattempted_expiration_never_calls_venue(ctx):
    engine, venue, _ = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    assert (
        engine.dispatch(
            intent.client_id, venue, now=intent.expires_at, packet=packet(intent.expires_at)
        )
        == OrderState.EXPIRED
    )
    assert venue.submit_count == 0
    assert not engine.journal.report()["orders"][0]["active"]


def test_rehearsal_rejects_live_modes_generic_adapters_and_real_databases(ctx, tmp_path):
    engine, venue, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    for bad in [
        settings.model_copy(update={"mode": "LIVE"}),
        settings.model_copy(update={"live_enabled": True}),
    ]:
        with pytest.raises(ValueError, match="LIVE disabled"):
            ExecutionEngine(tmp_path / "forbidden.db", bad)
    with pytest.raises(ValueError, match="fixture venue"):
        engine.dispatch(intent.client_id, object(), now=NOW, packet=packet(NOW))
    assert venue.submit_count == 0
    path = tmp_path / "robinhood.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE synthetic_experiments(id TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="separate database"):
        ExecutionEngine(path, settings)
    assert path.read_bytes() == before


def test_config_changes_and_naive_evidence_are_rejected(ctx):
    engine, venue, settings = ctx
    with pytest.raises(ValueError, match="immutable"):
        ExecutionEngine(engine.journal.path, settings.model_copy(update={"max_daily_entries": 999}))
    with pytest.raises(ValueError, match="timezone-aware"):
        Snapshot(
            snapshot_id="bad", captured_at=NOW.replace(tzinfo=None), cash=10, safe_buying_power=10
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        engine.reconcile(venue.snapshot(NOW), now=NOW.replace(tzinfo=None))


def test_closed_market_and_stale_quote_preparation_fail_closed(ctx):
    engine, venue, _ = ctx
    later = NOW.replace(hour=21)
    engine.reconcile(venue.snapshot(later), now=later)
    with pytest.raises(ExecutionBlocked, match="MARKET_CLOSED"):
        engine.prepare("closed", decision(), packet(later), now=later)
    fresh = NOW + timedelta(days=1, seconds=91)
    engine.reconcile(venue.snapshot(fresh), now=fresh)
    stale = packet(fresh)
    stale.candidates[0].quote.timestamp = NOW
    with pytest.raises(ExecutionBlocked, match="STALE_QUOTE"):
        engine.prepare("stale", decision(), stale, now=fresh)


def test_report_reads_do_not_mutate_database(ctx):
    engine, _, _ = ctx
    before = engine.journal.path.read_bytes()
    engine.journal.report()
    assert engine.journal.path.read_bytes() == before


@pytest.mark.parametrize("status", ["CANCELED", "REJECTED", "EXPIRED"])
def test_only_observed_terminal_outcomes_release_attempted_reservations(ctx, status):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    venue.terminal(intent.client_id, status, NOW)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    assert engine.journal.report()["orders"][0]["status"] == status
    assert not engine.journal.report()["orders"][0]["active"]
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW)) == status
    assert venue.submit_count == 1


def test_snapshot_identity_conflict_and_time_regression_are_blocked(ctx):
    engine, venue, _ = ctx
    snap = venue.snapshot(NOW, snapshot_id="fixed")
    assert engine.reconcile(snap, now=NOW)["reconciled"]
    later = NOW + timedelta(seconds=1)
    assert (
        "SNAPSHOT_ID_CONFLICT"
        in engine.reconcile(snap.model_copy(update={"captured_at": later}), now=later)["issues"]
    )
    assert engine.reconcile(venue.snapshot(later), now=later)["reconciled"]
    assert "SNAPSHOT_TIME_REGRESSION" in engine.reconcile(snap, now=later)["issues"]


def test_partial_fill_then_missing_fill_evidence_cannot_release_capacity(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    at = NOW + timedelta(seconds=1)
    half = (intent.quantity / 2).quantize(D(".00000001"))
    venue.fill(intent.client_id, half, D(10), at)
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    snap = venue.snapshot(at)
    obs = snap.orders[0].model_copy(
        update={"fills": [], "filled_quantity": D(0), "status": "CANCELED"}
    )
    result = engine.reconcile(snap.model_copy(update={"orders": [obs]}), now=at)
    assert "KNOWN_FILLS_MISSING" in result["issues"]
    assert engine.journal.report()["orders"][0]["active"]


@pytest.mark.parametrize(
    "price,fee,reason",
    [
        (D("10.01"), D(0), "FILL_OUTSIDE_LIMIT"),
        (D(10), D(10), "APPROVED_BUDGET_EXCEEDED"),
    ],
)
def test_fill_limits_and_total_cash_budget_are_enforced(ctx, price, fee, reason):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    at = NOW + timedelta(seconds=1)
    # Model valid evidence with an adversarial price/fee; no fixture balance mutation.
    from app.execution.models import Fill, Observation

    obs = venue.orders[intent.client_id]
    fill = Fill(
        fill_id="adversarial",
        order_id=obs.order_id,
        quantity=intent.quantity,
        price=price,
        fee=fee,
        occurred_at=at,
    )
    bad = Observation(
        **{
            **obs.model_dump(),
            "status": "FILLED",
            "updated_at": at,
            "filled_quantity": intent.quantity,
            "fills": [fill],
        }
    )
    issues = engine.reconcile(venue.snapshot(at).model_copy(update={"orders": [bad]}), now=at)[
        "issues"
    ]
    assert reason in issues
    assert engine.journal.report()["fills"] == []


def test_daily_entry_limit_survives_close_cooldown_and_restart(tmp_path):
    settings = Settings(
        _env_file=None, mode="PAPER", live_enabled=False, starting_capital=10, max_daily_entries=1
    )
    engine = ExecutionEngine(tmp_path / "daily.db", settings)
    venue = LocalFixtureVenue(D(10))
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    intent = engine.prepare("buy", decision(), packet(), now=NOW)
    engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW))
    venue.fill(intent.client_id, intent.quantity, D(10), NOW)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    close = engine.prepare("sell", decision("CLOSE"), packet(NOW, "10", "10.01"), now=NOW)
    engine.dispatch(close.client_id, venue, now=NOW, packet=packet(NOW))
    venue.fill(close.client_id, close.quantity, D(10), NOW)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    later = NOW + timedelta(minutes=16)
    engine = ExecutionEngine(engine.journal.path, settings)
    engine.reconcile(venue.snapshot(later), now=later)
    with pytest.raises(ExecutionBlocked, match="DAILY_ENTRY_LIMIT"):
        engine.prepare("second", decision(), packet(later), now=later)


def test_kill_during_attempt_preserves_late_fill_evidence_without_resuming(ctx, monkeypatch):
    engine, venue, _ = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    accept = venue.accept

    def accept_then_halt(intent, now):
        order_id = accept(intent, now)
        engine.halt("operator halt after venue acceptance", now=now)
        return order_id

    monkeypatch.setattr(venue, "accept", accept_then_halt)
    engine.dispatch(intent.client_id, venue, now=NOW, packet=packet(NOW))
    venue.fill(intent.client_id, intent.quantity, D(10), NOW)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    assert engine.journal.report()["halted"]
    assert len(engine.journal.report()["fills"]) == 1


def test_cli_runs_without_network_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    import json
    import socket

    from app.execution.cli import main

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline rehearsal attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("TRADER_MODE", "LIVE")
    monkeypatch.setenv("TRADER_LIVE_ENABLED", "true")
    path = tmp_path / "cli.db"
    assert main(["run", "--db", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "OK" and output["live_enabled"] is False
    assert [o["status"] for o in output["orders"]] == ["CANCELED", "FILLED"]
    assert output["ledger"]["position"] is None and len(output["fills"]) == 2
    before = path.read_bytes()
    assert main(["report", "--db", str(path)]) == 0
    capsys.readouterr()
    assert path.read_bytes() == before
    assert main(["run", "--db", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["error_class"] == "FileExistsError"
    assert path.read_bytes() == before


def test_read_only_report_does_not_create_missing_database(tmp_path):
    from app.execution.journal import ExecutionJournal

    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        ExecutionJournal(path)
    assert not path.exists()


def test_fill_persistence_failure_rolls_back_order_ledger_and_snapshot(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, intent.quantity, D(10), at)
    before = engine.journal.report()
    with sqlite3.connect(engine.journal.path) as db:
        db.execute(
            "CREATE TRIGGER fail_fill BEFORE INSERT ON execution_fills "
            "BEGIN SELECT RAISE(ABORT, 'injected persistence failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        engine.reconcile(venue.snapshot(at), now=at)
    after = engine.journal.report()
    assert after["ledger"] == before["ledger"]
    assert after["orders"] == before["orders"] and after["fills"] == []
    assert after["events"] == before["events"]
    with pytest.raises(ExecutionBlocked, match="IN_FLIGHT"):
        engine.prepare("another", decision(), packet(at), now=at)
    with sqlite3.connect(engine.journal.path) as db:
        db.execute("DROP TRIGGER fail_fill")
    assert engine.reconcile(venue.snapshot(at), now=at)["new_fills"] == 1


def test_multiple_partial_fill_prices_and_fees_preserve_decimal_cash(ctx):
    engine, venue, _ = ctx
    intent = open_order(ctx)
    first = (intent.quantity / 2).quantize(D(".00000001"))
    at = NOW + timedelta(seconds=1)
    venue.fill(intent.client_id, first, D("9.90"), at, fee=D(".001"))
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    venue.fill(intent.client_id, intent.quantity - first, D("9.92"), at, fee=D(".001"))
    assert engine.reconcile(venue.snapshot(at), now=at)["new_fills"] == 1
    report = engine.journal.report()
    assert D(report["ledger"]["fees_paid"]) == D(".002")
    assert D(report["ledger"]["cash"]) == venue.cash
    assert D(report["ledger"]["position"]["quantity"]) == intent.quantity
    assert D(report["ledger"]["position"]["original_invalidation"]) == D("9.5")
    with pytest.raises(ExecutionBlocked, match="POSITION_ALREADY_OPEN"):
        engine.prepare("averaging", decision(), packet(at), now=at)


def test_actual_child_exit_leaves_durable_attempt_and_blocks_replay(ctx):
    import subprocess
    import sys

    engine, _, settings = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    script = """
import os
import sys
from datetime import datetime
from decimal import Decimal
from app.config import Settings
from app.execution.engine import ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
settings = Settings(_env_file=None, mode='PAPER', live_enabled=False, starting_capital=10)
engine = ExecutionEngine(sys.argv[1], settings)
venue = LocalFixtureVenue(Decimal(10))
accept = venue.accept
def die_after_accept(intent, now):
    accept(intent, now)
    os._exit(95)
venue.accept = die_after_accept
from tests.test_execution_rehearsal import packet
at = datetime.fromisoformat(sys.argv[3])
engine.dispatch(sys.argv[2], venue, now=at, packet=packet(at))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(engine.journal.path), intent.client_id, NOW.isoformat()],
        timeout=15,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 95, result.stderr.decode()
    assert engine.journal.report()["orders"][0]["status"] == "SUBMITTING"
    restarted = ExecutionEngine(engine.journal.path, settings)
    new_venue = LocalFixtureVenue(D(10))
    assert (
        restarted.dispatch(intent.client_id, new_venue, now=NOW, packet=packet(NOW))
        == OrderState.UNKNOWN
    )
    assert new_venue.submit_count == 0
    assert restarted.journal.report()["halted"]
    assert (
        "ATTEMPTED_ORDER_MISSING" in restarted.reconcile(new_venue.snapshot(NOW), now=NOW)["issues"]
    )


def test_buying_power_change_is_rechecked_before_attempt(ctx):
    engine, venue, _ = ctx
    intent = engine.prepare("cycle-1", decision(), packet(), now=NOW)
    at = NOW + timedelta(seconds=1)
    limited = venue.snapshot(at).model_copy(update={"safe_buying_power": D(1)})
    assert engine.reconcile(limited, now=at)["reconciled"]
    assert (
        engine.dispatch(intent.client_id, venue, now=at, packet=packet(at)) == OrderState.REJECTED
    )
    report = engine.journal.report()
    assert venue.submit_count == 0 and report["orders"][0]["attempted_at"] is None
    assert not report["orders"][0]["active"]
    assert report["events"][0]["kind"] == "PRE_DISPATCH_BLOCKED"
