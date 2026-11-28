"""One-bankroll immutable accounting, not mixed native execution acceptance."""

import asyncio
import hashlib
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_execution import NOW, configuration, enter, intent_for, owned

from app.mixed.accounting import reconstruct, verify_extension
from app.mixed.models import (
    CashHistory,
    CostRecord,
    CostResolution,
    MixedPolicy,
    OptionTrade,
    Reservation,
    Settlement,
    StockFill,
    StockInstrument,
    StockIntent,
    StockLimits,
    StockQuote,
    StockTrade,
    TerminalOrder,
)
from app.options.lifecycle import OptionLedger, OptionReceipt
from app.options.models import OptionProposal

D = Decimal
H = "a" * 64
OPEN = NOW - timedelta(seconds=60)


def changed(value, **fields):
    return type(value).model_validate({**value.model_dump(), **fields})


def policy():
    _, limits, native = configuration()
    stocks = StockLimits(
        provider=limits.provider,
        quote_source="stock-tape",
        allowed_symbols=("SPY", "QQQ"),
        share_step="1",
        max_shares="10",
        max_entry_debit="900",
        max_account_exposure="950",
        minimum_price="5",
        max_spread_fraction=".1",
        slippage_bps="0",
        entry_fee_per_share=".01",
        exit_fee_per_share=".01",
        entry_fee_per_order=".1",
        exit_fee_per_order=".1",
        quote_max_age_seconds=30,
        max_receive_lag_seconds=5,
        approval_lifetime_seconds=10,
    )
    return MixedPolicy(
        capital=native.capital,
        daily_loss_limit=native.daily_loss_limit,
        total_loss_limit=native.total_loss_limit,
        options=limits,
        stocks=stocks,
    )


def instrument():
    return StockInstrument(
        provider=policy().stocks.provider,
        instrument_id="stock-spy",
        symbol="SPY",
        kind="ETF",
        tick=".01",
        metadata_complete=True,
        tradable=True,
    )


def buy(at=NOW - timedelta(seconds=40), **changes):
    values = {
        "client_id": "stock-buy",
        "source_key": "stock-source",
        "instrument": instrument(),
        "side": "BUY",
        "quantity": "2",
        "limit_price": "100",
        "approved_entry_debit": "200.12",
        "reserved_exit_fee": ".22",
        "prepared_at": at,
        "approval_expires_at": at + timedelta(seconds=10),
        "order_expires_at": at + timedelta(minutes=5),
        "exit_at": at + timedelta(minutes=10),
        "original_invalidation": "90",
        "original_target": "120",
        "family": "SWING",
        "source_hash": H,
        "source_at": at - timedelta(seconds=20),
        "source_valid_until": at + timedelta(seconds=10),
        "approval_hash": H,
        "account_revision": 0,
        "thesis": "Original share thesis",
    }
    values.update(changes)
    return StockIntent(**values)


def sell(entry, at=NOW - timedelta(seconds=30), **changes):
    return changed(
        entry,
        client_id="stock-sell",
        source_key="stock-close",
        side="SELL",
        limit_price="101",
        approved_entry_debit="0",
        reserved_exit_fee="0",
        prepared_at=at,
        approval_expires_at=at + timedelta(seconds=10),
        order_expires_at=at + timedelta(minutes=5),
        closing_entry_client_id=entry.client_id,
        **changes,
    )


def trade(intent, sequence, *, quantity=None, price=None, fee=None, at=None, q=None, fill_id=None):
    at = at or intent.prepared_at + timedelta(seconds=1)
    quantity = D(quantity) if quantity is not None else intent.quantity
    price = D(price or ("100" if intent.side == "BUY" else "102"))
    q = q or StockQuote(
        source="stock-tape",
        source_at=at,
        received_at=at,
        entitlement="REALTIME",
        complete=True,
        instrument=intent.instrument,
        bid=price if intent.side == "SELL" else price - D(".01"),
        ask=price if intent.side == "BUY" else price + D(".01"),
        bid_size="10",
        ask_size="10",
    )
    f = StockFill(
        fill_id=fill_id or f"stock-fill-{sequence}",
        order_id="order-" + intent.client_id,
        sequence=sequence,
        quantity=quantity,
        price=price,
        fee=D(fee) if fee is not None else quantity * D(".01") + D(".1"),
        occurred_at=at,
        quote_hash=hashlib.sha256(q.model_dump_json().encode()).hexdigest(),
        quote=q,
    )
    return StockTrade(intent=intent, attempted_at=intent.prepared_at, fill=f)


