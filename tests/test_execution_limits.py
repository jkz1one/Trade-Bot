import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal
from app.execution.models import ExecutionLimits
from tests.test_execution_rehearsal import NOW, decision, packet

D = Decimal


def context(tmp_path, **overrides):
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    values = {
        "max_entry_notional": 3,
        "max_position_notional": 4,
        "total_loss_limit": 10,
        "daily_loss_limit": 10,
        **overrides,
    }
    limits = ExecutionLimits(**values)
    engine = ExecutionEngine(tmp_path / "limits.db", settings, limits=limits)
    venue = LocalFixtureVenue(D(10), account_id=limits.account_id)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    return engine, venue, settings


def enter(engine, venue, *, price=10, fee=0):
    price, fee = D(price), D(fee)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet()) == "OPEN"
    venue.fill(intent.client_id, intent.quantity, price, NOW, fee=fee, fill_id="buy")
    snap = venue.snapshot(NOW)
    assert engine.reconcile(snap, now=NOW)["new_fills"] == 1
    assert engine.reconcile(snap, now=NOW)["new_fills"] == 0
    return intent


def close(engine, venue, at, price="11", fee=0):
    fee = D(fee)
    p = packet(at, price, str(D(price) + D(".01")))
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    intent = engine.prepare("close", decision("CLOSE"), p, now=at)
    assert engine.dispatch(intent.client_id, venue, now=at, packet=p) == "OPEN"
    venue.fill(intent.client_id, intent.quantity, D(price), at, fee=fee, fill_id="sell")
    snap = venue.snapshot(at)
    assert engine.reconcile(snap, now=at)["new_fills"] == 1
    assert engine.reconcile(snap, now=at)["new_fills"] == 0
    return intent


def test_frozen_ceiling_clips_model_account_and_survives_restart(tmp_path):
    engine, venue, settings = context(tmp_path)
    p = packet()
    p.account = p.account.model_copy(
        update={"cash": D(999), "buying_power": D(999), "equity": D(999)}
    )
    intent = engine.prepare("entry", decision(), p, now=NOW)
    assert intent.approved_notional == D(3) and intent.quantity == D(".3")
    assert (
        "EXECUTION_NOTIONAL_CEILING"
        in engine.journal.report()["events"][0]["payload"]["risk"]["constraint_hits"]
    )
    with pytest.raises(ValidationError):
        engine.limits.max_entry_notional = D(999)
    with pytest.raises(ValueError, match="immutable"):
        ExecutionEngine(engine.journal.path, settings)
    changed = engine.limits.model_copy(update={"max_entry_notional": D(4)})
    with pytest.raises(ValueError, match="immutable"):
        ExecutionEngine(engine.journal.path, settings, limits=changed)
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    assert restarted.dispatch(intent.client_id, venue, now=NOW, packet=p) == "OPEN"


@pytest.mark.parametrize(
    "change",
    [
        {"max_entry_notional": 0},
        {"max_position_notional": "Infinity"},
        {"daily_loss_limit": "NaN"},
        {"account_id": " "},
        {"max_entry_notional": 5},
        {"total_loss_limit": 11},
    ],
)
def test_invalid_envelope_cannot_initialize(tmp_path, change):
    with pytest.raises(ValueError):
        context(tmp_path, **change)
    assert not (tmp_path / "limits.db").exists()


def test_foreign_snapshot_is_not_adopted_even_when_balances_match(tmp_path):
    engine, venue, _ = context(tmp_path, account_id="pinned-fixture")
    original = engine.journal.report()["ledger"]
    venue.account_id = "foreign-fixture"
    result = engine.reconcile(venue.snapshot(NOW), now=NOW)
    assert not result["reconciled"] and "EXECUTION_ACCOUNT_MISMATCH" in result["issues"]
    assert engine.journal.report()["ledger"] == original
    assert engine.journal.report()["halted"]


def test_foreign_dispatch_venue_halts_before_attempt(tmp_path):
    engine, venue, settings = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    foreign = LocalFixtureVenue(D(10), account_id="other")
    with pytest.raises(ExecutionBlocked, match="ACCOUNT_MISMATCH"):
        engine.dispatch(intent.client_id, foreign, now=NOW, packet=packet())
    assert foreign.submit_count == venue.submit_count == 0
    assert engine.journal.report()["orders"][0]["attempted_at"] is None
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    with pytest.raises(ExecutionBlocked, match="HALTED"):
        restarted.dispatch(intent.client_id, venue, now=NOW, packet=packet())


def test_gains_cannot_raise_ceiling_and_exits_are_not_capped(tmp_path):
    engine, venue, _ = context(tmp_path)
    buy = enter(engine, venue)
    at = NOW + timedelta(seconds=1)
    sell = close(engine, venue, at, "12")
    assert sell.approved_notional > engine.limits.max_entry_notional
    assert sell.quantity == buy.quantity
    later = at + timedelta(minutes=16)
    assert engine.reconcile(venue.snapshot(later), now=later)["reconciled"]
    second = engine.prepare("entry-2", decision(), packet(later), now=later)
    assert second.approved_notional == D(3)
    assert engine.journal.report()["ledger"]["daily_net_pnl"] == {"2026-10-06": "0.60000000"}


