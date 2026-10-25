"""Pure display mapping of already verified mixed observer records."""

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from app.mixed.observer import history_chart


def evidence_id(value):
    return "record-" + hashlib.sha256(str(value).encode()).hexdigest()


def display_time(value):
    if not value:
        return "Time unavailable"
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        return value
    return at.astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %Y %H:%M:%S %Z")


def family_of(intent):
    return intent.get("family") or (intent.get("entry_lineage") or {}).get("family") or "UNKNOWN"


def chart_with_gaps(points):
    chart = history_chart(points)
    if chart is None:
        return None
    # Connect only observed endpoints, with a distinct unavailable-interval style.
    # No value is calculated for missing snapshots, and solid segments stay broken.
    known = [i for i, point in enumerate(points) if point["equity"] is not None]
    chart["gaps"] = [
        f"{left['x']},{left['y']} {right['x']},{right['y']}"
        for index, (left, right) in enumerate(zip(chart["dots"], chart["dots"][1:]))
        if known[index + 1] > known[index] + 1
    ]
    return chart


def mixed_view(data):
    """Never infer cycle joins from timestamps or join a paged cycle to latest orders."""
    orders = data.get("orders", [])
    decisions = data.get("decisions", [])
    selected = decisions[0] if decisions else None
    key = selected["key"] if selected else orders[0]["intent"]["source_key"] if orders else None
    linked = [o for o in orders if o["intent"]["source_key"] == key] if key else []
    first = linked[0] if len(linked) == 1 else None
    verified = data.get("accounting") == "VERIFIED"
    fills = (
        [f for o in linked for f in (o.get("observation") or {}).get("fills", [])]
        if verified
        else []
    )
    destination = (
        "#" + evidence_id(key)
        if selected
        else "#" + evidence_id(first["intent"]["client_id"])
        if first
        else "#decisions"
    )
    stages = [
        {
            "label": "Proposal",
            "value": (selected.get("proposal") or {}).get("action", "No model proposal recorded")
            if selected
            else "Recorded plan"
            if first
            else "No record",
            "at": selected["started_at"]
            if selected
            else first["intent"]["prepared_at"]
            if first
            else None,
            "href": destination,
        },
        {
            "label": "Approval",
            "value": "Approved terms"
            if first
            else "See saved review"
            if selected
            else "No linked order",
            "at": first["intent"]["prepared_at"] if first else None,
            "href": "#" + evidence_id(first["intent"]["client_id"]) if first else destination,
        },
        {
            "label": "Attempt",
            "value": first["status"]
            if first and first["attempted_at"]
            else "Not recorded in this view",
            "at": first["attempted_at"] if first else None,
            "href": "#" + evidence_id(first["intent"]["client_id"]) if first else destination,
        },
        {
            "label": "Fills",
            "value": str(len(fills)) + " verified receipts"
            if verified and first and first.get("observation")
            else "Coverage unavailable",
            "at": max((f["occurred_at"] for f in fills), default=None),
            "href": "#" + evidence_id(first["intent"]["client_id"]) if first else destination,
        },
    ]
    families = []
    for name in ("DEGEN", "SWING", "SCOPE"):
        own = [o for o in orders if family_of(o["intent"]) == name]
        families.append({"name": name, "latest": own[0] if own else None})
    activity = []
    for order in orders:
        intent = order["intent"]
        base = {
            "family": family_of(intent),
            "symbol": order["symbol"],
            "href": "#" + evidence_id(intent["client_id"]),
        }
        activity.append(
            base | {"kind": "REVIEW", "label": "Order approved", "at": intent["prepared_at"]}
        )
        if order["attempted_at"]:
            activity.append(
                base
                | {
                    "kind": "ATTEMPT",
                    "label": "Order attempt · " + order["status"],
                    "at": order["attempted_at"],
                }
            )
        if verified:
            for fill in (order.get("observation") or {}).get("fills", []):
                activity.append(
                    base
                    | {
                        "kind": "FILL",
                        "label": "Fill · " + str(fill["quantity"]) + " @ $" + str(fill["price"]),
                        "at": fill["occurred_at"],
                    }
                )
    for decision in decisions:
        activity.append(
            {
                "kind": "DECISION",
                "label": "Decision · " + str(decision["status"]),
                "at": decision["started_at"],
                "href": "#" + evidence_id(decision["key"]),
                "family": "UNKNOWN",
                "symbol": "",
            }
        )
    for cost in data.get("costs", []):
        activity.append(
            {
                "kind": "COST",
                "label": cost["kind"]
                + " · "
                + ("$" + cost["amount"] if cost["amount"] is not None else "Unknown cost"),
                "at": cost["occurred_at"],
                "href": "#costs",
                "family": "UNKNOWN",
                "symbol": "",
            }
        )
    points = data.get("points", [])
    return {
        "key": key,
        "stages": stages,
        "families": families,
        "activity": sorted(activity, key=lambda e: datetime.fromisoformat(e["at"]), reverse=True)[
            :40
        ],
        "ranges": [
            {"name": name, "points": subset, "chart": chart_with_gaps(subset)}
            for name, subset in (("20", points[-20:]), ("50", points[-50:]), ("all", points))
        ],
    }
