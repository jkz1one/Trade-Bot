"""One immutable model-charge history for mixed native cash and trade outcomes."""

import json
from datetime import datetime
from decimal import Decimal

from app.mixed.models import CostRecord
from app.options.engine import exact, fingerprint


def enrolled(policy):
    return policy.mixed_owner is not None and policy.mixed_owner.reasoning == "mixed-paid-entry-v1"


def records(db, policy):
    if not enrolled(policy):
        return ()
    from app.mixed.entry import validate_stored

    result = []
    calls = db.execute(
        "SELECT * FROM execution_model_calls ORDER BY started_at,source_key"
    ).fetchall()
    keys = {c["source_key"] for c in calls}
    # Lost calls cannot silently turn a retained response into free advice.
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_opportunities'"
    ).fetchone():
        for row in db.execute("SELECT cycle_key,result_json FROM execution_option_opportunities"):
            evidence = json.loads(row["result_json"] or "{}")
            if (
                any(k in evidence for k in ("entry_result", "position_result"))
                and row["cycle_key"] not in keys
            ):
                raise ValueError("MIXED_MODEL_ATTEMPT_MISSING")
    for call in calls:
        row = db.execute(
            "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
            (call["source_key"],),
        ).fetchone()
        if row is None:
            raise ValueError("MIXED_MODEL_OPPORTUNITY_MISSING")
        evidence = json.loads(row[0] or "{}")
        entry_id = None
        kind = "ENTRY_MODEL"
        if "position_request" in evidence:
            kind = "MANAGEMENT_MODEL"
            if (
                evidence["position_request"]["packet"]["version"]
                == "mixed-stock-position-packet-v1"
            ):
                from app.mixed.position import stored

                request, _, _, _ = stored(db, call["source_key"])
                entry_id = request.packet.entry.client_id
            else:
                from app.options.attribution import decision_attribution
                from app.options.position_judgment import PositionRequest

                request = PositionRequest.model_validate(evidence["position_request"])
                decision_attribution(db, call["source_key"], evidence, policy)
                entry_id = request.packet.entry.client_id
        else:
            request, _, _ = validate_stored(db, call["source_key"], evidence, usable=False)
        at = datetime.fromisoformat(call["started_at"])
        if not request.packet.as_of <= at < request.packet.valid_until:
            raise ValueError("MIXED_MODEL_ATTEMPT_CLOCK_CHANGED")
        result.append(
            CostRecord(
                cost_id=call["source_key"],
                kind=kind,
                entry_client_id=entry_id,
                occurred_at=at,
                amount=Decimal(call["cost"]) if call["cost"] is not None else None,
                evidence_hash=fingerprint({"request": request, "call": dict(call)}),
            )
        )
    return tuple(result)


@exact
def apply(db, policy, outcome, intervals):
    calls = []
    for record in records(db, policy):
        at = record.occurred_at
        # A flat-account entry call at the exact close clock belongs to the
        # following actual entry. Management retains its explicit original owner.
        owned = next((i for i, a, b in intervals if a <= at and (b is None or at < b)), None)
        if record.entry_client_id is not None:
            owned = record.entry_client_id
        if owned is None:
            owned = next((i for i, a, _ in intervals if a >= at), None)
        if owned == outcome["entry_client_id"]:
            calls.append(record.model_dump(mode="json"))
    pending = any(
        db.execute(
            "SELECT status FROM execution_option_opportunities WHERE cycle_key=?", (c["cost_id"],)
        ).fetchone()[0]
        == "STARTED"
        and c["kind"] == "MANAGEMENT_MODEL"
        for c in calls
    )
    known = sum((Decimal(c["amount"]) for c in calls if c["amount"] is not None), Decimal(0))
    before = outcome.get("net_after_known_execution_and_model_costs")
    # Existing option accounting is run with its generic call allocator disabled
    # only for this explicit cohort; this is the single model-cost subtraction.
    net = (
        Decimal(before) - known
        if before is not None and not pending and all(c["amount"] is not None for c in calls)
        else None
    )
    return {
        **outcome,
        "model_calls": calls,
        "known_model_cost": str(known),
        "net_after_known_execution_and_model_costs": str(net) if net is not None else None,
    }
