"""Installed fixed-child mixed venue proof; this is not native owner acceptance."""

import asyncio
import json
import os
import sqlite3
import time
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from test_mixed_accounting import buy, changed, history, policy, sell, trade
from test_option_execution import NOW, configuration, intent_for, owned, quote_at

from app.execution.process import (
    FixtureProcessFailed,
    FixtureProcessProtocolError,
    FixtureProcessTimeout,
)
from app.mixed.accounting import reconstruct
from app.mixed.models import OptionTrade, Settlement, StockTrade
from app.mixed.stock_models import StockObservation
from app.options.engine import OptionExecution
from app.options.lifecycle import OptionLedger, OptionReceipt, OptionVenueSnapshot
from app.options.process import OptionRequest, run_option_process
from app.options.venue import DurableOptionVenue

D = Decimal


def venue_at(tmp_path, *, limits=None, fault="NONE"):
    p = policy()
    return DurableOptionVenue(
        tmp_path / "mixed.db",
        limits=p.options,
        stock_limits=limits or p.stocks,
        capital=p.capital,
        fault=fault,
    )


def accept(venue, intent, at=None, timeout=3):
    return asyncio.run(
        run_option_process(
            venue, now=at or intent.prepared_at, timeout_seconds=timeout, stock_intent=intent
        )
    ).order_id


def q(entry, at=None, **changes):
    return changed(
        trade(entry, 1, at=at or entry.prepared_at + timedelta(seconds=1)).fill.quote, **changes
    )


