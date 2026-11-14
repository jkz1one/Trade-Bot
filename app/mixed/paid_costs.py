"""One immutable model-charge history for mixed native cash and trade outcomes."""

import json
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from app.mixed.models import CostRecord
from app.options.engine import exact, fingerprint


def enrolled(policy):
    return policy.mixed_owner is not None and policy.mixed_owner.reasoning == "mixed-paid-entry-v1"


@exact
def _entry_cost_proof(strategy, configuration, call_items, inputs, started_at, frame_hash, evidence):
    # Pure validation of the same immutable SQL values used for original entry
    # checks. Cache just the clock bounds and evidence hash, never entry authority.
    from app.mixed.entry import _validate_entry_sources

    call = dict(call_items)
    frame = {"inputs_json": inputs, "started_at": started_at, "fingerprint": frame_hash}
    request, _, _ = _validate_entry_sources(
        call["source_key"], json.loads(evidence), strategy, configuration, call, frame, usable=False
    )
    return (
        request.packet.as_of,
        request.packet.valid_until,
        fingerprint({"request": request, "call": call}),
    )


# At most 64 keys of 256 Ki characters each (at most 64 MiB of string storage).
# Larger inputs undergo identical validation without being retained.
_cached_entry_cost_proof = lru_cache(maxsize=64)(_entry_cost_proof)


def records(db, policy):
    if not enrolled(policy):
        return ()
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
    entry_configuration = None
    for call in calls:
        row = db.execute(
            "SELECT result_json,inputs_json,started_at,fingerprint FROM execution_option_opportunities WHERE cycle_key=?",
            (call["source_key"],),
        ).fetchone()
        if row is None:
            raise ValueError("MIXED_MODEL_OPPORTUNITY_MISSING")
        result_json = row["result_json"] or "{}"
        evidence = json.loads(result_json)
        entry_id = None
        kind = "ENTRY_MODEL"
        if "position_request" in evidence:
            kind = "MANAGEMENT_MODEL"
            if evidence["position_request"]["packet"]["version"] == "portfolio-position-packet-v2":
                from app.mixed.portfolio_management import stored

                request, _, _, _ = stored(db, call["source_key"])
                entry_id = request.packet.play_id
            elif (
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
            as_of, valid_until = request.packet.as_of, request.packet.valid_until
            evidence_hash = fingerprint({"request": request, "call": dict(call)})
        else:
            if entry_configuration is None:
                entry_configuration = (
                    db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0],
                    db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0],
                )
            # SQLite columns with TEXT affinity can still contain other types.
            # Validate such originals directly, without admitting them to the cache.
            sources = (*entry_configuration, *row, *call)
            cacheable = all(value is None or isinstance(value, str) for value in sources)
            proof = _entry_cost_proof
            if cacheable and sum(len(value) for value in sources if value is not None) <= 256 * 1024:
                proof = _cached_entry_cost_proof
            as_of, valid_until, evidence_hash = proof(
                *entry_configuration, tuple(dict(call).items()),
                row["inputs_json"], row["started_at"], row["fingerprint"], result_json,
            )
            if policy.mixed_owner.portfolio is not None:
                selected = db.execute(
                    "SELECT client_id FROM execution_portfolio_orders WHERE (source_key=? OR json_extract(approval_json,'$.inputs.scope_arbitration.cycle_key')=?) AND json_extract(intent_json,'$.side')='BUY'",
                    (call["source_key"], call["source_key"]),
                ).fetchone()
                entry_id = selected[0] if selected else None
        at = datetime.fromisoformat(call["started_at"])
        if not as_of <= at < valid_until:
            raise ValueError("MIXED_MODEL_ATTEMPT_CLOCK_CHANGED")
        result.append(
            CostRecord(
                cost_id=call["source_key"],
                kind=kind,
                entry_client_id=entry_id,
                occurred_at=at,
                amount=Decimal(call["cost"]) if call["cost"] is not None else None,
                evidence_hash=evidence_hash,
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
