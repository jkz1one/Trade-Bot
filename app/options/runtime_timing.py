"""Bounded diagnostic spans; never market, account or execution authority."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import json
import sqlite3
import time


CURRENT = ContextVar("option_runtime_timing", default=None)
PHASES = {"SCAN", "STOCK_SCAN", "SCOPE_SCAN", "SCOPE_QUALITY", "ENTRY_MODEL",
          "ENTRY_MODEL_REQUEST", "ENTRY_MODEL_ADMISSION", "ENTRY_MODEL_SETTLEMENT",
          "ENTRY_MIXED_SELECTION", "ENTRY_SCOPE_RECEIPT_CHECK", "ENTRY_SCOPE_SELECTION", "ENTRY_OPTION_MARKET_READ",
          "ENTRY_PROTECTION_WAIT", "ENTRY_REVIEW",
          "STOCK_REFRESH", "SCOPE_REFRESH", "ADMISSION", "DISPATCH",
          "STOCK_ADMISSION", "STOCK_DISPATCH", "OPTION_MANAGEMENT_MODEL",
          "STOCK_MANAGEMENT_MODEL", "PORTFOLIO_MANAGEMENT_MODEL",
          "TICK_PACKET_VALIDATION", "TICK_NEW_RECEIPT", "TICK_REPEAT_RECEIPT", "TICK_QUOTE_FILLS",
          "CYCLE_OPPORTUNITY_CLAIM", "PROTECTION", "RECONCILE_COMMIT", "PROTECTION_POSITIONS", "PROTECTION_ASSESS",
          "PROTECTION_RESERVATION", "PROTECTION_HEARTBEAT", "NATIVE_SNAPSHOT", "NATIVE_ACCEPT", "DELIVERY_COMMIT",
          "NATIVE_ACCEPT_SPAWN", "NATIVE_SNAPSHOT_SPAWN"}
MAX_SPANS = 64


@contextmanager
def phase(name, *, quote=None, now=None, model_source_key=None, deadline=None):
    trace = CURRENT.get()
    if trace is None:
        yield
        return
    assert name in PHASES
    started, status = time.monotonic(), "COMPLETE"
    sample = {"phase": name}
    if deadline is not None:
        # The parent can observe a late wakeup even if the child ran on time.
        sample["remaining_at_start_seconds"] = round(deadline - started, 6)
    if model_source_key is not None:
        sample['model_source_key'] = model_source_key
    if quote is not None and now is not None:
        sample["quote_age_seconds"] = (now - quote.source_at).total_seconds()
        sample["receive_lag_seconds"] = (quote.received_at - quote.source_at).total_seconds()
        sample["local_age_seconds"] = (now - quote.received_at).total_seconds()
    try:
        yield
    except BaseException as exc:
        status = "INTERRUPTED" if isinstance(exc, asyncio.CancelledError) else "FAILED"
        raise
    finally:
        sample.update(status=status, elapsed_seconds=round(time.monotonic() - started, 6))
        if len(trace["spans"]) < MAX_SPANS:
            trace["spans"].append(sample)
        else:
            trace["spans_omitted"] += 1


def measured(name, *, quote_position=None):
    def original_quote(args, kwargs):
        if quote_position is None:
            return None
        return args[quote_position] if len(args) > quote_position else kwargs.get("quote")

    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                with phase(name, quote=original_quote(args, kwargs), now=kwargs.get("now")):
                    return await function(*args, **kwargs)
            return asynchronous
        @wraps(function)
        def synchronous(*args, **kwargs):
            with phase(name, quote=original_quote(args, kwargs), now=kwargs.get("now")):
                return function(*args, **kwargs)
        return synchronous
    return decorate


def bind_packet(packet, accepted_at, *, digest=None):
    trace = CURRENT.get()
    if trace is not None:
        from app.options.engine import fingerprint
        trace.update(packet_sequence=packet.sequence, packet_sha256=digest if digest is not None else fingerprint(packet),
                     packet_age_seconds=(accepted_at - packet.recorded_at).total_seconds())


def native_diagnostics(value):
    trace = CURRENT.get()
    if trace is not None:
        public = value.public()
        if public is not None:
            if len(trace['native']) < MAX_SPANS:
                trace["native"].append(public)
            else:
                trace['native_omitted'] = trace.get('native_omitted', 0) + 1


@contextmanager
def root(runtime, kind, *, slot=None, packet=None):
    """A cycle owns its own context even when spawned inside a protection tick."""
    journal = runtime.c.engine.journal
    at = runtime.c.now()
    started = time.monotonic()
    value = {"version": "runtime-timing-v1", "kind": kind, "slot": slot,
             "packet_sequence": None, "packet_sha256": None, "spans": [], "native": [],
             "spans_omitted": 0, "native_omitted": 0, "status": "RUNNING"}
    if kind == 'TICK' and getattr(runtime, '_scheduler_delay', None) is not None:
        value['scheduler_delay_seconds'] = runtime._scheduler_delay
    row_id = None
    try:
        with journal.write() as db:
            row = runtime._bound(db)
            value["generation"] = row["generation"]
            db.execute("CREATE TABLE IF NOT EXISTS execution_runtime_timings("
                       "id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,payload_json TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS runtime_timings_started ON execution_runtime_timings(started_at)")
            row_id = db.execute("INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)",
                                (at.isoformat(), json.dumps(value))).lastrowid
    except (OSError, sqlite3.Error):
        # Diagnostics must not stop valid protection. Missing rows remain unmeasured.
        pass
    value["trace_start_write_seconds"] = round(time.monotonic() - started, 6)
    token = CURRENT.set(value)
    if packet is not None:
        bind_packet(packet, at)
    try:
        yield
        value["status"] = "COMPLETE"
    except BaseException as exc:
        value["status"] = "INTERRUPTED" if isinstance(exc, asyncio.CancelledError) else "FAILED"
        raise
    finally:
        CURRENT.reset(token)
        value["elapsed_seconds"] = round(time.monotonic() - started, 6)
        if row_id is not None:
            try:
                with journal.write() as db:
                    db.execute("UPDATE execution_runtime_timings SET payload_json=? WHERE id=?",
                               (json.dumps(value, sort_keys=True), row_id))
            except (OSError, sqlite3.Error):
                pass  # The unfinished RUNNING record is explicit missing evidence.