def test_daily_loss_includes_buy_fees_and_does_not_block_close(tmp_path):
    engine, venue, settings = context(tmp_path, daily_loss_limit=".02")
    buy = enter(engine, venue, price=D("9.9"), fee=D(".02"))
    assert engine.journal.report()["ledger"]["daily_net_pnl"] == {"2026-10-06": "-0.02"}
    at = NOW + timedelta(seconds=1)
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    assert restarted.reconcile(venue.snapshot(at), now=at)["reconciled"]
    with pytest.raises(ExecutionBlocked, match="DAILY_LOSS_LIMIT"):
        restarted.prepare("blocked", decision(), packet(at), now=at)
    sell = close(restarted, venue, at, "9.9")
    assert sell.quantity == buy.quantity
    later = at + timedelta(minutes=16)
    assert restarted.reconcile(venue.snapshot(later), now=later)["reconciled"]
    with pytest.raises(ExecutionBlocked, match="DAILY_LOSS_LIMIT"):
        restarted.prepare("blocked-flat", decision(), packet(later), now=later)
    tomorrow = NOW + timedelta(days=1)
    assert restarted.reconcile(venue.snapshot(tomorrow), now=tomorrow)["reconciled"]
    assert restarted.prepare("next-day", decision(), packet(tomorrow), now=tomorrow)


def test_total_dollar_loss_floor_survives_next_session(tmp_path):
    engine, venue, settings = context(tmp_path, total_loss_limit=".05", daily_loss_limit=".04")
    enter(engine, venue)
    at = NOW + timedelta(seconds=1)
    close(engine, venue, at, "9.8")
    assert D(engine.journal.report()["ledger"]["cash"]) == D("9.94")
    tomorrow = NOW + timedelta(days=1)
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    assert restarted.reconcile(venue.snapshot(tomorrow), now=tomorrow)["reconciled"]
    with pytest.raises(ExecutionBlocked, match="TOTAL_LOSS_LIMIT"):
        restarted.prepare("loss-floor", decision(), packet(tomorrow), now=tomorrow)
    event = restarted.journal.report()["events"][0]
    assert event["kind"] == "ADMISSION_BLOCKED" and "TOTAL_LOSS_LIMIT" in event["payload"]["reason"]
    restarted.resume("cannot raise a frozen dollar limit", now=tomorrow)
    with pytest.raises(ExecutionBlocked, match="TOTAL_LOSS_LIMIT"):
        restarted.prepare("still-blocked", decision(), packet(tomorrow), now=tomorrow)


def test_unrealized_loss_floor_does_not_block_protective_exit(tmp_path):
    engine, venue, _ = context(tmp_path, total_loss_limit=".05")
    enter(engine, venue)
    at = NOW + timedelta(seconds=1)
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    p = packet(at, "9.4", "9.41")
    with pytest.raises(ExecutionBlocked, match="TOTAL_LOSS_LIMIT"):
        engine.prepare("adding", decision(), p, now=at)
    protective = engine.prepare_protective_exit(p, now=at)
    assert engine.dispatch(protective.client_id, venue, now=at, packet=p) == "OPEN"


def test_daily_fee_and_realized_pnl_use_fill_dates_across_sessions(tmp_path):
    engine, venue, _ = context(tmp_path)
    enter(engine, venue, price=D("9.9"), fee=D(".01"))
    at = NOW + timedelta(days=1)
    close(engine, venue, at, "10.1", fee=D(".02"))
    report = engine.journal.report()
    pnl = {day: D(value) for day, value in report["ledger"]["daily_net_pnl"].items()}
    assert pnl == {"2026-10-06": D("-.01"), "2026-10-07": D(".04")}
    assert sum(pnl.values()) == D(report["ledger"]["realized_pnl"]) - D(
        report["ledger"]["fees_paid"]
    )


def test_late_fill_daily_fee_uses_new_york_date_not_utc_date(tmp_path):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("late-entry", decision(), packet(), now=NOW)
    engine.dispatch(intent.client_id, venue, now=NOW, packet=packet())
    at = (NOW + timedelta(days=1)).replace(hour=0, minute=30)
    venue.fill(intent.client_id, intent.quantity, D("9.9"), at, fee=D(".01"))
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    assert engine.journal.report()["ledger"]["daily_net_pnl"] == {"2026-10-06": "-0.01"}


