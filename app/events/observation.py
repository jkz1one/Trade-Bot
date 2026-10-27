"""Read-only native decision linkage; advisory audit writes are off the trading path."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from urllib.parse import quote

from app.events.assessment import assess, prepare
from app.mixed.dashboard_snapshot import VERSION, checkpoint, file_identity
from app.options.engine import fingerprint

TABLES = {
    "OPTION": ("execution_option_decisions", "OPTION_PROPOSAL_RECORDED"),
    "STOCK": ("execution_stock_decisions", "STOCK_PROPOSAL_RECORDED"),
    "PORTFOLIO": ("execution_portfolio_decisions", "PORTFOLIO_PROPOSAL_RECORDED"),
}


def observe_decision(store, journal_path, kind, request, *, recorded_at, snapshot_binding):
    """Link to an existing immutable source_key and its original native event clock.

    The caller supplies candidate/family/horizon context (explicitly labelled).
    No lookahead: use only a snapshot published by the actual decision time.
    Only the existing publisher's atomic copy is accepted, never the active owner.
    Event consumers cannot hold SQLite read locks against mandatory protection.
    """
    if kind not in TABLES or request.population_id != store.binding["population_id"]:
        raise ValueError("Native decision kind/population mismatch")
    if recorded_at < request.evaluated_at:
        raise ValueError("Observation receipt predates native decision")
    path = Path(journal_path).resolve()
    if (
        path != Path(snapshot_binding["destination"]) / "options.db"
        or path == Path(snapshot_binding["source_journal"])
        or snapshot_binding["population_id"] != request.population_id
    ):
        raise ValueError("Published native snapshot required; active journal forbidden")
    identity = file_identity(path, snapshot_binding["reader_uid"], snapshot_binding["reader_gid"])
    table, event_kind = TABLES[kind]
    # Atomic publisher copies never change in place. Immutable reads take no locks.
    uri = "file:" + quote(str(path)) + "?mode=ro&immutable=1"
    db = sqlite3.connect(uri, uri=True, timeout=0)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        receipt = json.loads(
            db.execute("SELECT payload FROM dashboard_snapshot WHERE id=1").fetchone()[0]
        )
        if (
            receipt["version"] != VERSION
            or receipt["binding_sha256"] != fingerprint(snapshot_binding)
            or receipt["checkpoint"] != checkpoint(db, snapshot_binding)
            or datetime.fromisoformat(receipt["published_at"]) > recorded_at
        ):
            raise ValueError("Native snapshot receipt mismatch")
        config = json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        if config.get("limits", {}).get("population_id") != request.population_id:
            raise ValueError("Native journal population mismatch")
        row = db.execute(
            f"SELECT * FROM {table} WHERE source_key=?", (request.decision_id,)
        ).fetchone()
        event = db.execute(
            "SELECT sequence,occurred_at,payload FROM execution_events WHERE kind=? "
            "AND json_extract(payload,'$.source_key')=? ORDER BY sequence LIMIT 1",
            (event_kind, request.decision_id),
        ).fetchone()
        if row is None or event is None:
            raise ValueError("Actual native decision and event required")
        if datetime.fromisoformat(event["occurred_at"]) != request.evaluated_at:
            raise ValueError("Original native decision time required")
        native = dict(row)
        native_event = dict(event)
        inputs = json.loads(native.get("inputs_json", "{}"))
        if kind == "PORTFOLIO":
            order = db.execute(
                "SELECT approval_json FROM execution_portfolio_orders WHERE source_key=?",
                (request.decision_id,),
            ).fetchone()
            if order:
                inputs = json.loads(order[0]).get("inputs", {})
        instrument = (inputs.get("quote") or {}).get("instrument")
        if instrument:
            contract = instrument.get("contract")
            symbol = contract["underlying"] if contract else instrument["symbol"]
            underlying_kind = contract["underlying_kind"] if contract else instrument["kind"]
            if (symbol, instrument["instrument_id"], underlying_kind) != (
                request.symbol,
                request.instrument_id,
                request.underlying_kind,
            ):
                raise ValueError("Native decision instrument context mismatch")
        if (
            file_identity(path, snapshot_binding["reader_uid"], snapshot_binding["reader_gid"])
            != identity
        ):
            raise ValueError("Native snapshot replaced during observation; retry off-path")
    finally:
        db.close()
    snapshot = store.as_of(request.evaluated_at)
    view = prepare(snapshot, store.policy)
    start = perf_counter_ns()
    assessment = assess(view, request)
    elapsed_ms = (perf_counter_ns() - start) / 1_000_000
    delays = []
    for e in snapshot.events if snapshot else ():
        if e.scope == "SYMBOL" and request.symbol not in e.symbols:
            continue
        windows = [
            w
            for w in store.policy.windows
            if e.category == w.category or e.category.startswith(w.category + ".")
        ]
        if not windows:
            continue
        w = max(windows, key=lambda v: len(v.category))
        activation = e.starts_at - timedelta(seconds=w.before_seconds)
        end = e.ends_at + timedelta(seconds=w.after_seconds)
        if activation <= request.evaluated_at < end and e.status != "CANCELLED":
            delays.append(
                {
                    "evidence_ref": e.evidence_ref,
                    "source_to_receipt_seconds": (e.received_at - e.source_at).total_seconds()
                    if e.source_at
                    else None,
                    "source_to_detection_seconds": (recorded_at - e.source_at).total_seconds()
                    if e.source_at
                    else None,
                    "scheduled_activation_to_decision_seconds": (
                        request.evaluated_at - activation
                    ).total_seconds(),
                    "decision_to_observation_seconds": (
                        recorded_at - request.evaluated_at
                    ).total_seconds(),
                }
            )
    payload = {
        "kind": "EVENT_OBSERVATION_ONLY",
        "population_id": request.population_id,
        "decision_table": table,
        "decision_id": request.decision_id,
        "native_decision_hash": fingerprint(native),
        "native_event": native_event,
        "native_publication": receipt,
        "native_result": json.loads(native["result_json"]),
        "context_origin": "EXPLICIT_CALLER_CANDIDATE_AND_HORIZON",
        "native_instrument_verified": bool(instrument),
        "recorded_at": recorded_at.isoformat(),
        "assessment": assessment.model_dump(mode="json"),
        "local_check_ms": elapsed_ms,
        "detection_delays": delays,
        "actual_decision_changed": False,
    }
    return store.observe(payload), assessment