def original_option(tmp_path):
    with owned(tmp_path / "mint") as (engine, _, data):
        result = engine.prepare(
            "option-original", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        return intent_for(engine, result["client_id"]), data


def state_bytes(venue):
    with sqlite3.connect(venue.path) as db:
        return db.execute("SELECT state FROM option_fixture_control").fetchone()[0]


def corrupt(venue, *, state=None, meta=None):
    with sqlite3.connect(venue.path) as db:
        for column, action in (("state", state), ("meta", meta)):
            if action is not None:
                value = json.loads(
                    db.execute("SELECT " + column + " FROM option_fixture_control").fetchone()[0]
                )
                action(value)
                db.execute(
                    "UPDATE option_fixture_control SET " + column + "=?", (json.dumps(value),)
                )


def test_stock_round_trip_partial_fills_restart_and_explicit_settlement(tmp_path):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    order = accept(venue, entry)
    first = venue.fill_stock(entry, "1", q(entry), NOW + timedelta(seconds=1), fill_id="first")
    assert first.order_id == order and first.fee == D(".11") and first.sequence == 1
    reopened = DurableOptionVenue(venue.path)
    assert reopened.stock_limits == policy().stocks
    second = reopened.fill_stock(
        entry,
        "1",
        q(entry, NOW + timedelta(seconds=2)),
        NOW + timedelta(seconds=2),
        fill_id="second",
    )
    assert second.fee == D(".01") and second.sequence == 2
    snap = asyncio.run(
        run_option_process(reopened, now=NOW + timedelta(seconds=2), timeout_seconds=3)
    ).snapshot
    assert snap.stock_orders[0].intent == entry
    assert snap.cash == snap.settled_cash == D("799.88")
    assert snap.stock_position.entry == entry and snap.stock_position.quantity == 2
    close = sell(entry, at=NOW + timedelta(seconds=3))
    accept(reopened, close)
    c1 = reopened.fill_stock(
        close, "1", q(close), NOW + timedelta(seconds=4), fill_id="close-first"
    )
    c2 = reopened.fill_stock(
        close,
        "1",
        q(close, NOW + timedelta(seconds=5)),
        NOW + timedelta(seconds=5),
        fill_id="close-last",
    )
    snap = reopened.snapshot(NOW + timedelta(seconds=5))
    assert snap.stock_position is None and snap.position is None
    assert snap.cash == D("1003.76") and snap.settled_cash == D("799.88")
    receipt = OptionReceipt(
        receipt_id="settled",
        sequence=5,
        kind="FUNDS_SETTLED",
        occurred_at=NOW + timedelta(seconds=6),
        cash_change="203.88",
    )
    reopened.record_receipt(receipt)
    events = tuple(
        StockTrade(intent=i, attempted_at=i.prepared_at, fill=f)
        for i, f in ((entry, first), (entry, second), (close, c1), (close, c2))
    ) + (Settlement(receipt=receipt),)
    projected = reconstruct(
        history(events, venue_id=venue.venue_id, captured_at=receipt.occurred_at)
    )
    final = reopened.snapshot(receipt.occurred_at)
    assert projected.ledger.cash == final.cash == final.settled_cash
    assert projected.ledger.realized_pnl == 4 and projected.ledger.fees_paid == D(".24")
    assert reopened.submit_count == 2


def test_stock_option_stock_continuity_uses_one_original_capital(tmp_path):
    option, data = original_option(tmp_path)
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    f1 = venue.fill_stock(entry, "2", q(entry), NOW + timedelta(seconds=1), fill_id="s1")
    close = sell(entry, at=NOW + timedelta(seconds=2))
    accept(venue, close)
    f2 = venue.fill_stock(close, "2", q(close), NOW + timedelta(seconds=3), fill_id="s2")
    asyncio.run(
        run_option_process(venue, now=NOW + timedelta(seconds=3), timeout_seconds=3, intent=option)
    )
    f3 = venue.fill(
        option,
        option.quantity,
        quote_at(data, NOW + timedelta(seconds=4)),
        NOW + timedelta(seconds=4),
        fill_id="o1",
    )
    snap = venue.snapshot(NOW + timedelta(seconds=4))
    assert snap.stock_position is None and snap.position.quantity == option.quantity
    assert snap.cash == D("1003.76") - (f3.quantity * f3.price * 100 + f3.fee)
    option_close = changed(
        option,
        client_id="option-close",
        source_key="option-close",
        side="SELL",
        prepared_at=NOW + timedelta(seconds=5),
        approval_expires_at=NOW + timedelta(seconds=8),
        limit_price=".90",
        approved_entry_debit="0",
        approved_full_premium_loss="0",
    )
    asyncio.run(
        run_option_process(
            venue, now=option_close.prepared_at, timeout_seconds=3, intent=option_close
        )
    )
    f4 = venue.fill(
        option_close,
        option_close.quantity,
        quote_at(data, NOW + timedelta(seconds=6)),
        NOW + timedelta(seconds=6),
        fill_id="o2",
    )
    snap = venue.snapshot(NOW + timedelta(seconds=6))
    settle = OptionReceipt(
        receipt_id="common-settle",
        sequence=5,
        kind="FUNDS_SETTLED",
        occurred_at=NOW + timedelta(seconds=7),
        cash_change=snap.cash - snap.settled_cash,
    )
    venue.record_receipt(settle)
    next_entry = buy(
        at=NOW + timedelta(seconds=8), client_id="next-stock", source_key="next-stock-source"
    )
    accept(venue, next_entry)
    f6 = venue.fill_stock(next_entry, "2", q(next_entry), NOW + timedelta(seconds=9), fill_id="s3")
    events = (
        StockTrade(intent=entry, attempted_at=NOW, fill=f1),
        StockTrade(intent=close, attempted_at=close.prepared_at, fill=f2),
        OptionTrade(intent=option, attempted_at=NOW + timedelta(seconds=3), fill=f3),
        OptionTrade(intent=option_close, attempted_at=option_close.prepared_at, fill=f4),
        Settlement(receipt=settle),
        StockTrade(intent=next_entry, attempted_at=next_entry.prepared_at, fill=f6),
    )
    projection = reconstruct(
        history(events, venue_id=venue.venue_id, captured_at=NOW + timedelta(seconds=9))
    )
    final = venue.snapshot(NOW + timedelta(seconds=9))
    assert (
        projection.ledger.cash == final.cash
        and projection.ledger.settled_cash == final.settled_cash
    )
    assert projection.ledger.stock_position == final.stock_position
    assert [f.sequence for f in (f1, f2, f3, f4, f6)] == [1, 2, 3, 4, 6]


@pytest.mark.parametrize("winner", ["stock", "option"])
def test_one_working_order_lock_and_one_position_across_instruments(tmp_path, winner):
    option, data = original_option(tmp_path)
    venue = venue_at(tmp_path)
    stock = buy(at=NOW)

    def submit(kind):
        if kind == "stock":
            return accept(venue, stock)
        return asyncio.run(run_option_process(venue, now=NOW, timeout_seconds=3, intent=option))

    loser = "option" if winner == "stock" else "stock"
    submit(winner)
    with pytest.raises(FixtureProcessFailed):
        submit(loser)
    if winner == "stock":
        venue.fill_stock(stock, "2", q(stock), NOW + timedelta(seconds=1), fill_id="held")
    else:
        venue.fill(option, option.quantity, data["quote"], NOW, fill_id="held")
    with pytest.raises(FixtureProcessFailed):
        submit(loser)
    assert venue.submit_count == 1


def test_simultaneous_stock_option_children_cannot_acquire_two_locks(tmp_path):
    option, _ = original_option(tmp_path)
    venue = venue_at(tmp_path)

    async def compete():
        return await asyncio.gather(
            run_option_process(venue, now=NOW, timeout_seconds=3, intent=option),
            run_option_process(venue, now=NOW, timeout_seconds=3, stock_intent=buy(at=NOW)),
            return_exceptions=True,
        )

    results = asyncio.run(compete())
    assert sum(isinstance(r, FixtureProcessFailed) for r in results) == 1
    assert venue.submit_count == 1
    snap = venue.snapshot(NOW)
    assert len(snap.orders) + len(snap.stock_orders) == 1


@pytest.mark.parametrize(
    "fault,accepted",
    [
        ("LOST_ACK", True),
        ("INVALID_ACK", True),
        ("OVERSIZED_ACK", True),
        ("CRASH_AFTER_ACCEPT", True),
        ("STALL_BEFORE_ACCEPT", False),
        ("STALL_AFTER_ACCEPT", True),
        ("IGNORE_TERM_AFTER_ACCEPT", True),
    ],
)
def test_fixed_stock_child_uncertainty_and_no_duplicate_attempt(tmp_path, fault, accepted):
    venue = venue_at(tmp_path, fault=fault)
    entry = buy(at=NOW)
    with pytest.raises((FixtureProcessFailed, FixtureProcessTimeout, FixtureProcessProtocolError)):
        accept(venue, entry, timeout=5)
    venue = DurableOptionVenue(venue.path)
    snap = venue.snapshot(NOW)
    assert len(snap.stock_orders) == int(accepted)
    assert venue.submit_count == int(accepted)
    if accepted:
        with pytest.raises(FixtureProcessFailed):
            accept(venue, entry)
        assert venue.submit_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "b" * 64),
        ("source_at", NOW - timedelta(seconds=19)),
        ("source_valid_until", NOW + timedelta(seconds=9)),
        ("original_invalidation", "91"),
        ("original_target", "121"),
        ("exit_at", NOW + timedelta(minutes=11)),
        ("family", "DEGEN"),
        ("approval_hash", "c" * 64),
        ("account_revision", 1),
        ("thesis", "Rewritten thesis"),
        ("approval_expires_at", NOW + timedelta(seconds=9)),
        ("order_expires_at", NOW + timedelta(minutes=4)),
        ("approved_entry_debit", "201"),
        ("reserved_exit_fee", ".3"),
    ],
)
def test_fill_cannot_replace_any_accepted_stock_terms(tmp_path, field, value):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    venue._accept_stock(entry, entry.prepared_at, None, None)
    before = state_bytes(venue)
    with pytest.raises(ValueError):
        venue.fill_stock(
            changed(entry, **{field: value}),
            "1",
            q(entry),
            NOW + timedelta(seconds=1),
            fill_id="invalid",
        )
    assert state_bytes(venue) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False},
        {"entitlement": "DELAYED"},
        {"source": "other"},
        {"source_at": NOW},
        {"source_at": NOW - timedelta(seconds=40)},
        {"received_at": NOW + timedelta(seconds=2)},
        {"ask_size": None},
        {"ask_size": "1"},
        {"ask": "100.01"},
        {"bid": "4"},
    ],
)
def test_stock_fill_requires_later_fresh_executable_sized_evidence(tmp_path, changes):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    venue._accept_stock(entry, entry.prepared_at, None, None)
    before = state_bytes(venue)
    with pytest.raises(ValueError):
        venue.fill_stock(
            entry, "2", q(entry, **changes), NOW + timedelta(seconds=1), fill_id="invalid"
        )
    assert state_bytes(venue) == before