def allocation(at=OPEN):
    return tuple(
        CostRecord(
            cost_id=kind.lower() + at.date().isoformat(),
            kind=kind,
            occurred_at=at,
            amount="0",
            evidence_hash=H,
        )
        for kind in ("DATA", "HOST", "OPERATING")
    )


def history(events=(), **changes):
    p = policy()
    values = {
        "account_id": p.options.account_id,
        "population_id": p.options.population_id,
        "venue_id": "one-local-venue",
        "policy": p,
        "opened_at": OPEN,
        "captured_at": NOW,
        "events": events,
        "costs": allocation(),
    }
    values.update(changes)
    return CashHistory(**values)


@pytest.fixture(scope="module")
def option_trades(tmp_path_factory):
    with owned(tmp_path_factory.mktemp("native-original")) as (engine, venue, data):
        entry = enter(engine, venue, data)
        engine.assess(data["quote"], data["underlying"], now=NOW)
        result = engine.prepare(
            "native-close",
            OptionProposal(
                action="CLOSE",
                contract=entry.instrument.contract,
                thesis="Original native option close",
            ),
            data["quote"],
            now=NOW,
        )
        close = intent_for(engine, result["client_id"])
        assert asyncio.run(engine.dispatch(close.client_id, data["quote"], now=NOW)) == "OPEN"
        venue.fill(close, close.quantity, data["quote"], NOW, fill_id="native-exit")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        snap = venue.snapshot(NOW)
        events = tuple(
            OptionTrade(intent=i, attempted_at=NOW, fill=o.fills[0])
            for i, o in zip((entry, close), snap.orders, strict=True)
        )
        original = OptionLedger.model_validate(engine.journal.report(now=NOW)["ledger"])
    return events, original


def settlement(sequence, amount, at):
    return Settlement(
        receipt=OptionReceipt(
            receipt_id=f"settle-{sequence}",
            sequence=sequence,
            kind="FUNDS_SETTLED",
            occurred_at=at,
            cash_change=amount,
        )
    )


def stock_roundtrip():
    b = buy()
    return (trade(b, 1), trade(sell(b), 2))


def test_native_options_reconstruct_exactly_without_changing_legacy_ledger(option_trades):
    events, original = option_trades
    result = reconstruct(history(events))
    fields = {k: v for k, v in result.ledger.model_dump().items() if k in OptionLedger.model_fields}
    assert OptionLedger.model_validate(fields) == original
    assert result.net_realized_pnl == D("-23.20")
    assert "stock_position" not in original.model_dump()
    with pytest.raises(ValidationError):
        OptionLedger.model_validate(result.ledger.model_dump())


def test_stock_then_options_then_stock_uses_one_original_bankroll(option_trades):
    options, original = option_trades
    events = (*stock_roundtrip(), settlement(3, "203.88", NOW - timedelta(seconds=20)))
    events += tuple(changed(e, fill=changed(e.fill, sequence=e.fill.sequence + 3)) for e in options)
    events += (settlement(6, original.cash - original.settled_cash, NOW),)
    later = buy(NOW + timedelta(seconds=1), client_id="stock-again", source_key="stock-again")
    events += (trade(later, 7),)
    result = reconstruct(history(events, captured_at=NOW + timedelta(seconds=3)))
    assert result.ledger.cash == D("780.44")
    assert result.ledger.settled_cash == result.ledger.cash
    assert result.ledger.realized_pnl == D("-12")
    assert result.ledger.fees_paid == D("7.56")
    assert result.net_realized_pnl == D("-19.56")
    assert result.ledger.stock_position.entry == later
    assert result.ledger.position is None
    assert result.reserved_cash == D(".22")
    assert result.entry_blockers == ("MIXED_POSITION_OWNED",)


def test_stock_sale_credits_remain_unsettled_and_partial_lots_exact():
    b = buy()
    e1 = trade(b, 1, quantity="1", fee=".11")
    e2 = trade(b, 2, quantity="1", fee=".01", at=e1.fill.occurred_at + timedelta(seconds=1))
    close = sell(b, quantity="1")
    e3 = trade(close, 3, quantity="1")
    r = reconstruct(history((e1, e2, e3)))
    assert r.ledger.cash == D("901.77")
    assert r.ledger.settled_cash == D("799.88")
    assert r.ledger.stock_position.quantity == 1
    assert r.ledger.stock_position.basis == 100
    assert r.ledger.stock_position.entry == b
    assert r.ledger.realized_pnl == 2
    assert r.ledger.fees_paid == D(".23")


