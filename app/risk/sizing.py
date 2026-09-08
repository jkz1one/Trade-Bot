from __future__ import annotations

from decimal import Decimal

from app.domain.models import Quote


def effective_loss_distance_fraction(
    quote: Quote,
    invalidation_price: Decimal,
    atr_fraction: Decimal,
    *,
    volatility_floor_multiplier: Decimal = Decimal("0.35"),
    slippage_floor_multiplier: Decimal = Decimal("1.50"),
) -> Decimal:
    entry = quote.ask
    proposed = abs(entry - invalidation_price) / entry
    volatility_floor = atr_fraction * volatility_floor_multiplier
    spread_floor = quote.spread_fraction * slippage_floor_multiplier
    return max(proposed, volatility_floor, spread_floor)