@pytest.mark.parametrize("quantity", ["0", "-1", ".5", "3", True, 1.0, ".000000001"])
def test_fill_quantity_cannot_bypass_exact_frozen_shares(tmp_path, quantity):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    venue._accept_stock(entry, entry.prepared_at, None, None)
    before = state_bytes(venue)
    with pytest.raises(ValueError):
        venue.fill_stock(entry, quantity, q(entry), NOW + timedelta(seconds=1), fill_id="invalid")
    assert state_bytes(venue) == before


def test_source_liquidity_not_renewed_by_receipt_clock_or_decimal_format(tmp_path):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    quote = q(entry, ask_size="1")
    venue.fill_stock(entry, "1", quote, NOW + timedelta(seconds=1), fill_id="first")
    for changed_quote in (
        changed(quote, received_at=NOW + timedelta(seconds=2)),
        changed(quote, instrument=changed(quote.instrument, tick=".010")),
        changed(quote, ask_size="2"),
    ):
        before = state_bytes(venue)
        with pytest.raises(ValueError):
            venue.fill_stock(
                entry, "1", changed_quote, NOW + timedelta(seconds=2), fill_id="reused"
            )
        assert state_bytes(venue) == before


@pytest.mark.parametrize("status", ["CANCELED", "REJECTED", "EXPIRED"])
def test_explicit_unfilled_terminal_history_remains_and_cannot_replay(tmp_path, status):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    venue.record_stock_terminal(entry.client_id, status, NOW + timedelta(seconds=1))
    with pytest.raises(FixtureProcessFailed):
        accept(venue, entry, at=NOW + timedelta(seconds=1))
    assert venue.snapshot(NOW + timedelta(seconds=1)).stock_orders[0].status == status
    with pytest.raises(ValueError):
        venue.fill_stock(entry, "1", q(entry), NOW + timedelta(seconds=1), fill_id="after-terminal")