@pytest.mark.parametrize("direction", ["stock-option", "option-stock"])
def test_position_is_exclusive_across_instrument_types(option_trades, direction):
    options, _ = option_trades
    if direction == "stock-option":
        events = (trade(buy(), 1), changed(options[0], fill=changed(options[0].fill, sequence=2)))
    else:
        b = buy(NOW, client_id="later-stock")
        events = (options[0], trade(b, 2))
    with pytest.raises(ValueError, match="MIXED_EXISTING"):
        reconstruct(history(events, captured_at=NOW + timedelta(seconds=2)))


@pytest.mark.parametrize(
    "defect",
    [
        "gap",
        "duplicate-sequence",
        "time-regression",
        "future",
        "duplicate-id",
        "overfill",
        "order-id",
        "attempt",
        "intent",
    ],
)
def test_history_rejects_cross_instrument_sequence_or_original_defects(defect):
    a, b = stock_roundtrip()
    if defect == "gap":
        b = changed(b, fill=changed(b.fill, sequence=3))
    if defect == "duplicate-sequence":
        b = changed(b, fill=changed(b.fill, sequence=1))
    if defect == "time-regression":
        b = changed(b, fill=changed(b.fill, occurred_at=OPEN))
    if defect == "future":
        b = changed(b, fill=changed(b.fill, occurred_at=NOW + timedelta(seconds=1)))
    if defect == "duplicate-id":
        b = changed(b, fill=changed(b.fill, fill_id=a.fill.fill_id))
    if defect == "overfill":
        b = trade(a.intent, 2, at=a.fill.occurred_at + timedelta(seconds=1), fee=".02")
    if defect in {"order-id", "attempt", "intent"}:
        a = trade(a.intent, 1, quantity="1", fee=".11")
        b = trade(
            a.intent, 2, quantity="1", fee=".01", at=a.fill.occurred_at + timedelta(seconds=1)
        )
        if defect == "order-id":
            b = changed(b, fill=changed(b.fill, order_id="foreign"))
        if defect == "attempt":
            b = changed(b, attempted_at=b.attempted_at + timedelta(microseconds=1))
        if defect == "intent":
            b = changed(b, intent=changed(b.intent, thesis="Replaced original"))
    with pytest.raises(ValueError):
        reconstruct(history((a, b)))


@pytest.mark.parametrize(
    "defect",
    [
        "source",
        "foreign",
        "delayed",
        "incomplete",
        "old",
        "future-source",
        "lag",
        "missing-size",
        "zero-size",
        "hash",
        "fee",
        "price",
        "original-quote",
        "spread",
        "cheap",
    ],
)
def test_stock_fills_require_exact_fresh_sized_execution_evidence(defect):
    e = trade(buy(), 1)
    f = e.fill
    q = f.quote
    changes = {
        "source": {"source": "foreign"},
        "foreign": {"instrument": changed(q.instrument, instrument_id="foreign")},
        "delayed": {"entitlement": "DELAYED"},
        "incomplete": {"complete": False},
        "old": {"source_at": OPEN, "received_at": OPEN},
        "future-source": {
            "source_at": NOW + timedelta(seconds=1),
            "received_at": NOW + timedelta(seconds=1),
        },
        "lag": {"source_at": q.source_at - timedelta(seconds=6)},
        "missing-size": {"ask_size": None},
        "zero-size": {"ask_size": "0"},
        "original-quote": {"source_at": e.intent.prepared_at},
        "spread": {"bid": "80"},
        "cheap": {"bid": "4"},
    }
    if defect in changes:
        q = changed(q, **changes[defect])
        f = changed(f, quote=q, quote_hash=hashlib.sha256(q.model_dump_json().encode()).hexdigest())
    if defect == "hash":
        f = changed(f, quote_hash="b" * 64)
    if defect == "fee":
        f = changed(f, fee="0")
    if defect == "price":
        f = changed(f, price="99")
    with pytest.raises(ValueError):
        reconstruct(history((changed(e, fill=f),)))


