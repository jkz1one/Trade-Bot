"""Exact strategy identity from stored selected candidates, never thesis/contract inference."""

import json

from app.options.engine import fingerprint
from app.options.lifecycle import EntryLineage, OptionIntent
from app.options.selection import SwingCandidate, parse_candidate


def selected_lineage(db, source_key, instrument):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_option_opportunities'"
    ).fetchone():
        return None
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (source_key,)
    ).fetchone()
    if row is None:
        return None
    # Keep the same record bound used by stored attribution/observer reads.
    from app.options.observer import _json

    data = _json(row[0])
    planned = data.get("entry_result", {}).get("plan", {}).get("candidate_id")
    selected = data.get("candidate_id")
    if planned and selected and planned != selected:
        raise ValueError("ENTRY_LINEAGE_SELECTION_CONFLICT")
    selected = planned or selected
    candidates = data.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) > 100:
        raise ValueError("ENTRY_LINEAGE_CANDIDATE_CAPACITY")
    matches = [parse_candidate(c) for c in candidates if c["candidate_id"] == selected]
    if (
        not selected
        or len(matches) != 1
        or matches[0].instrument != instrument
        or matches[0].proposal.contract != instrument.contract
        or matches[0].admission.contract_id != instrument.contract.contract_id
        or matches[0].admission.outcome != "APPROVED"
    ):
        raise ValueError("ENTRY_LINEAGE_SELECTED_CANDIDATE_REQUIRED")
    candidate = matches[0]
    return EntryLineage(
        family="SWING" if isinstance(candidate, SwingCandidate) else "DEGEN",
        setup=candidate.family,
        opportunity_key=source_key,
        candidate_id=candidate.candidate_id,
        candidate_hash=fingerprint(candidate),
    )


def verified_lineage(db, intent, approval):
    """Validate a frozen buy label. Historical unlabeled intents stay unlabeled."""
    lineage = intent.entry_lineage
    if lineage is None and "entry_lineage" not in approval:
        return None
    if (
        lineage is None
        or approval.get("entry_lineage") != lineage.model_dump(mode="json")
        or selected_lineage(db, intent.source_key, intent.instrument) != lineage
    ):
        raise ValueError("ENTRY_LINEAGE_CHANGED")
    return lineage


def entry_lineage(db, entry_client_id):
    row = db.execute(
        "SELECT * FROM execution_orders WHERE client_id=?", (entry_client_id,)
    ).fetchone()
    if row is None:
        raise ValueError("ENTRY_LINEAGE_BUY_REQUIRED")
    intent = OptionIntent.model_validate_json(row["intent_json"])
    if (
        intent.side != "BUY"
        or intent.client_id != row["client_id"]
        or intent.source_key != row["source_key"]
    ):
        raise ValueError("ENTRY_LINEAGE_BUY_IDENTITY_CHANGED")
    return verified_lineage(db, intent, json.loads(row["approval_json"]))