def test_missing_dispatch_packet_preserves_unattempted_identity(tmp_path):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    with pytest.raises(ExecutionBlocked, match="FRESH_DISPATCH_PACKET_REQUIRED"):
        engine.dispatch(intent.client_id, venue, now=NOW)
    report = engine.journal.report()
    assert report["orders"][0]["status"] == "PREPARED" and venue.submit_count == 0
    assert report["events"][0]["kind"] == "DISPATCH_BLOCKED"
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet()) == "OPEN"
    assert engine.dispatch(intent.client_id, venue, now=NOW) == "OPEN"
    assert venue.submit_count == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ("duplicate", "DUPLICATE_MARKET_SYMBOLS"),
        ("crossed", "INSANE_QUOTE"),
        ("infinite", "INVALID_MARKET_PACKET"),
        ("stale", "INVALID_DISPATCH_PACKET_TIME"),
        ("future", "INVALID_DISPATCH_PACKET_TIME"),
        ("quote-back", "EVIDENCE_REGRESSION"),
        ("packet-back", "EVIDENCE_REGRESSION"),
        ("naive", "EVIDENCE_REGRESSION"),
    ],
)
def test_invalid_fresh_dispatch_evidence_never_attempts(tmp_path, change, reason):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    at = NOW + timedelta(seconds=1)
    p = packet(at)
    if change == "duplicate":
        p.candidates *= 2
    elif change == "crossed":
        p.candidates[0].quote.bid, p.candidates[0].quote.ask = D("9.99"), D("9.98")
    elif change == "infinite":
        p.candidates[0].quote.last = D("Infinity")
    elif change == "stale":
        p.as_of = at - timedelta(seconds=91)
    elif change == "future":
        p.as_of = at + timedelta(seconds=1)
    elif change == "quote-back":
        p.candidates[0].quote.timestamp = NOW - timedelta(seconds=1)
    elif change == "packet-back":
        p.as_of = NOW - timedelta(seconds=1)
    else:
        p.candidates[0].quote.timestamp = at.replace(tzinfo=None)
    with pytest.raises(ExecutionBlocked, match=reason):
        engine.dispatch(intent.client_id, venue, now=at, packet=p)
    assert venue.submit_count == 0
    assert engine.journal.report()["orders"][0]["attempted_at"] is None


@pytest.mark.parametrize("change", ["stop", "tradability", "volatility", "stale-quote"])
def test_fresh_market_changes_can_reject_previous_approval(tmp_path, change):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    at = NOW + timedelta(seconds=1)
    p = packet(at)
    if change == "stop":
        p.candidates[0].quote.bid = D("9.4")
    elif change == "tradability":
        p.candidates[0].quote.fractional_tradable = False
    elif change == "volatility":
        p.candidates[0].atr_fraction = D(".99")
    else:
        p.candidates[0].quote.timestamp = at + timedelta(seconds=1)
    assert engine.dispatch(intent.client_id, venue, now=at, packet=p) == "REJECTED"
    assert venue.submit_count == 0
    assert not engine.journal.report()["orders"][0]["active"]


def test_dispatch_risk_covers_original_limit_when_ask_falls(tmp_path):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    at = NOW + timedelta(seconds=1)
    p = packet(at, "9.8", "9.81")
    assert engine.dispatch(intent.client_id, venue, now=at, packet=p) == "OPEN"
    event = next(
        e for e in engine.journal.report()["events"] if e["kind"] == "PRE_DISPATCH_APPROVED"
    )
    assert D(event["payload"]["risk"]["effective_loss_distance"]) >= D(".05")


def test_legacy_journal_requires_explicit_new_envelope_not_silent_adoption(tmp_path):
    engine, _, settings = context(tmp_path)
    with engine.journal.write() as db:
        config = json.loads(engine._control(db)["config_json"])
        config.pop("execution_limits")
        db.execute(
            "UPDATE execution_control SET config_json=? WHERE id=1",
            (json.dumps(config, sort_keys=True),),
        )
    before = ExecutionJournal(engine.journal.path).report()
    with pytest.raises(ValueError, match="immutable"):
        ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    assert ExecutionJournal(engine.journal.path).report() == before


@pytest.mark.parametrize("change", ["capital", "limits", "universe", "risk", "live"])
def test_runtime_configuration_cannot_raise_journal_authority(tmp_path, change):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    if change == "capital":
        engine.settings.starting_capital = D(1000)
    elif change == "limits":
        engine.limits = ExecutionLimits(
            max_entry_notional=100,
            max_position_notional=100,
            total_loss_limit=10,
            daily_loss_limit=10,
        )
    elif change == "universe":
        engine.settings.initial_symbols.append("OTHER")
    elif change == "risk":
        engine.settings.max_daily_entries = 99
    else:
        engine.settings.live_enabled = True
    with pytest.raises(ExecutionBlocked, match="CONFIGURATION_CHANGED"):
        engine.dispatch(intent.client_id, venue, now=NOW, packet=packet())
    assert venue.submit_count == 0
    assert engine.journal.report()["orders"][0]["attempted_at"] is None