def test_changed_receipt_time_cannot_recycle_source_liquidity():
    b = buy()
    a = trade(b, 1, quantity="1", fee=".11")
    q = changed(a.fill.quote, ask_size="1")
    a = trade(b, 1, quantity="1", fee=".11", q=q)
    q2 = changed(q, received_at=q.received_at + timedelta(seconds=1))
    c = trade(b, 2, quantity="1", fee=".01", q=q2, at=q2.received_at)
    with pytest.raises(ValueError, match="SIZE_UNKNOWN_OR_EXCEEDED"):
        reconstruct(history((a, c)))
    q3 = changed(q2, ask_size="2")
    c = trade(b, 2, quantity="1", fee=".01", q=q3, at=q3.received_at)
    with pytest.raises(ValueError, match="SOURCE_QUOTE_CHANGED"):
        reconstruct(history((a, c)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_invalidation", "89"),
        ("original_target", "121"),
        ("source_hash", "b" * 64),
        ("family", "DEGEN"),
        ("closing_entry_client_id", "foreign"),
        ("source_at", NOW - timedelta(seconds=61)),
        ("source_valid_until", NOW - timedelta(seconds=29)),
    ],
)
def test_sale_preserves_original_stock_terms(field, value):
    a, b = stock_roundtrip()
    b = changed(b, intent=changed(b.intent, **{field: value}))
    with pytest.raises(ValueError, match="UNOWNED_STOCK"):
        reconstruct(history((a, b)))


def test_short_sale_second_buy_and_entry_after_partial_exit_are_forbidden():
    a, b = stock_roundtrip()
    with pytest.raises(ValueError, match="UNOWNED_STOCK"):
        reconstruct(history((changed(b, fill=changed(b.fill, sequence=1)),)))
    second = buy(a.intent.prepared_at + timedelta(seconds=2), client_id="new-buy")
    with pytest.raises(ValueError, match="AVERAGING"):
        reconstruct(history((a, trade(second, 2))))
    a = trade(a.intent, 1, quantity="1", fee=".11")
    b = trade(sell(a.intent, at=a.fill.occurred_at + timedelta(seconds=1), quantity="1"), 2)
    c = trade(a.intent, 3, quantity="1", fee=".01", at=b.fill.occurred_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="CANNOT_RESUME"):
        reconstruct(history((a, b, c)))


def test_unsettled_proceeds_cannot_fund_second_trade():
    p = changed(policy(), capital="250", daily_loss_limit="200", total_loss_limit="200")
    a, b = stock_roundtrip()
    new = buy(NOW - timedelta(seconds=20), client_id="new-buy")
    with pytest.raises(ValidationError):
        reconstruct(history((a, b, trade(new, 3)), policy=p))


def test_exact_fractional_share_accounting_is_independent_of_decimal_context():
    p = policy()
    p = changed(
        p,
        stocks=changed(
            p.stocks, share_step=".00000001", entry_fee_per_order="0", exit_fee_per_order="0"
        ),
    )
    b = buy(
        quantity=".12345678", approved_entry_debit="12.3469125678", reserved_exit_fee=".0012345678"
    )
    e = trade(b, 1, quantity=".12345678", fee=".0012345678")
    with localcontext() as ctx:
        ctx.prec = 6
        r = reconstruct(history((e,), policy=p))
    assert r.ledger.cash == D("987.6530874322")
    assert r.ledger.stock_position.basis == D("12.345678")
    assert r.reserved_cash == D(".0012345678")


@pytest.mark.parametrize("quantity", [True, 1.5, "0.000000001", "NaN", "Infinity", "-1", "0"])
def test_invalid_share_quantities_are_rejected(quantity):
    with pytest.raises(ValidationError):
        buy(quantity=quantity)


@pytest.mark.parametrize("field", ["approved_entry_debit", "reserved_exit_fee"])
def test_share_debit_and_exit_fees_cannot_be_underreserved(field):
    b = buy(**{field: ".01"})
    with pytest.raises(ValueError, match="DEBIT_OR_EXIT_RESERVE"):
        reconstruct(history((trade(b, 1),)))


@pytest.mark.parametrize("status", ["PREPARED", "SUBMITTING", "UNKNOWN", "OPEN"])
def test_unfilled_stock_order_reserves_common_cash_even_after_approval_expiry(status):
    b = buy()
    r = reconstruct(history(reservations=(Reservation(intent=b, status=status),)))
    assert r.reserved_cash == D("200.34")
    assert r.available_settled_cash == D("799.66")
    assert r.entry_blockers == ("MIXED_ORDER_UNRESOLVED",)


