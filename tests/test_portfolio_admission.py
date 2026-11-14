"""Shared remaining risk, per-play close identity, and ordinary native quote gates."""

from decimal import Decimal as D

import pytest
from test_mixed_accounting import NOW, buy, changed, trade
from test_mixed_admission import proposal, quote, session
from test_option_execution import configuration
from test_portfolio_accounting import portfolio, two_stocks

from app.mixed.governor import admit_stock, option_account
from app.mixed.models import Reservation, StockProposal
from app.mixed.portfolio_admission import admit_portfolio_option


def stock(h, p=None, q=None, *, identity=None):
    p = p or proposal()
    q = q or quote(instrument=p.instrument)
    return admit_stock(
        p, q, h, session(underlying=p.instrument.symbol), now=NOW, reconciled=True, play_id=identity
    )


def option(h, **kwargs):
    data, _, _ = configuration()
    return admit_portfolio_option(
        data["proposal"],
        data["quote"],
        data["underlying"],
        h,
        changed(data["session"], source=h.policy.options.session_source),
        now=NOW,
        reconciled=True,
        **kwargs,
    )


def test_second_stock_is_sized_against_remaining_shared_risk():
    a, b = two_stocks()
    h = portfolio((trade(a, 1),))
    result = stock(h, proposal(instrument=b.instrument))
    assert result.outcome == "APPROVED"
    assert result.quantity == 2
    assert result.entry_debit + result.reserved_exit_fee + D("200.22") <= 500
    duplicate = stock(h)
    assert duplicate.outcome == "REJECTED"
    assert "DUPLICATE_EXPOSURE" in duplicate.reasons


def test_pending_entry_already_spends_budget_but_not_second_slot():
    a, b = two_stocks()
    h = portfolio(reservations=(Reservation(intent=a, status="PREPARED"),))
    r = stock(h, proposal(instrument=b.instrument))
    assert r.outcome == "APPROVED" and r.quantity == 2
    h = changed(h, reservations=(*h.reservations, Reservation(intent=b, status="PREPARED")))
    r = stock(h, proposal(instrument=b.instrument))
    assert "PLAY_CAPACITY" in r.reasons


def test_stock_does_not_occupy_every_option_slot_but_keeps_risk_reserved():
    _, b = two_stocks()
    h = portfolio((trade(b, 1),))
    result = option(h)
    assert result.outcome == "APPROVED"
    assert result.full_premium_loss + D("200.22") <= 500
    assert result.quantity < option(portfolio()).quantity
    with pytest.raises(ValueError, match="candidate-specific"):
        option_account(h, reconciled=True)


def test_option_candidate_on_existing_underlying_is_blocked():
    h = portfolio((trade(buy(), 1),))
    r = option(h)
    assert r.outcome == "REJECTED" and "DUPLICATE_EXPOSURE" in r.reasons


def test_unknown_attempt_blocks_new_entry_without_blocking_other_close():
    a, b = two_stocks()
    h = portfolio((trade(a, 1),), reservations=(Reservation(intent=b, status="UNKNOWN"),))
    assert "ACCOUNT_UNCERTAIN" in stock(h, proposal(instrument=b.instrument)).reasons
    p = StockProposal(action="CLOSE", instrument=a.instrument, thesis="Exact exit")
    assert stock(h, p, identity=a.client_id).outcome == "APPROVED"


def test_close_requires_exact_known_play_and_no_per_play_working_order():
    a, b = two_stocks()
    h = portfolio((trade(a, 1), trade(b, 2)))
    p = StockProposal(action="CLOSE", instrument=b.instrument, thesis="Exit QQQ")
    with pytest.raises(ValueError, match="exact play identity"):
        stock(h, p)
    with pytest.raises(ValueError, match="Unknown or closed"):
        stock(h, p, identity="missing")
    assert stock(h, p, identity=a.client_id).outcome == "REJECTED"
    assert stock(h, p, identity=b.client_id).outcome == "APPROVED"


def test_zero_limit_keeps_exits_available():
    a, b = two_stocks()
    h = portfolio((trade(a, 1),))
    h = changed(h, policy=changed(h.policy, max_plays=0))
    assert "PLAY_CAPACITY" in stock(h, proposal(instrument=b.instrument)).reasons
    p = StockProposal(action="CLOSE", instrument=a.instrument, thesis="Exit")
    assert stock(h, p, identity=a.client_id).outcome == "APPROVED"


@pytest.mark.parametrize(
    "changes", [{"entitlement": "UNKNOWN"}, {"ask_size": None}, {"complete": False}]
)
def test_portfolio_admission_does_not_relax_executable_stock_evidence(changes):
    result = stock(portfolio(), q=quote(**changes))
    assert result.outcome == "REJECTED"


def test_index_budget_cannot_be_spent_again_for_different_symbol():
    a, b = two_stocks()
    h = portfolio((trade(a, 1),))
    h = changed(h, policy=changed(h.policy, index_exposure_limit="250"))
    r = stock(h, proposal(instrument=b.instrument))
    assert r.outcome == "REJECTED" and "MIXED_STOCK_NO_FUNDED_SIZE" in r.reasons


def test_portfolio_admission_receipts_cannot_be_reused_by_legacy_consumers():
    from app.mixed.models import StockAdmission
    from app.options.models import OptionAdmission

    h = portfolio()
    stock_result = stock(h)
    option_result = option(h)
    for cls, result in ((StockAdmission, stock_result), (OptionAdmission, option_result)):
        with pytest.raises(ValueError):
            cls.model_validate(result.model_dump())
        assert result.history_hash
    a, _ = two_stocks()
    p = StockProposal(action="CLOSE", instrument=a.instrument, thesis="Exit")
    closed = stock(portfolio((trade(a, 1),)), p, identity=a.client_id)
    assert closed.play_id == a.client_id


def small_cash_policy(h, capital):
    return changed(
        h.policy,
        capital=capital,
        daily_loss_limit=capital,
        total_loss_limit=capital,
        exposure_limit=capital,
        index_exposure_limit=capital,
    )


def test_close_can_spend_its_own_exit_fee_reserve():
    a, _ = two_stocks()
    h = portfolio((trade(a, 1),))
    h = changed(h, policy=small_cash_policy(h, "200.23"))
    p = StockProposal(action="CLOSE", instrument=a.instrument, thesis="Low-value exit")
    r = stock(h, p, quote(bid=".01", ask=".02"), identity=a.client_id)
    assert r.outcome == "APPROVED"


def test_close_cannot_spend_another_plays_exit_fee_reserve():
    a, b = two_stocks()
    a = changed(a, quantity="1", approved_entry_debit="100.11", reserved_exit_fee=".11")
    b = changed(b, quantity="1", approved_entry_debit="100.11", reserved_exit_fee=".11")
    h = portfolio((trade(a, 1), trade(b, 2)))
    h = changed(h, policy=small_cash_policy(h, "200.33"))
    p = StockProposal(action="CLOSE", instrument=a.instrument, thesis="Low-value exit")
    r = stock(h, p, quote(bid=".01", ask=".02"), identity=a.client_id)
    assert r.outcome == "REJECTED" and "MIXED_STOCK_EXIT_FEE_UNFUNDED" in r.reasons
