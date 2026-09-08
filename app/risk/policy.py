from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskPolicy:
    name: str
    max_risk_fraction: Decimal
    max_exposure_fraction: Decimal
    shutdown_drawdown_fraction: Decimal


TIERS: tuple[tuple[Decimal, RiskPolicy], ...] = (
    (Decimal("25"), RiskPolicy("MICRO", Decimal("0.08"), Decimal("0.90"), Decimal("0.50"))),
    (Decimal("100"), RiskPolicy("SMALL", Decimal("0.06"), Decimal("0.80"), Decimal("0.45"))),
    (Decimal("1000"), RiskPolicy("GROWTH", Decimal("0.04"), Decimal("0.65"), Decimal("0.35"))),
    (Decimal("10000"), RiskPolicy("SCALE", Decimal("0.025"), Decimal("0.50"), Decimal("0.25"))),
    (Decimal("Infinity"), RiskPolicy("PRESERVATION", Decimal("0.015"), Decimal("0.35"), Decimal("0.20"))),
)


def policy_for_equity(equity: Decimal) -> RiskPolicy:
    for upper, policy in TIERS:
        if equity < upper:
            return policy
    raise AssertionError("unreachable")


def drawdown_modifier(drawdown: Decimal, shutdown: Decimal) -> Decimal:
    if shutdown <= 0 or drawdown >= shutdown:
        return Decimal("0")
    # Progressive de-risking: full risk at <=20% of shutdown DD, then linear to zero.
    start = shutdown * Decimal("0.20")
    if drawdown <= start:
        return Decimal("1")
    remaining = shutdown - drawdown
    span = shutdown - start
    return max(Decimal("0"), min(Decimal("1"), remaining / span))
