from __future__ import annotations
from decimal import Decimal
from app.domain.models import AccountState


def net_strategy_pnl(account: AccountState, net_capital_flows: Decimal) -> Decimal:
    return account.equity - net_capital_flows


def simple_return(account: AccountState, net_capital_flows: Decimal) -> Decimal:
    if net_capital_flows <= 0:
        return Decimal("0")
    return net_strategy_pnl(account, net_capital_flows) / net_capital_flows


def capital_multiple(account: AccountState, initial_capital: Decimal, has_external_flows: bool) -> Decimal | None:
    if initial_capital <= 0 or has_external_flows:
        return None
    return account.equity / initial_capital
