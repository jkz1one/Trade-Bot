"""Executable-bid trail on completed entry basis, never a net-profit claim."""

from decimal import Context, Decimal, localcontext


def verify_binding(intent, approval):
    if intent.premium_trail != approval.get("premium_trail"):
        raise ValueError("OPTION_PREMIUM_TRAIL_CHANGED")


def terms(position):
    trail = position.premium_trail if position else None
    return (trail.version, trail.entry_quantity, trail.entry_basis) if trail else None


def accounting_position(position, excluded):
    if position is None:
        return None
    data = position.model_dump(exclude=excluded)
    if position.premium_trail is not None:
        data["premium_trail"].pop("peak_bid")
    if position.trade_floor is not None:
        data["trade_floor"] = {"version": position.trade_floor.version}
    return data


def floor_value(trail, multiplier):
    """Return original-quantity premium equivalent; keep rational thresholds exact."""
    if trail is None or trail.entry_basis is None or trail.peak_bid is None:
        return None
    with localcontext(Context(prec=192)):
        basis = trail.entry_basis
        peak = trail.peak_bid * trail.entry_quantity * multiplier
        floors = []
        if peak >= basis * Decimal("1.20"):
            floors.append(basis * Decimal(".97"))
        if peak >= basis * Decimal("1.35"):
            floors.append(basis * Decimal("1.10"))
        if peak >= basis * Decimal("1.50"):
            floors.extend((basis * Decimal("1.25"), basis + (peak - basis) * Decimal(".55")))
        return max(floors) if floors else None


def assess(position, bid):
    trail = position.premium_trail
    if trail is None or trail.entry_basis is None:
        return trail, False
    trail = trail.model_copy(update={"peak_bid": max(trail.peak_bid or bid, bid)})
    floor = floor_value(trail, position.contract.multiplier)
    with localcontext(Context(prec=192)):
        crossed = (
            floor is not None and bid * trail.entry_quantity * position.contract.multiplier <= floor
        )
    return trail, crossed
