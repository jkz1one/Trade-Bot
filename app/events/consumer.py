"""Bounded, resumable observation of published native decisions. Run off-path only."""

import fcntl
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.events.models import Request
from app.events.observation import (
    TABLES,
    ObservationUnavailable,
    decision_evidence,
    native_context,
    native_snapshot,
    observation_payload,
)
from app.options.engine import clock, fingerprint
from app.options.models import OptionRecord

VERSION = "event-observer-v1"
KINDS = {event: kind for kind, (_, event) in TABLES.items()}


class SuppliedContext(OptionRecord):
    kind: Literal["OPTION", "STOCK", "PORTFOLIO"]
    request: Request


class ObserverBatch(OptionRecord):
    """Bounds apply to work per invocation, never to trading eligibility."""

    version: Literal["event-observer-v1"] = VERSION
    max_events: int = Field(default=100, strict=True, ge=1, le=1000)
    max_gap_retries: int = Field(default=25, strict=True, ge=0, le=1000)
    max_publication_age_seconds: int = Field(default=60, strict=True, ge=1, le=3600)
    contexts: tuple[SuppliedContext, ...] = Field(default=(), max_length=1000)


def initialize(store, binding):
    """Additive evidence-only schema; the native owner is never migrated."""
    with store.writer(), store.db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS observer_state(id INTEGER PRIMARY KEY, payload TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS observer_deliveries("
            "sequence INTEGER PRIMARY KEY, decision_key TEXT UNIQUE NOT NULL,"
            "status TEXT NOT NULL, attempt INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS observer_attempts(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS observer_gap_queue "
            "ON observer_deliveries(status,attempt,sequence)"
        )
        row = db.execute("SELECT payload FROM observer_state WHERE id=1").fetchone()
        if row:
            state = json.loads(row[0])
            if state["binding"] != binding:
                raise ValueError("Observer source/population/policy binding changed")
        else:
            state = {
                "binding": binding,
                "cursor": 0,
                "anchor_hash": None,
                "publication": None,
                "attempt": 0,
            }
            db.execute("INSERT INTO observer_state VALUES(1,?)", (json.dumps(state),))
        return state


def commit_batch(store, state, deliveries, observations, result):
    """Observation, delivery receipt and cursor are one transaction or none."""
    with store.writer(), store.db() as db:
        for payload in observations:
            db.execute(
                "INSERT OR IGNORE INTO observations VALUES(?,?)",
                (fingerprint(payload), json.dumps(payload, sort_keys=True)),
            )
        for item in deliveries:
            db.execute(
                "INSERT INTO observer_deliveries VALUES(?,?,?,?,?) "
                "ON CONFLICT(sequence) DO UPDATE SET status=excluded.status,"
                "attempt=excluded.attempt,payload=excluded.payload",
                (
                    item["sequence"],
                    item["decision_key"],
                    item["status"],
                    state["attempt"],
                    json.dumps(item, sort_keys=True),
                ),
            )
        db.execute("UPDATE observer_state SET payload=? WHERE id=1", (json.dumps(state),))
        result["unresolved_gaps"] = db.execute(
            "SELECT count(*) FROM observer_deliveries WHERE status='GAP'"
        ).fetchone()[0]
        if result["status"] == "CAUGHT_UP" and result["unresolved_gaps"]:
            result["status"] = "CAUGHT_UP_WITH_GAPS"
        result["committed"] = True
        result["delivery_outcomes"] = deliveries
        db.execute("INSERT INTO observer_attempts(payload) VALUES(?)", (json.dumps(result),))


def delivery(store, db, receipt, event, contexts, recorded_at):
    kind = KINDS[event["kind"]]
    key = json.loads(event["payload"])["source_key"]
    item = {
        "sequence": event["sequence"],
        "decision_key": fingerprint((kind, key)),
        "decision_id": key,
        "decision_kind": kind,
        "native_event_hash": fingerprint(event),
        "native_event": event,
        "status": "GAP",
        "recorded_at": recorded_at.isoformat(),
        "reason": "NATIVE_DECISION_EVIDENCE_UNAVAILABLE",
        "observation_digest": None,
    }
    try:
        evidence = decision_evidence(db, kind, key)
        if evidence[1]["sequence"] != event["sequence"]:
            raise ValueError("Native decision event changed")
    except (ValueError, KeyError, TypeError, sqlite3.Error):
        return item, None
    explicit = contexts.get((kind, key))
    try:
        request = explicit or native_context(evidence, store.binding["population_id"])
        if request is None:
            item["reason"] = "MISSING_CANDIDATE_FAMILY_OR_HOLDING_CONTEXT"
            return item, None
        payload, _ = observation_payload(
            store,
            kind,
            request,
            evidence,
            receipt,
            recorded_at=recorded_at,
            context_origin="EXPLICIT_CALLER_CANDIDATE_AND_HORIZON"
            if explicit
            else "RETAINED_NATIVE_DECISION_CONTEXT",
        )
    except (ValueError, KeyError, TypeError):
        item["reason"] = "CONTEXT_CONFLICT_OR_INVALID"
        return item, None
    item.update(status="OBSERVED", reason=None, observation_digest=fingerprint(payload))
    return item, payload


def consume_once(store, snapshot_binding, *, recorded_at, batch=None):
    """Read a bounded batch from the publisher's copy and atomically record progress.

    No scheduler, polling sleep, owner connection, provider, model or enforcement.
    Restart reuses durable progress. Missing context is a retained retryable gap.
    """
    recorded_at = clock(recorded_at)
    batch = ObserverBatch.model_validate((batch or ObserverBatch()).model_dump())
    contexts = {(c.kind, c.request.decision_id): c.request for c in batch.contexts}
    if len(contexts) != len(batch.contexts) or any(
        r.population_id != store.binding["population_id"] for r in contexts.values()
    ):
        raise ValueError("Unique contexts for the bound population required")
    binding = {
        "version": VERSION,
        "snapshot_binding": snapshot_binding,
        "event_binding_hash": fingerprint(store.binding),
    }
    fd = os.open(store.directory / "observer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = initialize(store, binding)
        return run_batch(store, state, contexts, batch, recorded_at)
    finally:
        os.close(fd)


def run_batch(store, state, contexts, batch, recorded_at):
    binding = state["binding"]["snapshot_binding"]
    result = {
        "kind": "EVENT_OBSERVER_BATCH",
        "version": VERSION,
        "recorded_at": recorded_at.isoformat(),
        "cursor_before": state["cursor"],
        "cursor_after": state["cursor"],
        "events_scanned": 0,
        "observed": 0,
        "gap_retries": 0,
        "pending_native_events": None,
        "authority": False,
        "actual_decisions_changed": False,
        "committed": False,
        "batch": batch.model_dump(mode="json"),
    }
    try:
        observations, deliveries = [], []
        with native_snapshot(
            Path(binding["destination"]) / "options.db",
            binding,
            store.binding["population_id"],
            recorded_at,
        ) as (native, receipt):
            age = (recorded_at - datetime.fromisoformat(receipt["published_at"])).total_seconds()
            result.update(native_publication=receipt, publication_age_seconds=age)
            if age > batch.max_publication_age_seconds:
                raise ObservationUnavailable("STALE_NATIVE_PUBLICATION")
            previous = state["publication"]
            if previous and (
                datetime.fromisoformat(receipt["published_at"])
                < datetime.fromisoformat(previous["published_at"])
                or any(receipt["checkpoint"][k] < v for k, v in previous["checkpoint"].items())
            ):
                raise ObservationUnavailable("NATIVE_PUBLICATION_REGRESSED")
            if state["cursor"]:
                anchor = native.execute(
                    "SELECT * FROM execution_events WHERE sequence=?", (state["cursor"],)
                ).fetchone()
                if anchor is None or fingerprint(dict(anchor)) != state["anchor_hash"]:
                    raise ObservationUnavailable("NATIVE_CURSOR_ANCHOR_CHANGED")
            rows = [
                dict(r)
                for r in native.execute(
                    "SELECT * FROM execution_events WHERE sequence>? ORDER BY sequence LIMIT ?",
                    (state["cursor"], batch.max_events),
                )
            ]
            cursor = state["cursor"]
            for event in rows:
                if event["sequence"] != cursor + 1:
                    raise ObservationUnavailable("NATIVE_EVENT_SEQUENCE_GAP")
                cursor = event["sequence"]
                if event["kind"] in KINDS:
                    item, payload = delivery(store, native, receipt, event, contexts, recorded_at)
                    deliveries.append(item)
                    if payload:
                        observations.append(payload)
            if not rows and receipt["checkpoint"]["owner_revision"] != cursor:
                raise ObservationUnavailable("NATIVE_CHECKPOINT_MISSING_EVENTS")
            with store.db() as db:
                gaps = [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT payload FROM observer_deliveries WHERE status='GAP' "
                        "ORDER BY attempt,sequence LIMIT ?",
                        (batch.max_gap_retries,),
                    )
                ]
            for gap in gaps:
                event = native.execute(
                    "SELECT * FROM execution_events WHERE sequence=?", (gap["sequence"],)
                ).fetchone()
                if event is None or fingerprint(dict(event)) != gap["native_event_hash"]:
                    raise ObservationUnavailable("NATIVE_GAP_EVIDENCE_CHANGED")
                item, payload = delivery(store, native, receipt, dict(event), contexts, recorded_at)
                deliveries.append(item)
                if payload:
                    observations.append(payload)
            new_state = state | {
                "cursor": cursor,
                "anchor_hash": fingerprint(rows[-1]) if rows else state["anchor_hash"],
                "publication": receipt,
                "attempt": state["attempt"] + 1,
            }
            result.update(
                status="BACKLOG"
                if cursor < receipt["checkpoint"]["owner_revision"]
                else "CAUGHT_UP",
                cursor_after=cursor,
                events_scanned=len(rows),
                observed=len(observations),
                gap_retries=len(gaps),
                pending_native_events=receipt["checkpoint"]["owner_revision"] - cursor,
                publication_age_seconds=age,
                native_publication=receipt,
            )
        # Only commit after the immutable snapshot's final identity check succeeds.
        commit_batch(store, new_state, deliveries, observations, result)
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError, sqlite3.Error) as exc:
        publication = result.get("native_publication")
        pending = (
            publication["checkpoint"]["owner_revision"] - state["cursor"] if publication else None
        )
        result.update(
            status="UNAVAILABLE",
            cursor_after=state["cursor"],
            observed=0,
            reason=exc.code
            if isinstance(exc, ObservationUnavailable)
            else "NATIVE_OBSERVATION_BATCH_UNAVAILABLE",
            error_type=type(exc).__name__,
            committed=False,
            delivery_outcomes=[],
            unresolved_gaps=None,
            pending_native_events=pending if pending is not None and pending >= 0 else None,
        )
        # A failed transaction cannot advance the cursor or leave partial observations.
        # If the audit itself is unavailable, propagate; never claim a retained failure.
        with store.writer(), store.db() as db:
            db.execute("INSERT INTO observer_attempts(payload) VALUES(?)", (json.dumps(result),))
        return result


def observer_export(db):
    """Read inside the event export's consistent transaction; old audits remain readable."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='observer_state'").fetchone():
        return None
    row = db.execute("SELECT payload FROM observer_state WHERE id=1").fetchone()
    return {
        "state": json.loads(row[0]) if row else None,
        "deliveries": [
            json.loads(r[0])
            for r in db.execute("SELECT payload FROM observer_deliveries ORDER BY sequence")
        ],
        "attempts": [
            json.loads(r[0])
            for r in db.execute("SELECT payload FROM observer_attempts ORDER BY id")
        ],
    }