def test_partial_cancel_preserves_owned_lots_and_allows_only_original_close(tmp_path):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    venue.fill_stock(entry, "1", q(entry), NOW + timedelta(seconds=1), fill_id="partial")
    with pytest.raises(ValueError):
        venue.record_stock_terminal(entry.client_id, "REJECTED", NOW + timedelta(seconds=1))
    venue.record_stock_terminal(entry.client_id, "CANCELED", NOW + timedelta(seconds=2))
    with pytest.raises(FixtureProcessFailed):
        accept(venue, buy(at=NOW + timedelta(seconds=2), client_id="average", source_key="average"))
    close = sell(entry, at=NOW + timedelta(seconds=3), quantity="1")
    for altered in (
        changed(close, original_invalidation="91"),
        changed(close, thesis="Changed"),
        changed(close, quantity="2"),
    ):
        with pytest.raises(FixtureProcessFailed):
            accept(venue, altered)
    accept(venue, close)
    venue.fill_stock(close, "1", q(close), NOW + timedelta(seconds=4), fill_id="close")
    assert venue.snapshot(NOW + timedelta(seconds=4)).stock_position is None


def test_low_price_owned_exit_and_fractional_fees_are_exact_under_low_precision(tmp_path):
    limits = changed(policy().stocks, share_step=".25")
    venue = venue_at(tmp_path, limits=limits)
    entry = buy(at=NOW, quantity=".5", approved_entry_debit="50.105", reserved_exit_fee=".205")
    with localcontext() as context:
        context.prec = 5
        accept(venue, entry)
        f = venue.fill_stock(entry, ".25", q(entry), NOW + timedelta(seconds=1), fill_id="first")
        assert f.fee == D(".1025")
        venue.record_stock_terminal(entry.client_id, "CANCELED", NOW + timedelta(seconds=1))
        close = changed(sell(entry, at=NOW + timedelta(seconds=2), quantity=".25"), limit_price="1")
        accept(venue, close)
        f = venue.fill_stock(
            close, ".25", q(close, bid="1", ask="1.01"), NOW + timedelta(seconds=3), fill_id="loss"
        )
        assert f.price == 1 and f.fee == D(".1025")
    snap = venue.snapshot(NOW + timedelta(seconds=3))
    assert snap.cash == D("975.045") and snap.settled_cash == D("974.8975")


def test_legacy_engine_rejects_mixed_venue_and_enrolled_snapshot_even_when_flat(tmp_path):
    venue = venue_at(tmp_path)
    _, limits, p = configuration()
    with (
        pytest.raises(ValueError, match="separately bound"),
        OptionExecution.open(tmp_path / "engine.db", limits, p, venue, now=NOW, create=True),
    ):
        pass
    assert not (tmp_path / "engine.db").exists()
    with owned(tmp_path / "legacy") as (engine, legacy, _):
        snap = changed(legacy.snapshot(NOW), stock_limits=venue.stock_limits)
        result = engine.reconcile(snap, now=NOW)
        assert not result["reconciled"]
        assert "MIXED_STOCK_SNAPSHOT_NOT_ENROLLED" in str(result)