def test_partial_stock_reservation_subtracts_actual_paid_debit_once():
    b = buy()
    e = trade(b, 1, quantity="1", fee=".11")
    r = reconstruct(history((e,), reservations=(Reservation(intent=b, status="PARTIAL"),)))
    assert r.ledger.cash == D("899.89")
    assert r.reserved_cash == D("100.23")
    assert r.available_settled_cash == D("799.66")


def test_stock_pending_order_cannot_hide_behind_option_holding(option_trades):
    events, _ = option_trades
    with pytest.raises(ValueError, match="CROSS_INSTRUMENT_RESERVATION"):
        reconstruct(
            history(events[:1], reservations=(Reservation(intent=buy(), status="UNKNOWN"),))
        )


def test_explicit_costs_include_rejected_entries_management_and_operating_allocations():
    a, b = stock_roundtrip()
    costs = (
        CostRecord(
            cost_id="rejected", kind="ENTRY_MODEL", occurred_at=OPEN, amount=".3", evidence_hash=H
        ),
        CostRecord(
            cost_id="entry",
            kind="ENTRY_MODEL",
            occurred_at=a.intent.prepared_at - timedelta(seconds=1),
            amount=".2",
            entry_client_id=a.intent.client_id,
            evidence_hash=H,
        ),
        CostRecord(
            cost_id="manage",
            kind="MANAGEMENT_MODEL",
            occurred_at=a.fill.occurred_at,
            amount=".1",
            entry_client_id=a.intent.client_id,
            evidence_hash=H,
        ),
    )
    alloc = tuple(changed(c, amount=".5") for c in allocation())
    r = reconstruct(history((a, b), costs=(*alloc, *costs)))
    assert r.ledger.cash == D("1003.76")
    assert r.known_cost == D("2.1")
    assert r.net_realized_pnl == D("1.66")
    assert r.total_loss_available == D("801.66")
    assert r.daily_loss_available == D("601.66")


def test_unknown_cost_is_not_zero_and_explicit_resolution_preserves_original_charge():
    c = CostRecord(
        cost_id="unknown-call", kind="ENTRY_MODEL", occurred_at=OPEN, amount=None, evidence_hash=H
    )
    first = history(costs=(*allocation(), c))
    r = reconstruct(first)
    assert r.net_realized_pnl is None and r.total_loss_available is None
    assert r.unknown_cost_ids == ("unknown-call",)
    current = changed(
        first,
        cost_resolutions=(
            CostResolution(
                cost_id=c.cost_id, recorded_at=NOW, amount=".45", evidence_hash="b" * 64
            ),
        ),
    )
    resolved = verify_extension(first, current)
    assert resolved.net_realized_pnl == D("-.45")
    assert current.costs[-1].amount is None


@pytest.mark.parametrize("missing", ["DATA", "HOST", "OPERATING"])
def test_missing_operating_allocation_is_unknown(missing):
    r = reconstruct(history(costs=tuple(c for c in allocation() if c.kind != missing)))
    assert any(i.startswith("missing-" + missing) for i in r.unknown_cost_ids)
    assert r.net_realized_pnl is None


def test_overnight_calendar_dates_require_explicit_allocation_including_zero():
    r = reconstruct(history(captured_at=NOW + timedelta(days=1)))
    assert len(r.unknown_cost_ids) == 3
    complete = reconstruct(
        history(
            captured_at=NOW + timedelta(days=1),
            costs=(*allocation(), *allocation(NOW + timedelta(days=1))),
        )
    )
    assert complete.net_realized_pnl == 0


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "future",
        "foreign-entry",
        "management-before-fill",
        "resolution-orphan",
        "resolution-known",
    ],
)
def test_cost_history_tampering_is_rejected(defect):
    a, b = stock_roundtrip()
    costs = allocation()
    resolutions = ()
    if defect == "duplicate":
        costs = (*costs, costs[0])
    if defect == "future":
        costs = (*costs, changed(costs[0], cost_id="new", occurred_at=NOW + timedelta(seconds=1)))
    if defect in {"foreign-entry", "management-before-fill"}:
        costs = (
            *costs,
            CostRecord(
                cost_id="call",
                kind="MANAGEMENT_MODEL",
                occurred_at=OPEN,
                amount=".2",
                entry_client_id="foreign" if defect == "foreign-entry" else a.intent.client_id,
                evidence_hash=H,
            ),
        )
    if defect.startswith("resolution"):
        resolutions = (
            CostResolution(
                cost_id="foreign" if defect.endswith("orphan") else costs[0].cost_id,
                recorded_at=NOW,
                amount="1",
                evidence_hash=H,
            ),
        )
    with pytest.raises(ValueError):
        reconstruct(history((a, b), costs=costs, cost_resolutions=resolutions))


