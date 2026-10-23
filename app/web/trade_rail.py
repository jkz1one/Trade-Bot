"""Stored underlying-price rail, adapted from pinned SignalFlow marker grouping.

Reference: PlayProgressRail.tsx, f9eaf2c1b5d13dca287ee7138126883065b00395.
No premium prices are plotted on an underlying axis; no touch implies a fill.
"""

from decimal import Decimal


def trade_rail(position):
    if not position:
        return None
    p = position
    markers = [("Original stop", Decimal(p["original_stop"]))]
    if p["active_stop"] != p["original_stop"]:
        markers.append(("Active stop", Decimal(p["active_stop"])))
    if p["asset"] == "STOCK":
        markers.append(("Entry", Decimal(p["basis"]) / Decimal(p["quantity"])))
        q = p["details"].get("quote")
        if q:
            markers.append(
                (
                    "Stored bid" if p["mark_status"] == "USABLE_STORED_BID" else "Last bid",
                    Decimal(q["bid"]),
                )
            )
    else:
        reference = p["details"].get("entry_underlying_reference") or {}
        if reference.get("status") == "READY" and reference.get("reference") is not None:
            markers.append(("Entry reference", Decimal(reference["reference"])))
        # Current option premium must never masquerade as an underlying mark.
    markers.extend(
        (f"T{i + 1}", Decimal(t["underlying_price"])) for i, t in enumerate(p["targets"])
    )
    low, high = min(v for _, v in markers), max(v for _, v in markers)
    span = high - low or Decimal(1)
    ordered = sorted(
        (Decimal(3) + (value - low) / span * 94, label, value) for label, value in markers
    )
    groups = []
    # SignalFlow's 5.5-point collision grouping and alternating 14-point label rows.
    for x, label, value in ordered:
        if groups and x - groups[-1]["position"] < Decimal("5.5"):
            group = groups[-1]
            group["positions"].append(x)
            group["position"] = sum(group["positions"]) / len(group["positions"])
            group["labels"].append(f"{label} {value.normalize():f}")
        else:
            groups.append(
                {"position": x, "positions": [x], "labels": [f"{label} {value.normalize():f}"]}
            )
    previous = None
    for group in groups:
        group["row"] = (
            1 - previous["row"] if previous and group["position"] - previous["position"] < 14 else 0
        )
        group["align"] = (
            "left" if group["position"] < 12 else "right" if group["position"] > 88 else "center"
        )
        previous = group
    return groups
