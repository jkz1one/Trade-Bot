"""Two-play cash replay uses one balance and explicit original entry keys."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_mixed_accounting import (
    NOW,
    allocation,
    buy,
    changed,
    history,
    policy,
    sell,
    trade,
)
from test_mixed_accounting import option_trades as option_trades  # noqa: PLC0414

from app.mixed.accounting import reconstruct, verify_extension
from app.mixed.models import Reservation, Settlement, TerminalOrder
from app.mixed.portfolio_accounting import (
    PortfolioHistory,
    PortfolioLedger,
    PortfolioPolicy,
    capacity,
)
from app.mixed.portfolio_capacity import entry_blockers
from app.options.lifecycle import EntryLineage, OptionReceipt


def portfolio(events=(), **changes):
    original = history(events)
    values = original.model_dump()
    values.update(
        version="mixed-cash-history-v2",
        policy=PortfolioPolicy(
            **{
                **policy().model_dump(),
                "version": "mixed-cash-history-v2",
                "options": changed(policy().options, allowed_underlyings=("SPY", "QQQ")),
            },
            exposure_limit=policy().options.max_account_exposure,
            index_exposure_limit=policy().options.max_account_exposure,
        ),
    )
    values.update(changes)
    return PortfolioHistory.model_validate(values)


def two_stocks():
    a = buy()
    b = changed(
        buy(),
        client_id="qqq-buy",
        source_key="qqq-source",
        instrument=changed(a.instrument, symbol="QQQ", instrument_id="stock-qqq"),
        thesis="Independent QQQ thesis",
    )
    return a, b


def labeled(event):
    intent = changed(
        event.intent,
        entry_lineage=EntryLineage(
            family="DEGEN",
            setup="test",
            opportunity_key=event.intent.source_key,
            candidate_id="original",
            candidate_hash="a" * 64,
        ),
    )
    return changed(event, intent=intent)


def test_two_stock_positions_one_balance_and_independent_partial_exit():
    a, b = two_stocks()
    close = sell(a, quantity="1")
    h = portfolio((trade(a, 1), trade(b, 2), trade(close, 3)))
    r = reconstruct(h)
    assert set(r.ledger.positions) == {a.client_id, b.client_id}
    assert r.ledger.positions[a.client_id].quantity == 1
    assert r.ledger.positions[b.client_id].quantity == 2
    assert r.ledger.positions[b.client_id].entry.thesis == b.thesis
    assert r.ledger.cash == D("701.65")
    assert r.ledger.settled_cash == D("599.76")
    assert r.ledger.realized_pnl == 2
    assert r.ledger.fees_paid == D(".35")
    assert r.reserved_cash == D(".33")
    assert r.ledger.high_watermark == 1000
    assert r.entry_blockers == ("PLAY_CAPACITY",)
    assert r.ledger.position is r.ledger.stock_position is None


def test_close_one_and_simultaneous_exits_keep_exact_lineage():
    a, b = two_stocks()
    h = portfolio(
        (trade(a, 1), trade(b, 2), trade(sell(a), 3)),
        captured_at=sell(a).prepared_at + timedelta(seconds=1),
    )
    r = reconstruct(h)
    assert set(r.ledger.positions) == {b.client_id}
    other = changed(sell(b), client_id="qqq-sell", source_key="qqq-close")
    updated = changed(h, events=(*h.events, trade(other, 4)))
    result = verify_extension(h, updated)
    assert result.ledger.positions == {}
    assert result.ledger.cash == D("1007.52")
    assert result.ledger.settled_cash == D("599.76")
    assert result.ledger.high_watermark == D("1007.52")
    assert result.entry_blockers == ()
    assert reconstruct(PortfolioHistory.model_validate_json(updated.model_dump_json())) == result


def test_two_unfilled_reservations_use_shared_funds_and_capacity():
    a, b = two_stocks()
    h = portfolio(
        reservations=(
            Reservation(intent=a, status="OPEN"),
            Reservation(intent=b, status="PREPARED"),
        )
    )
    r = reconstruct(h)
    assert r.reserved_cash == D("400.68")
    assert r.available_settled_cash == D("599.32")
    account = capacity(h, r, revision=3, reconciled=True, halted=False)
    candidate = changed(
        r.commitments[0],
        play_id="third",
        entry_client_id="third",
        underlying="IWM",
        instrument_id="iwm",
    )
    assert "PLAY_CAPACITY" in entry_blockers(account, candidate)
    assert len(account.plays) == 2


def test_partial_entry_cancel_releases_only_unfilled_debit():
    a, b = two_stocks()
    h = portfolio(
        (trade(a, 1, quantity="1", fee=".11"),),
        reservations=(
            Reservation(intent=a, status="PARTIAL"),
            Reservation(intent=b, status="OPEN"),
        ),
    )
    r = reconstruct(h)
    assert r.reserved_cash == D("300.57")
    assert r.ledger.positions[a.client_id].basis == 100
    after = changed(
        h,
        reservations=h.reservations[1:],
        terminals=(
            TerminalOrder(
                intent=a,
                status="CANCELED",
                observed_at=NOW,
                order_id="order-" + a.client_id,
                attempted_at=a.prepared_at,
            ),
        ),
    )
    result = verify_extension(h, after)
    assert result.reserved_cash == D("200.45")
    assert len(result.commitments) == 2
    assert result.ledger == r.ledger
    with pytest.raises(ValueError, match="WITHOUT_TERMINAL"):
        verify_extension(h, changed(h, reservations=h.reservations[1:]))


def test_pending_exit_and_uncertainty_keep_both_plays_committed():
    a, b = two_stocks()
    closing = sell(a)
    h = portfolio(
        (trade(a, 1), trade(b, 2)), reservations=(Reservation(intent=closing, status="UNKNOWN"),)
    )
    r = reconstruct(h)
    assert len(r.commitments) == 2
    assert r.commitments[0].uncertain
    assert r.reserved_cash == D(".44")
    assert "ACCOUNT_UNCERTAIN" in r.entry_blockers


def test_limit_reduction_does_not_remove_positions_or_reserves():
    a, b = two_stocks()
    h = portfolio((trade(a, 1), trade(b, 2)))
    for limit in (0, 1, 2):
        r = reconstruct(changed(h, policy=changed(h.policy, max_plays=limit)))
        assert len(r.ledger.positions) == 2
        assert r.reserved_cash == D(".44")


def test_mixed_stock_option_replay_has_one_cash_balance(option_trades):
    options, _ = option_trades
    a, _ = two_stocks()
    a = changed(a, instrument=changed(a.instrument, symbol="QQQ", instrument_id="stock-qqq"))
    option = labeled(changed(options[0], fill=changed(options[0].fill, sequence=2)))
    h = portfolio((trade(a, 1), option))
    r = reconstruct(h)
    assert len(r.ledger.positions) == 2
    assert r.ledger.positions[a.client_id].quantity == 2
    assert r.ledger.positions[option.intent.client_id].quantity == option.fill.quantity
    assert (
        r.ledger.cash
        == 1000 - D("200.12") - option.fill.price * option.fill.quantity * 100 - option.fill.fee
    )
    assert sum(p.invested_loss for p in r.commitments) == sum(
        p.basis for p in r.ledger.positions.values()
    )


def test_same_underlying_stock_and_option_is_rejected(option_trades):
    options, _ = option_trades
    event = labeled(changed(options[0], fill=changed(options[0].fill, sequence=2)))
    with pytest.raises(ValueError, match="Duplicate portfolio exposure"):
        reconstruct(portfolio((trade(buy(), 1), event)))


@pytest.mark.parametrize("defect", ["missing", "foreign", "other-play"])
def test_exit_cannot_target_another_play(defect):
    a, b = two_stocks()
    close = sell(a)
    if defect == "missing":
        with pytest.raises(ValueError):
            changed(close, closing_entry_client_id=None)
        return
    close = changed(
        close, closing_entry_client_id="unknown" if defect == "foreign" else b.client_id
    )
    with pytest.raises(ValueError):
        reconstruct(portfolio((trade(a, 1), trade(b, 2), trade(close, 3))))


def test_duplicate_fill_and_resume_after_exit_do_not_duplicate_cash():
    a, _ = two_stocks()
    first = trade(a, 1, quantity="1", fee=".11")
    duplicate = changed(first, fill=changed(first.fill, sequence=2))
    with pytest.raises(ValueError, match="DUPLICATE"):
        reconstruct(portfolio((first, duplicate)))
    exit_event = trade(sell(a, quantity="1"), 2)
    later = trade(a, 3, quantity="1", fee=".01", at=exit_event.fill.occurred_at)
    with pytest.raises(ValueError, match="CANNOT_RESUME"):
        reconstruct(portfolio((first, exit_event, later)))


def test_no_silent_legacy_enrollment_or_scalar_position():
    a, b = two_stocks()
    legacy = history((trade(a, 1), trade(b, 2)))
    with pytest.raises(ValueError):
        reconstruct(legacy)
    h = portfolio((trade(a, 1),))
    with pytest.raises(ValueError, match="FROZEN_IDENTITY"):
        verify_extension(history(), h)
    ledger = reconstruct(h).ledger
    with pytest.raises(ValueError, match="explicit play"):
        PortfolioLedger.model_validate(
            {**ledger.model_dump(), "stock_position": ledger.positions[a.client_id]}
        )


def test_unknown_costs_and_shared_exposure_do_not_gain_second_budget():
    a, b = two_stocks()
    h = portfolio((trade(a, 1),), costs=tuple(changed(c, amount=None) for c in allocation()))
    r = reconstruct(h)
    assert r.daily_loss_available is r.total_loss_available is None
    assert "MIXED_COST_UNKNOWN" in r.entry_blockers
    c = capacity(h, r, revision=0, reconciled=True, halted=False)
    candidate = reconstruct(
        portfolio(reservations=(Reservation(intent=b, status="PREPARED"),))
    ).commitments[0]
    assert set(entry_blockers(c, candidate)) >= {"COSTS_UNKNOWN", "ACCOUNT_LOSS_BUDGET"}
    known = reconstruct(portfolio((trade(a, 1),)))
    c = capacity(portfolio(), known, revision=0, reconciled=True, halted=False)
    c = changed(c, index_exposure_limit="300")
    assert "CORRELATED_INDEX_EXPOSURE" in entry_blockers(c, candidate)


def test_account_funds_settlement_does_not_drop_an_open_play():
    a, b = two_stocks()
    events = (trade(a, 1), trade(b, 2), trade(sell(a), 3))
    receipt = OptionReceipt(
        receipt_id="settled",
        sequence=4,
        kind="FUNDS_SETTLED",
        occurred_at=NOW,
        cash_change="203.88",
    )
    r = reconstruct(portfolio((*events, Settlement(receipt=receipt))))
    assert set(r.ledger.positions) == {b.client_id}
    assert r.ledger.settled_cash == r.ledger.cash


def relabel_option(event, *, client_id, symbol, sequence, right="CALL", closing=None):
    """Clearly synthetic second instrument; retain execution-price/fee evidence."""
    import hashlib

    contract = changed(
        event.intent.instrument.contract, underlying=symbol, root=symbol, right=right
    )
    instrument = changed(
        event.intent.instrument, contract=contract, instrument_id=symbol + "-option"
    )
    intent = changed(
        event.intent,
        instrument=instrument,
        client_id=client_id,
        source_key=client_id,
        closing_entry_client_id=closing,
    )
    q = changed(event.fill.quote, instrument=instrument)
    underlying = event.fill.underlying
    if underlying is not None:
        underlying = changed(underlying, symbol=symbol)
    fill = changed(
        event.fill,
        quote=q,
        quote_hash=hashlib.sha256(q.model_dump_json().encode()).hexdigest(),
        order_id="order-" + client_id,
        fill_id="fill-" + client_id,
        sequence=sequence,
        underlying=underlying,
    )
    return changed(event, intent=intent, fill=fill)


def test_two_option_plays_and_exact_independent_close(option_trades):
    options, _ = option_trades
    a = labeled(options[0])
    b = labeled(
        relabel_option(options[0], client_id="qqq-entry", symbol="QQQ", sequence=2, right="PUT")
    )
    close = changed(
        options[1],
        intent=changed(options[1].intent, closing_entry_client_id=a.intent.client_id),
        fill=changed(options[1].fill, sequence=3),
    )
    h = portfolio((a, b, close))
    result = reconstruct(h)
    assert set(result.ledger.positions) == {b.intent.client_id}
    assert result.ledger.positions[b.intent.client_id].contract.right == "PUT"
    assert result.ledger.positions[b.intent.client_id].lots[0].price == b.fill.price
    assert result.commitments[0].family == "DEGEN"
    assert result.ledger.position is None


def test_option_expiry_requires_exact_play_and_preserves_other_holding(option_trades):
    options, _ = option_trades
    a = labeled(options[0])
    b = labeled(relabel_option(options[0], client_id="qqq-entry", symbol="QQQ", sequence=2))
    expires = a.intent.instrument.contract.expires_at
    receipt = OptionReceipt(
        receipt_id="expiry-a",
        sequence=3,
        kind="EXPIRED_WORTHLESS",
        occurred_at=expires,
        contract=a.intent.instrument.contract,
        quantity=a.fill.quantity,
        settlement_value="0",
        cash_change="0",
    )
    h = portfolio(
        (a, b, Settlement(receipt=receipt, play_id=a.intent.client_id)), captured_at=expires
    )
    result = reconstruct(h)
    assert set(result.ledger.positions) == {b.intent.client_id}
    assert result.ledger.cash == 1000 - sum(
        e.fill.price * e.fill.quantity * 100 + e.fill.fee for e in (a, b)
    )
    for identity in (None, "foreign", b.intent.client_id):
        with pytest.raises(ValueError):
            reconstruct(changed(h, events=(a, b, Settlement(receipt=receipt, play_id=identity))))


def test_price_improvement_does_not_stay_reserved_after_partial_fill():
    a, _ = two_stocks()
    event = trade(a, 1, quantity="1", price="99", fee=".11")
    result = reconstruct(
        portfolio((event,), reservations=(Reservation(intent=a, status="PARTIAL"),))
    )
    assert result.ledger.positions[a.client_id].basis == 99
    assert result.reserved_cash == D("100.23")
    assert result.available_settled_cash == D("800.66")


def test_duplicate_reservation_and_two_working_orders_for_one_play_are_invalid():
    a, _ = two_stocks()
    with pytest.raises(ValueError, match="Duplicate portfolio reservation"):
        portfolio(
            reservations=(
                Reservation(intent=a, status="OPEN"),
                Reservation(intent=a, status="OPEN"),
            )
        )
    close = sell(a, quantity="1")
    with pytest.raises(ValueError, match="One unresolved order per play"):
        reconstruct(
            portfolio(
                (trade(a, 1, quantity="1", fee=".11"),),
                reservations=(
                    Reservation(intent=a, status="PARTIAL"),
                    Reservation(intent=close, status="OPEN"),
                ),
            )
        )


def test_option_source_liquidity_not_renewed_by_receive_time(option_trades):
    from app.mixed.portfolio_accounting import check_option_source_size

    options, _ = option_trades
    e = options[0]
    q = changed(e.fill.quote, ask_size=e.fill.quantity)
    first = changed(e.fill, quote=q)
    used = {}
    check_option_source_size(e.intent, first, used)
    later = changed(first, quote=changed(q, received_at=q.received_at + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="SOURCE_SIZE_EXCEEDED"):
        check_option_source_size(e.intent, later, used)


def test_portfolio_money_is_independent_of_global_decimal_precision():
    from decimal import localcontext

    a, b = two_stocks()
    h = portfolio((trade(a, 1),), reservations=(Reservation(intent=b, status="OPEN"),))
    expected = reconstruct(h)
    with localcontext() as context:
        context.prec = 5
        assert reconstruct(h) == expected
