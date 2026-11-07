"""Portfolio constraints only; these tests do not establish native integration."""

from decimal import Decimal

import pytest

from app.mixed.portfolio_capacity import PlayCommitment, PortfolioCapacity, entry_blockers


def play(name="a", symbol="SPY", **changes):
    return PlayCommitment.model_validate(
        dict(
            play_id=name,
            entry_client_id="entry-" + name,
            instrument_id="instrument-" + name,
            underlying=symbol,
            family="SWING",
            invested_loss="0",
            remaining_debit="100",
            exit_reserve="1",
            has_position=False,
            pending_entry=True,
            **changes,
        )
    )


def account(plays=(), **changes):
    values = {
        "account_id": "one",
        "population_id": "one",
        "revision": 1,
        "max_plays": 2,
        "settled_cash": "1000",
        "daily_loss_remaining": "500",
        "total_loss_remaining": "700",
        "exposure_limit": "800",
        "index_exposure_limit": "300",
        "costs_known": True,
        "reconciled": True,
        "halted": False,
        "plays": plays,
    }
    values.update(changes)
    return PortfolioCapacity.model_validate(values)


def changed(p, **values):
    return type(p).model_validate({**p.model_dump(), **values})


def test_two_reservations_then_capacity_and_no_strategy_slots():
    a, b, c = play(), play("b", "QQQ"), play("c", "IWM")
    assert not entry_blockers(account(), a)
    assert not entry_blockers(account((a,)), b)
    assert "PLAY_CAPACITY" in entry_blockers(account((a, b)), c)


def test_partial_fill_moves_reserved_to_invested_without_double_funding():
    a = play()
    partial = changed(a, has_position=True, invested_loss="40", remaining_debit="60")
    before = account((a,), settled_cash="150")
    after = account((partial,), settled_cash="110")
    b = play("b", "QQQ")
    assert entry_blockers(before, b) == entry_blockers(after, b)
    assert "SETTLED_FUNDS" in entry_blockers(after, b)


def test_confirmed_cancel_retains_filled_play_and_exit_reserve():
    a = changed(
        play(), has_position=True, invested_loss="40", remaining_debit="0", pending_entry=False
    )
    assert "PLAY_CAPACITY" in entry_blockers(account((a,), max_plays=1), play("b", "QQQ"))


def test_spy_and_qqq_share_index_exposure_cap():
    a = changed(play(), remaining_debit="200")
    assert "CORRELATED_INDEX_EXPOSURE" in entry_blockers(account((a,)), play("b", "QQQ"))
    assert "CORRELATED_INDEX_EXPOSURE" not in entry_blockers(account((a,)), play("b", "IBM"))


def test_duplicate_underlying_and_retries():
    a = play()
    assert "DUPLICATE_EXPOSURE" in entry_blockers(account((a,)), play("b"))
    assert "ENTRY_ALREADY_RESERVED" in entry_blockers(account((a,)), a)
    with pytest.raises(ValueError):
        account((a, play("b")))


@pytest.mark.parametrize(
    "field,reason",
    [
        ("settled_cash", "SETTLED_FUNDS"),
        ("daily_loss_remaining", "ACCOUNT_LOSS_BUDGET"),
        ("total_loss_remaining", "ACCOUNT_LOSS_BUDGET"),
    ],
)
def test_shared_funds_and_limits(field, reason):
    assert reason in entry_blockers(account((play(),), **{field: "150"}), play("b", "QQQ"))


def test_uncertainty_and_unknown_costs_block_entry():
    a = changed(play(), uncertain=True)
    reasons = entry_blockers(account((a,), costs_known=False), play("b", "QQQ"))
    assert "ACCOUNT_UNCERTAIN" in reasons and "COSTS_UNKNOWN" in reasons


def test_lower_limit_preserves_existing_plays():
    a, b = play(), play("b", "QQQ")
    state = account((a, b), max_plays=0)
    assert state.plays == (a, b)
    assert "PLAY_CAPACITY" in entry_blockers(state, play("c", "IBM"))


def test_strict_money_and_limits():
    with pytest.raises(ValueError):
        account(max_plays=3)
    with pytest.raises(ValueError):
        account(max_plays=True)
    with pytest.raises(ValueError):
        account(settled_cash=1.2)
    assert account().settled_cash == Decimal(1000)