def test_mixed_losses_are_one_envelope_across_all_cost_kinds():
    costs = (
        *allocation(),
        CostRecord(
            cost_id="budget", kind="OPERATING", occurred_at=OPEN, amount="900", evidence_hash=H
        ),
    )
    r = reconstruct(history(costs=costs))
    assert r.daily_loss_available == 0 and r.total_loss_available == 0
    assert "MIXED_LOSS_BUDGET_EXHAUSTED" in r.entry_blockers


def test_serialized_restart_projection_is_exact_with_no_new_capital(option_trades):
    events, _ = option_trades
    h = history(events)
    assert reconstruct(CashHistory.model_validate_json(h.model_dump_json())) == reconstruct(h)
    assert reconstruct(h).ledger.cash == D("976.80")
    assert verify_extension(h, h) == reconstruct(h)


@pytest.mark.parametrize("defect", ["capital", "account", "venue", "events", "costs", "clock"])
def test_extension_cannot_rewrite_original_history(defect):
    old = history(stock_roundtrip())
    if defect == "capital":
        new = changed(old, policy=changed(old.policy, capital="2000"))
    if defect == "account":
        p = changed(old.policy, options=changed(old.policy.options, account_id="other"))
        new = changed(old, account_id="other", policy=p)
    if defect == "venue":
        new = changed(old, venue_id="other")
    if defect == "events":
        new = changed(old, events=())
    if defect == "costs":
        new = changed(old, costs=tuple(changed(c, amount=".1") for c in old.costs))
    if defect == "clock":
        new = changed(old, captured_at=old.captured_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="MIXED_"):
        verify_extension(old, new)


def test_unknown_reservation_needs_explicit_terminal_before_release():
    b = buy()
    old = history(reservations=(Reservation(intent=b, status="UNKNOWN"),))
    new = changed(old, reservations=())
    with pytest.raises(ValueError, match="DISAPPEARED_WITHOUT_TERMINAL"):
        verify_extension(old, new)
    t = TerminalOrder(
        intent=b,
        status="CANCELED",
        observed_at=NOW,
        order_id="canceled-order",
        attempted_at=b.prepared_at,
    )
    new = changed(new, terminals=(t,))
    r = verify_extension(old, new)
    assert r.reserved_cash == 0 and not r.entry_blockers


def test_pending_original_and_state_cannot_regress():
    b = buy()
    old = history(reservations=(Reservation(intent=b, status="UNKNOWN"),))
    for replacement in (
        Reservation(intent=changed(b, thesis="Changed"), status="UNKNOWN"),
        Reservation(intent=b, status="PREPARED"),
    ):
        with pytest.raises(ValueError, match="MIXED_RESERVATION"):
            verify_extension(old, changed(old, reservations=(replacement,)))


def test_independent_research_accounts_share_no_cash_or_costs(option_trades):
    events, _ = option_trades
    outputs = []
    for arm in "ABCD":
        p = policy()
        p = changed(
            p,
            options=changed(
                p.options, account_id="account-" + arm, population_id="population-" + arm
            ),
        )
        costs = (
            *allocation(),
            CostRecord(
                cost_id="same-source-call",
                kind="ENTRY_MODEL",
                occurred_at=OPEN,
                amount=str("ABCD".index(arm)),
                evidence_hash=H,
            ),
        )
        h = history(
            events,
            policy=p,
            account_id=p.options.account_id,
            population_id=p.options.population_id,
            venue_id="venue-" + arm,
            costs=costs,
        )
        outputs.append(reconstruct(h))
    assert [r.ledger.cash for r in outputs] == [D("976.80")] * 4
    assert [r.net_realized_pnl for r in outputs] == [
        D("-23.20"),
        D("-24.20"),
        D("-25.20"),
        D("-26.20"),
    ]