def test_legacy_fixture_serialization_omits_new_fields_and_rejects_unenrolled_stock(tmp_path):
    _, limits, p = configuration()
    venue = DurableOptionVenue(tmp_path / "legacy.db", limits=limits, capital=p.capital)
    assert not any(k.startswith("stock_") for k in venue.snapshot(NOW).model_dump())
    assert "stock_position" not in OptionLedger(cash="1000", high_watermark="1000").model_dump()
    request = OptionRequest(
        operation="snapshot",
        path=str(venue.path),
        venue_id=venue.venue_id,
        account_id=venue.account_id,
        population_id=venue.population_id,
        now=NOW,
        deadline_monotonic=time.monotonic() + 3,
        parent_pid=os.getpid(),
    )
    assert "stock_limits" not in request.model_dump() and "stock_intent" not in request.model_dump()
    with pytest.raises(ValueError):
        accept(venue, buy(at=NOW))
    assert venue.submit_count == 0


@pytest.mark.parametrize("operation", ["accept", "snapshot", "stock_accept"])
def test_worker_rejects_mismatched_intent_operation(operation, tmp_path):
    venue = venue_at(tmp_path)
    values = {
        "operation": operation,
        "path": str(venue.path),
        "venue_id": venue.venue_id,
        "account_id": venue.account_id,
        "population_id": venue.population_id,
        "now": NOW,
        "deadline_monotonic": time.monotonic() + 3,
        "parent_pid": os.getpid(),
        "stock_limits": venue.stock_limits,
    }
    if operation != "stock_accept":
        values["stock_intent"] = buy(at=NOW)
    with pytest.raises(ValueError):
        OptionRequest(**values)


def test_enrollment_cannot_be_grafted_onto_legacy_fixture(tmp_path):
    _, limits, p = configuration()
    venue = DurableOptionVenue(tmp_path / "legacy.db", limits=limits, capital=p.capital)
    corrupt(venue, meta=lambda m: m.update(stock_limits=policy().stocks.model_dump(mode="json")))
    with pytest.raises(ValueError, match="schema"):
        DurableOptionVenue(venue.path)


def test_frozen_stock_limits_change_invalidates_existing_handle(tmp_path):
    venue = venue_at(tmp_path)
    corrupt(venue, meta=lambda m: m["stock_limits"].update(max_shares="9"))
    with pytest.raises(ValueError):
        venue.snapshot(NOW)
    with pytest.raises(ValueError):
        venue._accept_stock(buy(at=NOW), NOW, None, None)


@pytest.mark.parametrize("mutation", ["sequence", "duplicate", "submit_count", "unowned_position"])
def test_stored_mixed_state_cannot_silently_drop_or_duplicate_history(tmp_path, mutation):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    venue.fill_stock(entry, "2", q(entry), NOW + timedelta(seconds=1), fill_id="first")

    def alter(s):
        if mutation == "sequence":
            s["sequence"] = 2
        elif mutation == "duplicate":
            s["stock_orders"].append(s["stock_orders"][0])
        elif mutation == "submit_count":
            s["submit_count"] = 0
        else:
            s["stock_orders"] = []

    corrupt(venue, state=alter)
    with pytest.raises(ValueError):
        DurableOptionVenue(venue.path)


def test_all_mixed_operations_reject_time_regression(tmp_path):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    venue.fill_stock(entry, "1", q(entry), NOW + timedelta(seconds=1), fill_id="first")
    for operation in (
        lambda: venue.snapshot(NOW),
        lambda: venue.record_stock_terminal(entry.client_id, "CANCELED", NOW),
        lambda: venue.fill_stock(entry, "1", q(entry), NOW, fill_id="second"),
    ):
        with pytest.raises(ValueError):
            operation()
    assert venue.submit_count == 1


def test_stock_observation_requires_full_original_intent_and_fill_identity(tmp_path):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    accept(venue, entry)
    venue.fill_stock(entry, "1", q(entry), NOW + timedelta(seconds=1), fill_id="first")
    observation = venue.snapshot(NOW + timedelta(seconds=1)).stock_orders[0]
    for fields in (
        {"filled_quantity": "0"},
        {"status": "FILLED"},
        {"client_id": "other"},
        {"updated_at": NOW},
        {"fills": (*observation.fills, *observation.fills)},
        {"intent": changed(entry, quantity="3")},
    ):
        with pytest.raises(ValueError):
            StockObservation.model_validate({**observation.model_dump(), **fields})
    with pytest.raises(ValueError):
        OptionVenueSnapshot.model_validate(
            {**venue.snapshot(NOW + timedelta(seconds=1)).model_dump(), "stock_limits": None}
        )


