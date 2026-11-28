"""Exact strategy identity from stored selected candidates, never thesis/contract inference."""

import json
from contextvars import ContextVar
from functools import wraps

from app.options.engine import fingerprint
from app.options.lifecycle import EntryLineage, OptionIntent
from app.options.selection import SwingCandidate, parse_candidate

_OUTCOME_SNAPSHOT = ContextVar("option_outcome_lineage_snapshot", default=None)


def outcome_snapshot(function):
    """Reuse exact lineage validation only inside one synchronous outcome read."""

    @wraps(function)
    def wrapped(db, *args, **kwargs):
        value = (db, db.total_changes, {}) if db.in_transaction else None
        token = _OUTCOME_SNAPSHOT.set(value)
        try:
            return function(db, *args, **kwargs)
        finally:
            _OUTCOME_SNAPSHOT.reset(token)

    return wrapped


def _snapshot_key(db, intent, approval):
    snapshot = _OUTCOME_SNAPSHOT.get()
    if (
        snapshot is None
        or snapshot[0] is not db
        or not db.in_transaction
        or snapshot[1] != db.total_changes
        or type(intent) is not OptionIntent
        or type(approval) is not dict
    ):
        return None
    # Exact serialized arguments, not only the order ID. The caller's existing
    # transaction binds all database reads; any write disables reuse immediately.
    return snapshot[2], (intent.model_dump_json(), json.dumps(approval, sort_keys=True))


def selected_lineage(db, source_key, instrument):
    from app.options.scope_execution import lineage, stored_entry

    scope = stored_entry(db, source_key)
    if scope is not None:
        if scope["packet"]["instrument"] != instrument.model_dump(mode="json"):
            raise ValueError("SCOPE_NATIVE_INSTRUMENT_CHANGED")
        return lineage(scope["packet"])
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
    cached = _snapshot_key(db, intent, approval)
    if cached is not None and cached[1] in cached[0]:
        return cached[0][cached[1]]
    result = _verified_lineage(db, intent, approval)
    if cached is not None and _snapshot_key(db, intent, approval) is not None:
        cached[0][cached[1]] = result
    return result


def _verified_lineage(db, intent, approval):
    from app.options.scope_arbitration import verify_entry
    from app.options.scope_execution import verify_native_intent
    from app.options.swing_execution import verify_binding

    verify_entry(db, intent, approval)
    verify_binding(db, intent, approval)
    if intent.side == "BUY":
        verify_native_intent(db, intent, approval)
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
