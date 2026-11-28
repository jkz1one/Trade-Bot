"""Read-only mixed loss receipts tied to reconstructed full-cost native outcomes."""

import json
from datetime import datetime

from app.options.engine import fingerprint
from app.options.loss_control import FamilyLossState, LossState, outcome_record, stored_state


def export_losses(db, policy, outcomes, events, *, boundary):
    view = stored_state(db)
    if policy is None or view is None or view["policy"] != policy.model_dump(mode="json"):
        raise ValueError("Original native mixed loss enrollment required")
    state = LossState.model_validate({k: view[k] for k in LossState.model_fields if k in view})
    enrolled = [e for e in events if e["kind"] == "NATIVE_LOSS_CONTROL_ENROLLED"]
    if len(enrolled) != 1 or json.loads(enrolled[0]["payload"]) != policy.model_dump(mode="json"):
        raise ValueError("Mixed loss enrollment audit mismatch")
    if state.last_checked_at > boundary:
        raise ValueError("Mixed loss state exceeds the retained boundary")
    latest, consumed, pauses = None, {}, []
    admissions = {
        json.loads(e["payload"])["source_key"]: e["sequence"]
        for e in events
        if e["kind"] == "OPTION_MODEL_ATTEMPT_ADMITTED"
    }
    for e in events:
        if e["kind"] == "NATIVE_LOSS_REVIEWED_RESET":
            raise ValueError("Operator loss resets are not declared by mixed fixture replay")
        if e["kind"] not in {
            "NATIVE_LOSS_OUTCOME_CONSUMED",
            "NATIVE_LOSS_CONTROL_REVIEWED",
            "OPTION_ENTRY_MODEL_RISK_PAUSED",
        }:
            continue
        at = datetime.fromisoformat(e["occurred_at"])
        if e["sequence"] <= enrolled[0]["sequence"] or at > boundary:
            raise ValueError("Mixed loss event outside original enrollment")
        value = json.loads(e["payload"])
        if e["kind"] == "NATIVE_LOSS_CONTROL_REVIEWED":
            latest = LossState.model_validate(value)
            if latest.last_checked_at != at:
                raise ValueError("Mixed loss review clock changed")
        elif e["kind"] == "NATIVE_LOSS_OUTCOME_CONSUMED":
            key = value["entry_client_id"]
            if key in consumed:
                raise ValueError("Mixed loss entry consumed twice")
            consumed[key] = (e, value)
        else:
            if admissions.get(value["source_key"], e["sequence"] + 1) <= e["sequence"]:
                raise ValueError("Mixed risk pause follows an admitted charge")
            pauses.append({"revision": e["sequence"], "occurred_at": e["occurred_at"], **value})
    if latest is None:
        latest = LossState(
            consecutive_losses=0,
            locked=False,
            consumed_entries=0,
            last_checked_at=datetime.fromisoformat(enrolled[0]["occurred_at"]),
            families=tuple(
                FamilyLossState(
                    family=f.family, consecutive_losses=0, locked=False, consumed_entries=0
                )
                for f in policy.families
            ),
        )
    if latest != state:
        raise ValueError("Mixed loss state differs from its native audit")
    rows = db.execute("SELECT * FROM execution_option_loss_outcomes ORDER BY rowid").fetchall()
    if {r["entry_client_id"] for r in rows} != set(consumed) or len(rows) != state.consumed_entries:
        raise ValueError("Complete mixed consumed outcome coverage required")
    by_entry = {o["entry_client_id"]: o for o in outcomes}
    records = []
    for row in rows:
        key = row["entry_client_id"]
        outcome = by_entry.get(key)
        if outcome is None or outcome["status"] != "COMPLETE":
            raise ValueError("Consumed mixed outcome is incomplete")
        record = outcome_record(outcome, policy)
        digest = fingerprint(record)
        event, payload = consumed[key]
        if (
            row["outcome_hash"] != digest
            or json.loads(row["record_json"]) != record
            or payload
            != {"entry_client_id": key, "outcome_hash": digest, "outcome": record["outcome"]}
            or not datetime.fromisoformat(record["closed_at"])
            <= datetime.fromisoformat(event["occurred_at"])
            <= state.last_checked_at
        ):
            raise ValueError("Mixed loss receipt differs from reconstructed full costs")
        records.append(
            {
                "revision": event["sequence"],
                "recognized_at": event["occurred_at"],
                "outcome_hash": digest,
                "record": record,
            }
        )
    for family in state.families:
        if family.consumed_entries != sum(
            r["record"].get("entry_lineage", {}).get("family") == family.family for r in records
        ):
            raise ValueError("Mixed family loss consumption count changed")
    return {
        "version": "mixed-native-loss-evidence-v1",
        "policy_hash": fingerprint(policy),
        "state": state.model_dump(mode="json"),
        "consumed": records,
        "entry_pauses": pauses,
        "execution_authority": False,
    }
