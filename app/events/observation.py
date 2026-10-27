"""Read-only native decision linkage; advisory audit writes are off the trading path."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from urllib.parse import quote

from pydantic import ValidationError

from app.events.assessment import assess, prepare
from app.events.models import Request
from app.events.option_volatility import prepare_option_volatility, review_option_volatility
from app.mixed.dashboard_snapshot import VERSION, checkpoint, file_identity
from app.options.engine import fingerprint
from app.options.models import OptionQuote

TABLES = {
    "OPTION": ("execution_option_decisions", "OPTION_PROPOSAL_RECORDED"),
    "STOCK": ("execution_stock_decisions", "STOCK_PROPOSAL_RECORDED"),
    "PORTFOLIO": ("execution_portfolio_decisions", "PORTFOLIO_PROPOSAL_RECORDED"),
}
ORDER_TABLES = {
    "OPTION": "execution_orders",
    "STOCK": "execution_stock_orders",
    "PORTFOLIO": "execution_portfolio_orders",
}


class ObservationUnavailable(ValueError):
    """An allowlisted diagnostic code, without private exception payloads."""

    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


@contextmanager
def native_snapshot(journal_path, snapshot_binding, population_id, recorded_at):
    """One immutable published inode; refuse active paths before opening SQLite."""
    path = Path(journal_path).resolve()
    if (
        path != Path(snapshot_binding["destination"]) / "options.db"
        or path == Path(snapshot_binding["source_journal"])
        or snapshot_binding["population_id"] != population_id
    ):
        raise ObservationUnavailable(
            "NATIVE_PUBLISHED_COPY_REQUIRED",
            "Published native snapshot required; active journal forbidden",
        )
    identity = file_identity(path, snapshot_binding["reader_uid"], snapshot_binding["reader_gid"])
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
        ):
            raise ObservationUnavailable("NATIVE_SNAPSHOT_RECEIPT_MISMATCH")
        if datetime.fromisoformat(receipt["published_at"]) > recorded_at:
            raise ObservationUnavailable("NATIVE_PUBLICATION_IN_FUTURE")
        config = json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        if config.get("limits", {}).get("population_id") != population_id:
            raise ObservationUnavailable("NATIVE_POPULATION_MISMATCH")
        yield db, receipt
        if (
            file_identity(path, snapshot_binding["reader_uid"], snapshot_binding["reader_gid"])
            != identity
        ):
            raise ObservationUnavailable("NATIVE_SNAPSHOT_REPLACED_DURING_READ")
    finally:
        db.close()


def decision_evidence(db, kind, decision_id):
    table, event_kind = TABLES[kind]
    row = db.execute(f"SELECT * FROM {table} WHERE source_key=?", (decision_id,)).fetchone()
    events = db.execute(
        "SELECT sequence,occurred_at,payload FROM execution_events WHERE kind=? "
        "AND json_extract(payload,'$.source_key')=? ORDER BY sequence LIMIT 2",
        (event_kind, decision_id),
    ).fetchall()
    if row is None or len(events) != 1:
        raise ValueError("Unique actual native decision and event required")
    native, native_event = dict(row), dict(events[0])
    inputs = json.loads(native.get("inputs_json", "{}"))
    order = db.execute(
        f"SELECT intent_json,approval_json FROM {ORDER_TABLES[kind]} WHERE source_key=?",
        (decision_id,),
    ).fetchone()
    intent = json.loads(order[0]) if order else {}
    if order and kind == "PORTFOLIO":
        inputs = json.loads(order[1]).get("inputs", {})
    return native, native_event, inputs, intent


def native_context(evidence, population_id):
    """Use only retained native fields. No family, instrument or horizon guesses."""
    native, event, inputs, intent = evidence
    instrument = intent.get("instrument") or (inputs.get("quote") or {}).get("instrument")
    proposal = inputs.get("proposal") or {}
    family = intent.get("family") or (intent.get("entry_lineage") or {}).get("family")
    family = family or proposal.get("family")
    horizon = intent.get("exit_at") or proposal.get("exit_at")
    if not (instrument and family and horizon):
        return None
    contract = instrument.get("contract")
    return Request(
        population_id=population_id,
        decision_id=native["source_key"],
        family=family,
        symbol=contract["underlying"] if contract else instrument["symbol"],
        instrument_id=instrument["instrument_id"],
        underlying_kind=contract["underlying_kind"] if contract else instrument["kind"],
        evaluated_at=datetime.fromisoformat(event["occurred_at"]),
        holding_until=datetime.fromisoformat(horizon),
    )


def observation_payload(store, kind, request, evidence, receipt, *, recorded_at, context_origin):
    native, native_event, inputs, intent = evidence
    if request.population_id != store.binding["population_id"]:
        raise ValueError("Native decision population mismatch")
    if recorded_at < request.evaluated_at:
        raise ValueError("Observation receipt predates native decision")
    if (
        native["source_key"] != request.decision_id
        or datetime.fromisoformat(native_event["occurred_at"]) != request.evaluated_at
    ):
        raise ValueError("Original native decision identity/time required")
    instrument = intent.get("instrument") or (inputs.get("quote") or {}).get("instrument")
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
    proposal = inputs.get("proposal") or {}
    family = intent.get("family") or (intent.get("entry_lineage") or {}).get("family")
    family = family or proposal.get("family")
    horizon = intent.get("exit_at") or proposal.get("exit_at")
    if (family and family != request.family) or (
        horizon and datetime.fromisoformat(horizon) != request.holding_until
    ):
        raise ValueError("Native family or holding horizon context mismatch")
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
        "decision_table": TABLES[kind][0],
        "decision_id": request.decision_id,
        "native_decision_hash": fingerprint(native),
        "native_event": native_event,
        "native_publication": receipt,
        "native_result": json.loads(native["result_json"]),
        "context_origin": context_origin,
        "native_instrument_verified": bool(instrument),
        "recorded_at": recorded_at.isoformat(),
        "assessment": assessment.model_dump(mode="json"),
        "local_check_ms": elapsed_ms,
        "detection_delays": delays,
        "actual_decision_changed": False,
    }
    if kind == "OPTION" or (instrument and instrument.get("contract")):
        raw_quote = inputs.get("quote")
        try:
            option_quote = OptionQuote.model_validate(raw_quote) if raw_quote else None
        except ValidationError:
            option_quote = None
        if (
            option_quote is not None
            and instrument
            and option_quote.instrument.model_dump(mode="json") != instrument
        ):
            option_quote = None
        # Separate background preparation/measurement and policy identity. Native
        # decisions and the existing event assessment are never rewritten.
        volatility_view = prepare_option_volatility(view)
        start = perf_counter_ns()
        diagnostic = review_option_volatility(volatility_view, request, option_quote)
        payload["option_volatility_local_check_ms"] = (perf_counter_ns() - start) / 1_000_000
        payload["option_event_volatility"] = diagnostic | {
            "policy": volatility_view.policy.model_dump(mode="json"),
            "snapshot_hash": view.snapshot_hash,
            "snapshot_sequence": snapshot.sequence if snapshot else None,
            "base_policy_hash": view.policy_hash,
            "native_quote_hash": fingerprint(raw_quote) if raw_quote else None,
            "native_quote": raw_quote,
        }
    return payload, assessment


def observe_decision(store, journal_path, kind, request, *, recorded_at, snapshot_binding):
    """Single decision API; the bounded consumer supplies durable delivery/checkpoints."""
    if kind not in TABLES:
        raise ValueError("Native decision kind mismatch")
    with native_snapshot(
        journal_path, snapshot_binding, store.binding["population_id"], recorded_at
    ) as (db, receipt):
        evidence = decision_evidence(db, kind, request.decision_id)
        payload, assessment = observation_payload(
            store,
            kind,
            request,
            evidence,
            receipt,
            recorded_at=recorded_at,
            context_origin="EXPLICIT_CALLER_CANDIDATE_AND_HORIZON",
        )
    return store.observe(payload), assessment
