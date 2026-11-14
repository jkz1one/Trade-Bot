from decimal import Decimal

from app.robinhood.models import (
    RobinhoodAccount,
    RobinhoodPortfolio,
    RobinhoodPosition,
    RobinhoodTruth,
)
from app.robinhood.reconcile import reconcile_truth


def truth(position=None, unsupported=Decimal("0")):
    return RobinhoodTruth(
        account=RobinhoodAccount(
            account_number="RH1",
            type="cash",
            brokerage_account_type="individual",
            agentic_allowed=True,
            state="active",
            deactivated=False,
            permanently_deactivated=False,
        ),
        portfolio=RobinhoodPortfolio(
            total_value=Decimal("10"),
            equity_value=Decimal("0"),
            cash=Decimal("10"),
            buying_power=Decimal("10"),
            unleveraged_buying_power=Decimal("10"),
            unsupported_value=unsupported,
        ),
        positions=[] if position is None else [position],
        working_orders=[],
    )


def test_empty_broker_and_empty_local_reconcile(repo):
    result = reconcile_truth(repo, truth())
    assert result.reconciled


def test_unowned_broker_position_halts(repo):
    position = RobinhoodPosition(
        symbol="AAPL",
        quantity=Decimal("1"),
        shares_available_for_sells=Decimal("1"),
        average_buy_price=Decimal("100"),
        type="long",
    )
    result = reconcile_truth(repo, truth(position))
    assert not result.reconciled
    assert "BROKER_POSITION_NOT_OWNED_LOCALLY" in result.reasons


def test_unsupported_assets_halt(repo):
    result = reconcile_truth(repo, truth(unsupported=Decimal("1")))
    assert not result.reconciled
    assert "UNSUPPORTED_ASSET_VALUE_PRESENT" in result.reasons
