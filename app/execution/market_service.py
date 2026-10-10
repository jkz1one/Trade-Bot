"""Explicit continuous market-only collection, owned by the isolated PAPER runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from uuid import uuid4

from pydantic import Field

from app.domain.models import utc_now
from app.execution import market_reads, restore
from app.execution.engine import ExecutionBlocked, ExecutionEngine, _clock
from app.execution.market_reads import MarketReadPolicy, market_read_lease, source_hash
from app.execution.models import Contract, Ledger
from app.execution.quote_feed import DurableQuoteFeed


class MarketServiceLimits(Contract):
    poll_seconds: float = Field(default=5, ge=0.01, le=30)
    max_age_seconds: float = Field(default=45, gt=0, le=90)


class PaperMarketService:
    def __init__(self, engine, feed, *, limits=None, clock=utc_now):
        if (
            type(engine) is not ExecutionEngine
            or type(feed) is not DurableQuoteFeed
            or feed.source is None
        ):
            raise ValueError("Built-in isolated PAPER engine and sourced feed required")
        self.engine, self.feed, self.clock = engine, feed, clock
        self.source = MarketReadPolicy.model_validate(feed.source)
        self.limits = MarketServiceLimits.model_validate(
            (limits or MarketServiceLimits()).model_dump()
        )
        if (
            self.limits.poll_seconds + self.source.timeout_seconds + 2 > self.limits.max_age_seconds
            or self.limits.max_age_seconds
            > min(self.source.max_age_seconds, engine.settings.quote_max_age_seconds)
            or feed.symbols != engine.settings.initial_symbols
        ):
            raise ValueError("Market cadence/read deadline must fit frozen freshness and universe")
        _clock(clock())
        self.owner = None

    def _policy(self):
        return {
            "policy": "continuous-paper-market-v1",
            "limits": self.limits.model_dump(mode="json"),
            "feed_id": self.feed.feed_id,
            "feed_path": str(self.feed.path),
            "source_hash": source_hash(self.source),
            "symbols": self.feed.symbols,
            "read_timeout_seconds": self.source.timeout_seconds,
            "quote_max_age_seconds": self.engine.settings.quote_max_age_seconds,
            "calendar": "XNYS-regular-flat-idle",
        }

    def enroll(self):
        now = self.clock()
        _clock(now)
        with self.engine.journal.read() as db:
            if (
                restore.status(db, restore.authority_path(self.engine.journal.path))["status"]
                != "VERIFIED"
            ):
                raise ValueError("Verified paired execution authority required")
        with self.engine.journal.write() as db:
            self.engine._control(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_market_service(id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL,status TEXT NOT NULL,owner TEXT,generation INTEGER NOT NULL,heartbeat_at TEXT,last_success_at TEXT,oldest_quote_at TEXT,feed_sequence INTEGER,feed_hash TEXT,attempt_started_at TEXT,error_class TEXT)"
            )
            policy = json.dumps(self._policy(), sort_keys=True)
            row = db.execute(
                "SELECT policy_json FROM execution_market_service WHERE id=1"
            ).fetchone()
            if row:
                if row[0] != policy:
                    raise ValueError("Market service policy is immutable")
            else:
                if db.execute(
                    "SELECT 1 FROM execution_orders UNION ALL SELECT 1 FROM execution_model_calls LIMIT 1"
                ).fetchone():
                    raise ValueError("Market service enrollment must precede orders/model attempts")
                db.execute(
                    "INSERT INTO execution_market_service(id,policy_json,status,generation) VALUES(1,?,'STOPPED',0)",
                    (policy,),
                )
                self.engine.journal.event(db, now, "MARKET_SERVICE_ENROLLED", self._policy())

    def _state(self, db):
        self.engine._control(db)
        row = db.execute("SELECT * FROM execution_market_service WHERE id=1").fetchone()
        if (
            row is None
            or row["policy_json"] != json.dumps(self._policy(), sort_keys=True)
            or source_hash(MarketReadPolicy.model_validate(self.feed.source))
            != source_hash(self.source)
        ):
            raise ExecutionBlocked("MARKET_SERVICE_CONFIGURATION_CHANGED")
        if self.owner is not None and row["owner"] != self.owner:
            raise ExecutionBlocked("MARKET_SERVICE_OWNER_CHANGED")
        return row

    def _claim(self):
        now = self.clock()
        _clock(now)
        with self.engine.journal.write() as db:
            row = self._state(db)
            if row["status"] in {"RUNNING", "COLLECTING", "IDLE", "STOPPING"}:
                self.engine._halt(db, "INTERRUPTED_MARKET_SERVICE", now)
            self.owner = uuid4().hex
            db.execute(
                "UPDATE execution_market_service SET status='COLLECTING',owner=?,generation=generation+1,heartbeat_at=?,last_success_at=NULL,oldest_quote_at=NULL,feed_sequence=NULL,feed_hash=NULL,attempt_started_at=NULL,error_class=NULL WHERE id=1",
                (self.owner, now.isoformat()),
            )
            self.engine.journal.event(
                db, now, "MARKET_SERVICE_STARTED", {"generation": row["generation"] + 1}
            )

    def revoke(self):
        if self.owner is not None:
            self._publish("STOPPING")

    def _publish(self, status, *, sample=None, error=None):
        now = self.clock()
        _clock(now)
        with self.engine.journal.write() as db:
            if status in {"FAILED", "STOPPING", "STOPPED"}:
                row = db.execute("SELECT * FROM execution_market_service WHERE id=1").fetchone()
                if row is None or row["owner"] != self.owner:
                    raise ExecutionBlocked("MARKET_SERVICE_OWNER_CHANGED")
            else:
                row = self._state(db)
                if row["heartbeat_at"] and now < datetime.fromisoformat(row["heartbeat_at"]):
                    raise ExecutionBlocked("MARKET_SERVICE_TIME_REGRESSION")
            if row["status"] == "STOPPING" and status in {"RUNNING", "COLLECTING", "IDLE"}:
                status, sample = "STOPPING", None
            if status == "FAILED":
                self.engine._halt(db, "MARKET_SERVICE_FAILED", now)
            db.execute(
                "UPDATE execution_market_service SET status=?,heartbeat_at=?,attempt_started_at=?,error_class=? WHERE id=1",
                (
                    status,
                    now.isoformat(),
                    now.isoformat() if status == "COLLECTING" else None,
                    error,
                ),
            )
            if sample is not None:
                sequence, packet = sample
                oldest = min(c.quote.timestamp for c in packet.candidates)
                if (
                    not 0
                    <= (now - oldest).total_seconds()
                    <= self.engine.settings.quote_max_age_seconds
                ):
                    raise ExecutionBlocked("MARKET_SERVICE_COMPLETION_NOT_FRESH")
                digest = hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
                db.execute(
                    "UPDATE execution_market_service SET last_success_at=?,oldest_quote_at=?,feed_sequence=?,feed_hash=? WHERE id=1",
                    (now.isoformat(), oldest.isoformat(), sequence, digest),
                )
                self.engine.journal.event(
                    db,
                    now,
                    "MARKET_SAMPLE_PUBLISHED",
                    {
                        "feed_sequence": sequence,
                        "feed_hash": digest,
                        "source_hash": source_hash(self.source),
                    },
                )
            elif status != row["status"] or error:
                self.engine.journal.event(
                    db, now, "MARKET_SERVICE_STATE", {"status": status, "error_class": error}
                )

    def _idle(self):
        now = self.clock()
        _clock(now)
        with self.engine.journal.read() as db:
            control = self.engine._control(db)
            return (
                self.engine.calendar.current_window(now) is None
                and Ledger.model_validate_json(control["ledger_json"]).position is None
                and db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone()
                is None
            )

    async def run(self, stop):
        with market_read_lease(self.feed.path):
            self._claim()
            try:
                while not stop.is_set():
                    if self._idle():
                        self._publish("IDLE")
                    else:
                        self._publish("COLLECTING")
                        await market_reads._collect_owned(self.feed, clock=self.clock)
                        if stop.is_set():
                            break
                        self._publish("RUNNING", sample=self.feed.latest())
                    try:
                        await asyncio.wait_for(stop.wait(), self.limits.poll_seconds)
                    except TimeoutError:
                        pass
                return 0
            except asyncio.CancelledError:
                self.revoke()
                raise
            except Exception as exc:  # noqa: BLE001 -- only sanitized failure class is persisted
                self._publish("FAILED", error=type(exc).__name__)
                return 1
            finally:
                with self.engine.journal.read() as db:
                    row = db.execute(
                        "SELECT status,owner FROM execution_market_service WHERE id=1"
                    ).fetchone()
                if row["status"] != "FAILED" and row["owner"] == self.owner:
                    self._publish("STOPPED")
                self.owner = None