@pytest.mark.parametrize("at", [NOW - timedelta(microseconds=1), NOW + timedelta(seconds=10)])
def test_original_stock_approval_window_cannot_be_renewed(tmp_path, at):
    venue = venue_at(tmp_path)
    with pytest.raises(ValueError):
        venue._accept_stock(buy(at=NOW), at, None, None)
    assert venue.submit_count == 0


def test_expired_worker_lease_never_commits_stock_acceptance(tmp_path):
    venue = venue_at(tmp_path)
    with pytest.raises(TimeoutError):
        venue._accept_stock(buy(at=NOW), NOW, time.monotonic() - 1, None)
    assert venue.submit_count == 0


def test_close_requires_terminal_entry_and_settlement_requires_terminal_close(tmp_path):
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    venue._accept_stock(entry, NOW, None, None)
    venue.fill_stock(entry, "1", q(entry), NOW + timedelta(seconds=1), fill_id="first")
    close = sell(entry, at=NOW + timedelta(seconds=2), quantity="1")
    with pytest.raises(ValueError):
        venue._accept_stock(close, close.prepared_at, None, None)
    venue.record_stock_terminal(entry.client_id, "CANCELED", close.prepared_at)
    venue._accept_stock(close, close.prepared_at, None, None)
    receipt = OptionReceipt(
        receipt_id="early",
        sequence=2,
        kind="FUNDS_SETTLED",
        occurred_at=close.prepared_at,
        cash_change="1",
    )
    with pytest.raises(ValueError, match="terminal"):
        venue.record_receipt(receipt)
    assert venue.snapshot(close.prepared_at).stock_position.quantity == 1


def test_shared_fill_identity_cannot_be_reused_by_later_option(tmp_path):
    option, data = original_option(tmp_path)
    venue = venue_at(tmp_path)
    entry = buy(at=NOW)
    venue._accept_stock(entry, NOW, None, None)
    venue.fill_stock(entry, "2", q(entry), NOW + timedelta(seconds=1), fill_id="same")
    close = sell(entry, at=NOW + timedelta(seconds=2))
    venue._accept_stock(close, close.prepared_at, None, None)
    venue.fill_stock(close, "2", q(close), NOW + timedelta(seconds=3), fill_id="close")
    venue._accept(option, NOW + timedelta(seconds=3), None, None)
    before = state_bytes(venue)
    with pytest.raises(ValueError, match="Duplicate"):
        venue.fill(
            option,
            option.quantity,
            quote_at(data, NOW + timedelta(seconds=4)),
            NOW + timedelta(seconds=4),
            fill_id="same",
        )
    assert state_bytes(venue) == before


def test_worker_rejects_stale_parent_enrollment_without_attempt(tmp_path):
    venue = venue_at(tmp_path)
    corrupt(venue, meta=lambda m: m["stock_limits"].update(max_shares="9"))
    with pytest.raises(FixtureProcessFailed):
        accept(venue, buy(at=NOW))
    assert DurableOptionVenue(venue.path).submit_count == 0


def test_four_fixture_accounts_keep_cash_and_attempts_independent(tmp_path):
    p = policy()
    venues = []
    for arm in "ABCD":
        limits = changed(p.options, account_id="account-" + arm, population_id="population-" + arm)
        v = DurableOptionVenue(
            tmp_path / (arm + ".db"), limits=limits, stock_limits=p.stocks, capital=p.capital
        )
        venues.append(v)
    entry = buy(at=NOW)
    venues[0]._accept_stock(entry, NOW, None, None)
    venues[0].fill_stock(entry, "2", q(entry), NOW + timedelta(seconds=1), fill_id="entry")
    snaps = [v.snapshot(NOW + timedelta(seconds=1)) for v in venues]
    assert len({s.venue_id for s in snaps}) == len({s.account_id for s in snaps}) == 4
    assert [s.cash for s in snaps] == [D("799.88"), D("1000"), D("1000"), D("1000")]
    assert [v.submit_count for v in venues] == [1, 0, 0, 0]
