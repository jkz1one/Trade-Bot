"""Native long-share carry, actual calendar bounds and original protection."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from test_mixed_accounting import buy, changed
from test_mixed_native_owner import close, intent_for, owned_mixed, proposal
from test_mixed_venue import q
from test_option_execution import NOW

from app.mixed.carry import (
    StockCarryPolicy,
    StockCarryTerms,
    StockCatalyst,
    calendar_path,
    derive_terms,
    review_entry,
)
from app.mixed.native_store import history, position, protection
from app.options.engine import OptionExecution
from app.robinhood.schedule import XNYSCalendar


def carry_policy(**changes):
    return StockCarryPolicy.model_validate(
        {
            "maximum_carry_sessions": 3,
            "maximum_calendar_days": 7,
            "exit_before_close_minutes": 15,
            "catalyst_source": "stock-catalyst",
            "catalyst_max_age_seconds": 30,
            **changes,
        }
    )


def original(p=None, at=NOW, end=date(2026, 10, 12)):
    pr = proposal(at)
    terms = derive_terms(
        p or carry_policy(),
        XNYSCalendar(),
        source_hash=pr.source_hash,
        catalyst=StockCatalyst(
            source="stock-catalyst",
            source_at=at,
            received_at=at,
            complete=True,
            entitlement="REALTIME",
            symbol=pr.instrument.symbol,
            status="CLEAR",
            valid_through=at + timedelta(days=10),
        ),
        now=at,
        exit_session=end,
    )
    return changed(pr, carry=terms, exit_at=terms.exit_at)


def enter_carry(e, v, *, pr=None):
    pr = pr or original()
    quote = q(buy(), NOW)
    out = e.prepare_stock("carry-entry", pr, quote, now=NOW)
    assert out["status"] == "PREPARED", out
    entry = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch_stock(entry.client_id, quote, now=NOW)) == "OPEN"
    at = NOW + timedelta(seconds=1)
    v.fill_stock(entry, entry.quantity, q(entry, at), at, fill_id="carry-fill")
    assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
    return entry


def test_calendar_weekend_and_early_close():
    cal = XNYSCalendar()
    path, deadline = calendar_path(carry_policy(), cal, date(2026, 11, 25), date(2026, 11, 27))
    assert [s.session for s in path] == [date(2026, 11, 25), date(2026, 11, 27)]
    assert deadline.hour == 17 and deadline.minute == 45
    assert path[-1].closes_at.hour == 18


@pytest.mark.parametrize(
    "start,end,changes,reason",
    [
        (date(2026, 10, 9), date(2026, 10, 9), {}, "SPAN"),
        (date(2026, 10, 9), date(2026, 10, 8), {}, "SPAN"),
        (date(2026, 10, 9), date(2026, 10, 19), {}, "SPAN"),
        (date(2026, 10, 10), date(2026, 10, 12), {}, "EXACT_SESSIONS"),
        (date(2026, 10, 9), date(2026, 10, 11), {}, "EXACT_SESSIONS"),
        (date(2026, 10, 9), date(2026, 10, 13), {"maximum_carry_sessions": 1}, "SESSION_LIMIT"),
    ],
)
def test_calendar_bounds(start, end, changes, reason):
    with pytest.raises(ValueError, match=reason):
        calendar_path(carry_policy(**changes), XNYSCalendar(), start, end)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "foreign"),
        ("symbol", "QQQ"),
        ("status", "UNKNOWN"),
        ("status", "BLOCKED"),
        ("complete", False),
        ("entitlement", "DELAYED"),
        ("source_at", NOW - timedelta(seconds=30)),
        ("received_at", NOW + timedelta(seconds=1)),
    ],
)
def test_catalyst_rejected_before_attempt(tmp_path, field, value):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, v):
        pr = original()
        catalyst = changed(pr.carry.catalyst, **{field: value})
        pr = changed(pr, carry=changed(pr.carry, catalyst=catalyst))
        out = e.prepare_stock("bad-catalyst", pr, q(buy(), NOW), now=NOW)
        assert out["status"] == "REJECTED", out
        assert v.snapshot(NOW).stock_orders == ()


@pytest.mark.parametrize("alter", ["path", "policy", "source", "deadline", "family"])
def test_original_carry_terms_cannot_be_rewritten(alter):
    pr = original()
    if alter == "path":
        pr = changed(
            pr,
            carry=changed(
                pr.carry,
                sessions=(changed(pr.carry.sessions[0], opens_at=NOW), pr.carry.sessions[-1]),
            ),
        )
    elif alter == "policy":
        pr = changed(pr, carry=changed(pr.carry, policy_hash="0" * 64))
    elif alter == "source":
        with pytest.raises(ValueError):
            changed(pr, source_hash="0" * 64)
        return
    elif alter == "family":
        with pytest.raises(ValueError):
            changed(pr, family="DEGEN")
        return
    else:
        with pytest.raises(ValueError):
            changed(pr, exit_at=pr.exit_at + timedelta(minutes=1))
        return
    with pytest.raises(ValueError, match="ORIGINAL_TERMS"):
        review_entry(carry_policy(), XNYSCalendar(), pr, NOW, 5)


def test_catalyst_does_not_extend_original_approval(tmp_path):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, v):
        pr = original()
        out = e.prepare_stock("deadline", pr, q(buy(), NOW), now=NOW)
        entry = intent_for(e, out["client_id"])
        assert entry.approval_expires_at <= pr.valid_until
        at = entry.approval_expires_at
        assert asyncio.run(e.dispatch_stock(entry.client_id, q(entry, at), now=at)) == "REJECTED"
        assert not v.snapshot(at).stock_orders


def test_legacy_owner_rejects_carry_terms(tmp_path):
    with owned_mixed(tmp_path) as (e, _v):
        out = e.prepare_stock("carry", original(), q(buy(), NOW), now=NOW)
        assert out["status"] == "REJECTED" and "NOT_ENROLLED" in out["reason"]


def test_enrollment_does_not_infer_missing_original_terms(tmp_path):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, _v):
        pr = original()
        out = e.prepare_stock("missing", changed(pr, carry=None), q(buy(), NOW), now=NOW)
        assert out["status"] == "REJECTED" and "NOT_ENROLLED" in out["reason"]


def test_native_weekend_restart_original_target_and_all_daily_costs(tmp_path):
    with owned_mixed(tmp_path, stock_carry=carry_policy(), daily_host_cost="1") as (e, v):
        entry = enter_carry(e, v)
        assert entry.order_expires_at == entry.carry.sessions[0].closes_at
        cutoff = entry.order_expires_at - timedelta(minutes=10)
        assert e.reconcile(v.snapshot(cutoff), now=cutoff)["reconciled"]
        assert e.assess_stock(q(entry, cutoff), now=cutoff)["status"] == "HEALTHY"
        night = entry.order_expires_at + timedelta(hours=12)
        assert e.reconcile(v.snapshot(night), now=night)["reconciled"]
        out = e.assess_stock(None, now=night)
        assert out["issue"] == "STOCK_CARRY_MARKET_CLOSED" and out["exit_reason"] is None
        limits, p = e.limits, e.policy
    at = entry.carry.sessions[-1].opens_at + timedelta(minutes=1)
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=at) as e:
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        assert e.assess_stock(q(entry, at), now=at)["status"] == "HEALTHY"
        with e.journal.read() as db:
            assert position(e, db).entry == entry
            assert len(history(e, db, as_of=at).costs) == 12
        _, done = close(e, v, entry, at + timedelta(seconds=1))
        assert e.journal.report(now=done)["stock_position"] is None
        assert e.journal.report(now=done)["loss_control"]["consumed_entries"] == 1
        # Four $1 calendar allocations turn the $3.76 execution win into a loss.
        assert e.journal.report(now=done)["loss_control"]["consecutive_losses"] == 1


@pytest.mark.parametrize(
    "trigger,bid,reason",
    [
        ("time", "100", "STOCK_TIME_EXIT"),
        ("stop", "89", "STOCK_INVALIDATION"),
        ("target", "120", "STOCK_TARGET"),
    ],
)
def test_original_held_protection_and_full_exit(tmp_path, trigger, bid, reason):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, v):
        entry = enter_carry(e, v)
        at = (
            entry.exit_at
            if trigger == "time"
            else entry.carry.sessions[-1].opens_at + timedelta(minutes=1)
        )
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        out = e.assess_stock(q(entry, at, bid=bid, ask=str(Decimal(bid) + Decimal(".01"))), now=at)
        assert out["exit_reason"] == reason
        out = asyncio.run(e.protective_stock_tick(q(entry, at), now=at))
        assert out["status"] == "OPEN", out
        closing = intent_for(e, out["client_id"])
        assert closing.carry == entry.carry and closing.exit_at == entry.exit_at


def test_missing_quote_at_original_deadline_keeps_latch(tmp_path):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, v):
        entry = enter_carry(e, v)
        at = entry.exit_at
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        out = e.assess_stock(None, now=at)
        assert out["status"] == "BLOCKED" and out["exit_reason"] == "STOCK_TIME_EXIT"
        with e.journal.read() as db:
            assert protection(e, db).exit_required_at == at


def test_catalyst_horizon_cannot_end_early():
    pr = original()
    with pytest.raises(ValueError, match="coverage"):
        StockCarryTerms.model_validate(
            {**pr.carry.model_dump(), "catalyst": changed(pr.carry.catalyst, valid_through=NOW)}
        )


def test_fresh_dispatch_cannot_replace_expired_original_catalyst(tmp_path):
    p = carry_policy(catalyst_max_age_seconds=1)
    with owned_mixed(tmp_path, stock_carry=p) as (e, v):
        pr = original(p)
        out = e.prepare_stock("expired-catalyst", pr, q(buy(), NOW), now=NOW)
        entry = intent_for(e, out["client_id"])
        at = NOW + timedelta(seconds=1)
        assert at < entry.approval_expires_at
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        assert asyncio.run(e.dispatch_stock(entry.client_id, q(entry, at), now=at)) == "REJECTED"
        assert not v.snapshot(at).stock_orders


def test_omitted_calendar_session_rejected():
    pr = original(end=date(2026, 10, 13))
    pr = changed(
        pr, carry=changed(pr.carry, sessions=(pr.carry.sessions[0], pr.carry.sessions[-1]))
    )
    with pytest.raises(ValueError, match="ORIGINAL_TERMS"):
        review_entry(carry_policy(), XNYSCalendar(), pr, NOW, 5)


def test_carry_does_not_allow_next_session_entry():
    pr = original()
    at = pr.carry.sessions[-1].opens_at
    with pytest.raises(ValueError, match="EXPIRED"):
        review_entry(carry_policy(), XNYSCalendar(), pr, at, 5)


def test_elapsed_horizon_at_closed_market_latches_without_dispatch(tmp_path):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, v):
        entry = enter_carry(e, v)
        at = entry.carry.sessions[-1].closes_at + timedelta(hours=1)
        out = asyncio.run(e.protective_stock_tick(q(entry, at), now=at))
        assert out["status"] == "BLOCKED" and out["exit_reason"] == "STOCK_TIME_EXIT"
        assert len(v.snapshot(at).stock_orders) == 1


def test_partial_close_retains_full_original_carry(tmp_path):
    with owned_mixed(tmp_path, stock_carry=carry_policy()) as (e, v):
        entry = enter_carry(e, v)
        at = entry.carry.sessions[-1].opens_at + timedelta(minutes=1)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        e.assess_stock(q(entry, at), now=at)
        closing, done = close(e, v, entry, at, quantity="1")
        assert closing.carry == entry.carry
        with e.journal.read() as db:
            assert position(e, db).entry == entry and position(e, db).quantity == 1
        assert e.assess_stock(q(entry, done), now=done)["status"] == "HEALTHY"
