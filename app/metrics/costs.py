from __future__ import annotations
from decimal import Decimal


def economic_pnl(trading_pnl: Decimal, ai_cost: Decimal, friction: Decimal = Decimal("0")) -> Decimal:
    return trading_pnl - ai_cost - friction
