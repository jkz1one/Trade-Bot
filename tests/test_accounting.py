from decimal import Decimal
from app.metrics.performance import capital_multiple, net_strategy_pnl


def test_deposit_not_profit(broker):
    before=broker.account_state()
    assert before.equity == Decimal("10")
    broker.deposit(Decimal("990"))
    after=broker.account_state()
    assert after.equity == Decimal("1000")
    assert net_strategy_pnl(after, Decimal("1000")) == Decimal("0")
    assert capital_multiple(after, Decimal("10"), has_external_flows=True) is None


def test_withdrawal_not_loss(broker):
    broker.withdraw(Decimal("4"))
    after = broker.account_state()
    assert after.equity == Decimal("6")
    assert net_strategy_pnl(after, Decimal("6")) == Decimal("0")
