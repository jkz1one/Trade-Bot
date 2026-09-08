from __future__ import annotations

from decimal import Decimal


def benchmark_return(start_price: Decimal, current_price: Decimal) -> Decimal:
    if start_price <= 0:
        return Decimal("0")
    return current_price / start_price - Decimal("1")
