"""Independent fixture-only sampled supervision. It never dispatches a BUY."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import Field, model_validator

from app.domain.models import utc_now
from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.engine import ExecutionBlocked, ExecutionEngine, _clock
from app.execution.models import Contract, Ledger, Snapshot
from app.execution.quote_feed import DurableQuoteFeed


class SupervisorLimits(Contract):
    poll_seconds: float = Field(default=5, gt=0, le=30)
    tick_timeout_seconds: float = Field(default=10, gt=0, le=30)
    max_age_seconds: float = Field(default=20, gt=0, le=90)

    @model_validator(mode="after")
    def bounded(self):
        if self.poll_seconds + self.tick_timeout_seconds > self.max_age_seconds:
            raise ValueError("A complete supervision tick and poll must fit the freshness lease")
        return self


class SupervisorAlreadyRunning(RuntimeError):
    pass


class ExecutionSupervisor:
    def __init__(self, engine, venue, feed, *, limits=None, clock=utc_now):
        if (
            type(engine) is not ExecutionEngine
            or type(venue) is not DurableFixtureVenue
            or type(feed) is not DurableQuoteFeed
        ):
            raise ValueError("Only built-in fixture engine/venue/quotes are supported")
        self.engine, self.venue, self.feed, self.clock = engine, venue, feed, clock
        _clock(self.clock())
        self.limits = SupervisorLimits.model_validate((limits or SupervisorLimits()).model_dump())
        if (
            self.limits.max_age_seconds > engine.settings.quote_max_age_seconds
            or feed.symbols != engine.settings.initial_symbols
        ):
            raise ValueError("Supervisor freshness/universe exceeds frozen engine authority")
        with engine.journal.write() as db:
            engine._control(db)
            frozen = json.dumps(self._policy(), sort_keys=True)
            row = db.execute("SELECT policy_json FROM execution_supervisor WHERE id=1").fetchone()
            if row:
                if row[0] != frozen:
                    raise ValueError("Supervisor policy is immutable")
            else:
                if db.execute("SELECT 1 FROM execution_orders").fetchone():
                    raise ValueError("Supervisor enrollment must precede order preparation")
                db.execute(
                    "INSERT INTO execution_supervisor(id,policy_json,status,generation) VALUES(1,?,'STOPPED',0)",
                    (frozen,),
                )
                engine.journal.event(db, self.clock(), "SUPERVISOR_ENROLLED", self._policy())
        self.owner = None

    def _policy(self):
        return {
            "policy": "fixture-independent-supervisor-v1",
            "limits": self.limits.model_dump(mode="json"),
            "venue_id": self.venue.venue_id,
            "account_id": self.venue.account_id,
            "venue_path": str(self.venue.path),
            "feed_id": self.feed.feed_id,
            "feed_path": str(self.feed.path),
            "symbols": self.feed.symbols,
            **(
                {
                    "feed_source_hash": hashlib.sha256(
                        json.dumps(self.feed.source, sort_keys=True).encode()
                    ).hexdigest()
                }
                if self.feed.source is not None
                else {}
            ),
        }

    def _state(self, db):
        self.engine._control(db)
        row = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
        if row is None or row["policy_json"] != json.dumps(self._policy(), sort_keys=True):
            raise ExecutionBlocked("SUPERVISOR_CONFIGURATION_CHANGED")
        if self.owner is not None and row["owner"] != self.owner:
            raise ExecutionBlocked("SUPERVISOR_OWNER_CHANGED")
        return row

    def _claim(self):
        now = self.clock()
        _clock(now)
        with self.engine.journal.write() as db:
            row = self._state(db)
            if row["status"] in {"STARTING", "RUNNING", "IDLE", "STOPPING"}:
                self.engine._halt(db, "INTERRUPTED_SUPERVISOR", now)
            owner = uuid4().hex
            db.execute(
                "UPDATE execution_supervisor SET status='STARTING',owner=?,generation=generation+1,heartbeat_at=NULL WHERE id=1",
                (owner,),
            )
            self.engine.journal.event(
                db, now, "SUPERVISOR_STARTED", {"generation": row["generation"] + 1}
            )
        self.owner = owner

    def _finish(self, status, *, error=None):
        now = self.clock()
        _clock(now)
        # Failure/stop reduces authority even if runtime configuration was changed.
        with self.engine.journal.write() as db:
            row = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
            if row["owner"] != self.owner:
                raise ExecutionBlocked("SUPERVISOR_OWNER_CHANGED")
            control = db.execute("SELECT ledger_json FROM execution_control WHERE id=1").fetchone()
            risk = (
                Ledger.model_validate_json(control[0]).position is not None
                or db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone()
                is not None
            )
            if status == "FAILED" or risk:
                self.engine._halt(
                    db,
                    "SUPERVISOR_FAILED" if status == "FAILED" else "SUPERVISOR_STOPPED_WITH_RISK",
                    now,
                )
            result = {"status": status, **({"error_class": error} if error else {})}
            db.execute(
                "UPDATE execution_supervisor SET status=?,result_json=? WHERE id=1",
                (status, json.dumps(result)),
            )
            self.engine.journal.event(
                db, now, "SUPERVISOR_TICK", {"status": status, "result": result}
            )

    def _publish(self, status, result, now, *, sample=None):
        _clock(now)
        with self.engine.journal.write() as db:
            row = self._state(db)
            if row["status"] == "STOPPING":
                # A draining tick must never re-grant entry health after stop.
                status, result = "STOPPING", {"status": "STOPPING"}
            if status == "RUNNING":
                control = self.engine._control(db)
                if control["halted"] or json.loads(control["issues_json"]):
                    result = {**result, "status": "BLOCKED"}
            if row["heartbeat_at"] and now.isoformat() != row["heartbeat_at"]:
                from datetime import datetime

                if now < datetime.fromisoformat(row["heartbeat_at"]):
                    raise ExecutionBlocked("SUPERVISOR_TIME_REGRESSION")
            db.execute(
                "UPDATE execution_supervisor SET status=?,heartbeat_at=?,result_json=? WHERE id=1",
                (status, now.isoformat(), json.dumps(result, sort_keys=True)),
            )
            if sample is not None:
                db.execute(
                    "UPDATE execution_supervisor SET feed_sequence=?,feed_hash=? WHERE id=1", sample
                )
            self.engine.journal.event(
                db, now, "SUPERVISOR_TICK", {"status": status, "result": result}
            )

    async def _tick(self):
        now = self.clock()
        _clock(now)
        with self.engine.journal.read() as db:
            row = self._state(db)
            control = self.engine._control(db)
            flat = Ledger.model_validate_json(control["ledger_json"]).position is None
            active = db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone()
            window = self.engine.calendar.current_window(now)
            idle = window is None and flat and active is None
        if idle:
            self._publish("IDLE", {"status": "IDLE", "reason": "MARKET_CLOSED"}, now)
            return
        reconciled = await self.engine.reconcile_fixture(
            self.venue, now=now, fence_account_changes=True
        )
        if reconciled.get("superseded"):
            # No account evidence or heartbeat is renewed by an in-flight older read.
            return
        if not reconciled["reconciled"]:
            raise ExecutionBlocked("SUPERVISOR_RECONCILIATION_REQUIRED")
        now = self.clock()
        sequence, packet = self.feed.latest()
        packet = self.engine._validated_packet(packet)
        self.engine._market_values(packet)
        digest = hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
        with self.engine.journal.read() as db:
            row = self._state(db)
            if row["feed_sequence"] is not None and (
                sequence < row["feed_sequence"]
                or (sequence == row["feed_sequence"] and digest != row["feed_hash"])
            ):
                raise ExecutionBlocked("SUPERVISOR_QUOTE_HISTORY_CHANGED")
        stamps = [packet.as_of, *(c.quote.timestamp for c in packet.candidates)]
        if any(
            t.tzinfo is None
            or not 0 <= (now - t).total_seconds() <= self.engine.settings.quote_max_age_seconds
            for t in stamps
        ):
            raise ExecutionBlocked("SUPERVISOR_MARKET_NOT_FRESH")
        assessment = self.engine.supervise(packet, now=now)
        result = {"status": "OK", "assessment": assessment, "dispatched_side": None}
        with self.engine.journal.read() as db:
            halted = bool(self.engine._control(db)["halted"])
        if assessment["status"] == "BLOCKED" or halted:
            result["status"] = "BLOCKED"
        elif assessment["status"] in {"EXIT_REQUIRED", "EXIT_PENDING"}:
            intent = self.engine.prepare_protective_exit(packet, now=now)
            if intent is None or intent.side != "SELL":
                raise ExecutionBlocked("SUPERVISOR_SELL_ONLY")
            outcome = await self.engine.dispatch_async(
                intent.client_id, self.venue, now=now, packet=packet
            )
            result.update(
                dispatched_side="SELL", client_id=intent.client_id, order_status=str(outcome)
            )
            if outcome in {"UNKNOWN", "REJECTED"}:
                result["status"] = "BLOCKED"
        completed = self.clock()
        if not 0 <= (completed - now).total_seconds() <= self.limits.max_age_seconds:
            raise ExecutionBlocked("SUPERVISOR_COMPLETION_NOT_FRESH")
        if any(
            not 0 <= (completed - t).total_seconds() <= self.engine.settings.quote_max_age_seconds
            for t in stamps
        ):
            raise ExecutionBlocked("SUPERVISOR_MARKET_NOT_FRESH")
        with self.engine.journal.read() as db:
            control = self.engine._control(db)
            if not control["snapshot_json"] or not self.engine._fresh(
                Snapshot.model_validate_json(control["snapshot_json"]),
                completed,
                self.engine.settings.quote_max_age_seconds,
            ):
                raise ExecutionBlocked("SUPERVISOR_ACCOUNT_NOT_FRESH")
        self._publish("RUNNING", result, completed, sample=(sequence, digest))

    async def run(self, stop: asyncio.Event, *, drain_tick_on_stop=False):
        lock_path = Path(str(self.engine.journal.path) + ".supervisor.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SupervisorAlreadyRunning("Fixture supervisor already running") from None
            self._claim()
            stopping = asyncio.create_task(stop.wait())
            tick = None
            try:
                while not stop.is_set():
                    tick = asyncio.create_task(
                        asyncio.wait_for(self._tick(), self.limits.tick_timeout_seconds)
                    )
                    done, _ = await asyncio.wait(
                        {tick, stopping}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if stopping in done:
                        self._finish("STOPPING")
                        if drain_tick_on_stop:
                            # The tick already owns a bounded timeout and its fixed
                            # child deadline; entry authority was revoked above.
                            await tick
                        else:
                            tick.cancel()
                            try:
                                await tick
                            except asyncio.CancelledError:
                                pass
                        break
                    tick.result()
                    tick = None
                    try:
                        await asyncio.wait_for(asyncio.shield(stopping), self.limits.poll_seconds)
                    except TimeoutError:
                        pass
                return 0
            except asyncio.CancelledError:
                self._finish("STOPPING")
                if tick is not None:
                    tick.cancel()
                    try:
                        await tick
                    except asyncio.CancelledError:
                        pass
                raise
            except Exception as exc:  # noqa: BLE001 -- failed supervision cannot retain entry health
                self._finish("FAILED", error=type(exc).__name__)
                return 1
            finally:
                stopping.cancel()
                await asyncio.gather(stopping, return_exceptions=True)
                with self.engine.journal.read() as db:
                    row = db.execute(
                        "SELECT status,owner FROM execution_supervisor WHERE id=1"
                    ).fetchone()
                    failed = row["status"] == "FAILED"
                    owned = row["owner"] == self.owner
                if not failed and owned:
                    self._finish("STOPPED")
                self.owner = None
        finally:
            os.close(fd)