@pytest.mark.parametrize("family", ["SCOPE", "SWING"])
def test_original_native_family_terms_survive_common_projection(tmp_path, family):
    from contextlib import ExitStack

    from test_option_scope_execution import execution_policy, filled
    from test_option_scope_watch import owned as scope_owner
    from test_option_swing_execution import carry_frame, carry_owner, entered

    with ExitStack() as stack:
        if family == "SCOPE":
            e, v, _ = stack.enter_context(
                scope_owner(tmp_path, enroll=False, execution_policy_changes=execution_policy())
            )
            _, entry, _, _, now = filled(e, v)
        else:
            c, v, times = stack.enter_context(carry_owner(tmp_path))
            entry = entered(c, v, carry_frame())
            e, now = c.engine, times[0]
        snap = v.snapshot(now)
        events = tuple(
            OptionTrade(intent=entry, attempted_at=entry.prepared_at, fill=f)
            for f in snap.orders[0].fills
        )
        p = changed(
            policy(),
            capital=e.policy.capital,
            daily_loss_limit=e.policy.daily_loss_limit,
            total_loss_limit=e.policy.total_loss_limit,
            options=e.limits,
            stocks=changed(policy().stocks, provider=e.limits.provider),
        )
        h = history(
            events,
            policy=p,
            account_id=e.limits.account_id,
            population_id=e.limits.population_id,
            opened_at=entry.prepared_at,
            captured_at=now,
            costs=allocation(entry.prepared_at),
        )
        r = reconstruct(h)
        original = OptionLedger.model_validate(e.journal.report(now=now)["ledger"])
        assert r.ledger.position == original.position
        assert r.ledger.cash == original.cash
        assert r.ledger.settled_cash == original.settled_cash
        assert h.events[0].intent == entry
        if family == "SCOPE":
            assert entry.entry_lineage.family == "SCOPE"
            assert r.ledger.position.entry_time_protection == entry.entry_time_protection
            assert r.ledger.position.target_exit_schedule == entry.target_exit_schedule
        else:
            assert r.ledger.position.swing_carry == entry.swing_carry
            assert entry.swing_carry is not None


def test_source_size_cannot_be_reused_by_decimal_scale_alias():
    b = buy()
    a = trade(b, 1, quantity="1", fee=".11")
    q = changed(a.fill.quote, ask_size="1")
    a = trade(b, 1, quantity="1", fee=".11", q=q)
    instrument_alias = changed(b.instrument, tick=".010")
    b_alias = changed(b, instrument=instrument_alias)
    q2 = changed(q, instrument=instrument_alias, received_at=q.received_at + timedelta(seconds=1))
    c = trade(b_alias, 2, quantity="1", fee=".01", q=q2, at=q2.received_at)
    with pytest.raises(ValueError, match="SIZE_UNKNOWN_OR_EXCEEDED"):
        reconstruct(history((a, c)))


def test_pending_sale_cannot_reserve_unowned_remainder():
    a = trade(buy(), 1)
    close = sell(a.intent, quantity="3")
    with pytest.raises(ValueError, match="RESERVATION_OVERSELL"):
        reconstruct(history((a,), reservations=(Reservation(intent=close, status="UNKNOWN"),)))


@pytest.mark.parametrize(
    "receipt_kind", ["PHYSICAL_EXERCISE", "CASH_SETTLEMENT", "EXPIRED_WORTHLESS"]
)
def test_option_settlement_cannot_close_or_transform_a_stock_holding(receipt_kind, option_trades):
    entry = option_trades[0][0].intent
    receipt = OptionReceipt(
        receipt_id="foreign-settlement",
        sequence=2,
        kind=receipt_kind,
        occurred_at=NOW,
        contract=entry.instrument.contract,
        quantity=1,
        settlement_value="0",
        cash_change="0",
    )
    with pytest.raises(ValueError):
        reconstruct(history((trade(buy(), 1), Settlement(receipt=receipt))))


def test_explicit_settlement_cannot_create_money_or_replay():
    events = stock_roundtrip()
    for amount in ("204", "0", "-1"):
        with pytest.raises(ValueError):
            reconstruct(history((*events, settlement(3, amount, NOW))))
    good = settlement(3, "203.88", NOW)
    again = changed(good, receipt=changed(good.receipt, sequence=4))
    with pytest.raises(ValueError, match="DUPLICATE"):
        reconstruct(history((*events, good, again)))
