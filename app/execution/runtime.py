"""Opt-in single-host PAPER service. Only durable fixture orders are supported."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import Field, model_validator

from app.domain.models import TradeDecision, utc_now
from app.execution import alert_state, restore, runtime_state, supervisor_state
from app.execution.engine import ExecutionBlocked, _clock
from app.execution.judgment import JudgmentCoordinator, configuration
from app.execution.models import Contract, Ledger, Snapshot
from app.execution.supervisor import ExecutionSupervisor


class RuntimeLimits(Contract):
    poll_seconds: float = Field(default=5, gt=0, le=30)
    max_age_seconds: float = Field(default=20, gt=0, le=90)
    cycle_timeout_seconds: float = Field(default=45, gt=0, le=160)

    @model_validator(mode="after")
    def bounded(self):
        if self.poll_seconds >= self.max_age_seconds:
            raise ValueError("Runtime poll must fit its freshness lease")
        return self


class RuntimeAlreadyRunning(RuntimeError):
    pass


@contextmanager
def runtime_lease(journal_path):
    """Acquire before opening a writable engine, and retain through child cleanup."""
    path = Path(str(journal_path) + ".runtime.lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("Runtime lease must be a private owned regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeAlreadyRunning("Fixture PAPER service already running") from None
        yield
    finally:
        os.close(fd)


def model_key(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 1 <= info.st_size <= 513
        ):
            raise ValueError("Model key requires a private bounded owned regular file")
        raw = os.read(fd, 514)
        key = raw.removesuffix(b"\n").decode("ascii")
        if not 1 <= len(key) <= 512 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("Invalid model key file")
        return key
    finally:
        os.close(fd)


class PaperRuntime:
    def __init__(self, supervisor, *, limits=None, judgment=None, key_file=None, clock=utc_now):
        if type(supervisor) is not ExecutionSupervisor:
            raise ValueError("Built-in fixture supervision is required")
        self.supervisor, self.engine, self.clock = supervisor, supervisor.engine, clock
        self.limits = RuntimeLimits.model_validate((limits or RuntimeLimits()).model_dump())
        self.judgment = judgment
        self.key_file = str(Path(key_file).absolute()) if key_file is not None else None
        if judgment is not None:
            if (
                type(judgment) is not JudgmentCoordinator
                or judgment.costs.engine is not self.engine
                or self.key_file is None
            ):
                raise ValueError("Explicit bounded model authority and private key file required")
            if (
                self.limits.cycle_timeout_seconds
                < judgment.limits.process_timeout_seconds
                + self.engine.limits.process_timeout_seconds
                + 1
            ):
                raise ValueError("Cycle deadline must contain model and fixture process deadlines")
            model_key(self.key_file)
        elif self.key_file is not None:
            raise ValueError("Stub HOLD must not receive a model credential")
        self.owner = None
        _clock(clock())

    def _policy(self):
        return {
            "policy": "fixture-session-runtime-v1",
            "agent": "openai" if self.judgment else "stub-hold",
            "limits": self.limits.model_dump(mode="json"),
            "engine": json.loads(self._config),
            "supervisor": self.supervisor._policy(),
            "judgment": configuration(self.judgment.costs, self.judgment.limits)
            if self.judgment
            else None,
            "key_file": self.key_file,
            "calendar": "XNYS-15minute-current-slot",
        }

    @property
    def _config(self):
        with self.engine.journal.read() as db:
            return self.engine._control(db)["config_json"]

    def enroll(self):
        """Explicit immutable enrollment before any order or model attempt."""
        policy = json.dumps(self._policy(), sort_keys=True)
        with self.engine.journal.read() as db:
            if (
                restore.status(db, restore.authority_path(self.engine.journal.path))["status"]
                != "VERIFIED"
            ):
                raise ValueError("Verified paired execution authority required")
        with self.engine.journal.write() as db:
            self.engine._control(db)
            for sql in (
                "CREATE TABLE IF NOT EXISTS execution_runtime(id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL,status TEXT NOT NULL,owner TEXT,generation INTEGER NOT NULL,heartbeat_at TEXT)",
                "CREATE TABLE IF NOT EXISTS execution_runtime_cycles(slot TEXT PRIMARY KEY,owner TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,feed_sequence INTEGER NOT NULL,feed_hash TEXT NOT NULL,packet_json TEXT NOT NULL,decision_json TEXT,result_json TEXT)",
            ):
                db.execute(sql)
            row = db.execute("SELECT policy_json FROM execution_runtime WHERE id=1").fetchone()
            if row:
                if row[0] != policy:
                    raise ValueError("Runtime policy is immutable")
            else:
                if db.execute(
                    "SELECT 1 FROM execution_orders UNION ALL SELECT 1 FROM execution_model_calls LIMIT 1"
                ).fetchone():
                    raise ValueError("Runtime enrollment must precede orders/model attempts")
                db.execute(
                    "INSERT INTO execution_runtime VALUES(1,?,'STOPPED',NULL,0,NULL)", (policy,)
                )
                self.engine.journal.event(db, self.clock(), "RUNTIME_ENROLLED", json.loads(policy))

    def _state(self, db):
        self.engine._control(db)
        row = db.execute("SELECT * FROM execution_runtime WHERE id=1").fetchone()
        if row is None or row["policy_json"] != json.dumps(self._policy(), sort_keys=True):
            raise ExecutionBlocked("RUNTIME_CONFIGURATION_CHANGED")
        if self.owner is not None and row["owner"] != self.owner:
            raise ExecutionBlocked("RUNTIME_OWNER_CHANGED")
        return row

    def _claim(self):
        now = self.clock()
        _clock(now)
        with self.engine.journal.write() as db:
            row = self._state(db)
            interrupted = db.execute(
                "SELECT slot FROM execution_runtime_cycles WHERE status='CLAIMED'"
            ).fetchall()
            if row["status"] in {"RUNNING", "STOPPING"} or interrupted:
                self.engine._halt(db, "INTERRUPTED_PAPER_RUNTIME", now)
                for cycle in interrupted:
                    db.execute(
                        "UPDATE execution_runtime_cycles SET status='INTERRUPTED',completed_at=?,result_json=? WHERE slot=?",
                        (now.isoformat(), json.dumps({"reason": "INTERRUPTED_RUNTIME"}), cycle[0]),
                    )
            self.owner = uuid4().hex
            db.execute(
                "UPDATE execution_runtime SET status='RUNNING',owner=?,generation=generation+1,heartbeat_at=? WHERE id=1",
                (self.owner, now.isoformat()),
            )
            self.engine.journal.event(
                db, now, "RUNTIME_STARTED", {"generation": row["generation"] + 1}
            )

    def _publish(self, status):
        now = self.clock()
        _clock(now)
        with self.engine.journal.write() as db:
            row = self._state(db)
            if row["heartbeat_at"] and now < datetime.fromisoformat(row["heartbeat_at"]):
                raise ExecutionBlocked("RUNTIME_TIME_REGRESSION")
            if status == "FAILED":
                self.engine._halt(db, "PAPER_RUNTIME_FAILED", now)
            db.execute(
                "UPDATE execution_runtime SET status=?,heartbeat_at=? WHERE id=1",
                (status, now.isoformat()),
            )
            if status != "RUNNING":
                self.engine.journal.event(db, now, "RUNTIME_STATE", {"status": status})

    def _complete(self, slot, status, result, decision=None):
        now = self.clock()
        _clock(now)
        with self.engine.journal.write() as db:
            self._state(db)
            row = db.execute(
                "SELECT * FROM execution_runtime_cycles WHERE slot=?", (slot,)
            ).fetchone()
            if row is None or row["status"] != "CLAIMED" or row["owner"] != self.owner:
                raise ExecutionBlocked("RUNTIME_CYCLE_OWNER_CHANGED")
            if now < datetime.fromisoformat(row["started_at"]):
                raise ExecutionBlocked("RUNTIME_TIME_REGRESSION")
            db.execute(
                "UPDATE execution_runtime_cycles SET status=?,completed_at=?,decision_json=?,result_json=? WHERE slot=?",
                (
                    status,
                    now.isoformat(),
                    decision.model_dump_json() if decision else None,
                    json.dumps(result, sort_keys=True),
                    slot,
                ),
            )
            if status == "INTERRUPTED":
                self.engine._halt(db, "INTERRUPTED_PAPER_CYCLE", now)
            self.engine.journal.event(
                db,
                now,
                "RUNTIME_CYCLE_COMPLETED",
                {"slot": slot, "status": status, "result": result},
            )

    async def cycle_once(self):
        if self.owner is None:
            raise ExecutionBlocked("RUNTIME_NOT_RUNNING")
        now = self.clock()
        _clock(now)
        window = self.engine.calendar.current_window(now)
        if window is None:
            return {"status": "SKIPPED", "reason": "MARKET_CLOSED"}
        slot = "PAPER:XNYS:" + window.scheduled_for.isoformat()
        with self.engine.journal.read() as db:
            self._state(db)
            if db.execute(
                "SELECT 1 FROM execution_runtime_cycles WHERE slot=?", (slot,)
            ).fetchone():
                return {"status": "SKIPPED", "reason": "SLOT_ALREADY_ATTEMPTED"}
            if not supervisor_state.report(db, now)["fresh"]:
                return {"status": "SKIPPED", "reason": "SUPERVISOR_NOT_READY"}
        sequence, packet = self.supervisor.feed.latest()
        digest = hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
        with self.engine.journal.write() as db:
            self._state(db)
            if db.execute(
                "SELECT 1 FROM execution_runtime_cycles WHERE slot=?", (slot,)
            ).fetchone():
                return {"status": "SKIPPED", "reason": "SLOT_ALREADY_ATTEMPTED"}
            if runtime_state.unresolved(db):
                return {"status": "SKIPPED", "reason": "UNRESOLVED_CYCLE"}
            health = supervisor_state.report(db, now)
            if not health["fresh"] or health["last_feed_sequence"] != sequence:
                return {"status": "SKIPPED", "reason": "SUPERVISOR_NOT_READY"}
            observed = db.execute(
                "SELECT feed_hash FROM execution_supervisor WHERE id=1"
            ).fetchone()[0]
            if observed != digest:
                raise ExecutionBlocked("RUNTIME_QUOTE_HISTORY_CHANGED")
            if runtime_state.entry_reasons(db, now) or alert_state.entry_reasons(db, now):
                return {"status": "SKIPPED", "reason": "SERVICE_NOT_READY"}
            control = self.engine._control(db)
            try:
                snapshot = self.engine._ready(control, now)
            except ExecutionBlocked:
                return {"status": "SKIPPED", "reason": "EXECUTION_NOT_READY"}
            if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
                return {"status": "SKIPPED", "reason": "ORDER_ALREADY_IN_FLIGHT"}
            self.engine._market_values(packet)
            stamps = [packet.as_of, *(c.quote.timestamp for c in packet.candidates)]
            if any(
                not 0 <= (now - t).total_seconds() <= self.engine.settings.quote_max_age_seconds
                for t in stamps
            ):
                raise ExecutionBlocked("RUNTIME_MARKET_NOT_FRESH")
            hold = TradeDecision(
                action="HOLD",
                confidence=0,
                setup_quality=0,
                thesis="Explicit fixture service stub HOLD",
                invalidation_reason="No model judgment in stub mode",
                why_now="Scheduled PAPER fixture cycle",
            )
            _, packet = self.engine._govern(
                hold,
                packet,
                Ledger.model_validate_json(control["ledger_json"]),
                Snapshot.model_validate(snapshot),
                now,
                db,
                slot,
            )
            packet = packet.model_copy(update={"session_context": window.context()})
            db.execute(
                "INSERT INTO execution_runtime_cycles(slot,owner,status,started_at,feed_sequence,feed_hash,packet_json) VALUES(?,?,'CLAIMED',?,?,?,?)",
                (slot, self.owner, now.isoformat(), sequence, digest, packet.model_dump_json()),
            )
            self.engine.journal.event(
                db,
                now,
                "RUNTIME_CYCLE_CLAIMED",
                {
                    "slot": slot,
                    "feed_sequence": sequence,
                    "feed_hash": digest,
                    "agent": "openai" if self.judgment else "stub-hold",
                },
            )
        chosen = None
        try:
            async with asyncio.timeout(self.limits.cycle_timeout_seconds):
                chosen = hold
                if self.judgment:
                    outcome = await self.judgment.decide(
                        slot, packet, api_key=model_key(self.key_file), now=now, clock=self.clock
                    )
                    packet, chosen = outcome.packet, outcome.result.decision
                completed = self.clock()
                current_window = self.engine.calendar.current_window(completed)
                if current_window is None or current_window.scheduled_for != window.scheduled_for:
                    raise ExecutionBlocked("DECISION_SESSION_SLOT_EXPIRED")
                intent = self.engine.prepare(slot, chosen, packet, now=completed)
                result = {
                    "action": chosen.action.value,
                    "client_id": intent.client_id if intent else None,
                    "order_status": None,
                }
                if intent:
                    _, fresh_packet = self.supervisor.feed.latest()
                    result["order_status"] = str(
                        await self.engine.dispatch_async(
                            intent.client_id,
                            self.supervisor.venue,
                            now=completed,
                            packet=fresh_packet,
                        )
                    )
                self._complete(slot, "COMPLETE", result, chosen)
                return {"status": "COMPLETE", **result}
        except ExecutionBlocked as exc:
            result = {"reason": str(exc)}
            self._complete(slot, "BLOCKED", result, chosen)
            return {"status": "BLOCKED", **result}
        except BaseException as exc:
            self._complete(slot, "INTERRUPTED", {"error_class": type(exc).__name__}, chosen)
            raise

    async def _heartbeat(self, stop):
        while not stop.is_set():
            self._publish("RUNNING")
            await asyncio.sleep(self.limits.poll_seconds)

    async def _cycles(self, stop):
        while not stop.is_set():
            await self.cycle_once()
            await asyncio.sleep(self.limits.poll_seconds)

    async def _serve(self, stop):
        """Private entry point used only while runtime_lease is held."""
        self._claim()
        supervision_stop = asyncio.Event()
        tasks = [
            asyncio.create_task(self.supervisor.run(supervision_stop, drain_tick_on_stop=True)),
            asyncio.create_task(self._heartbeat(stop)),
            asyncio.create_task(self._cycles(stop)),
        ]
        stopping = asyncio.create_task(stop.wait())
        failed = False

        async def drain():
            for task in tasks[1:]:
                task.cancel()
            other_results = await asyncio.gather(*tasks[1:], return_exceptions=True)
            supervision_stop.set()
            results = await asyncio.gather(tasks[0], return_exceptions=True)
            stopping.cancel()
            await asyncio.gather(stopping, return_exceptions=True)
            return results[0], other_results

        try:
            done, _ = await asyncio.wait({*tasks, stopping}, return_when=asyncio.FIRST_COMPLETED)
            failed = (
                not stop.is_set()
                or any(t in done and (t.cancelled() or t.exception() is not None) for t in tasks)
                or (
                    tasks[0] in done
                    and not tasks[0].cancelled()
                    and tasks[0].exception() is None
                    and tasks[0].result() != 0
                )
            )
        finally:
            # Revoke entry authority before draining judgment/dispatch; keep protective
            # supervision alive while a cancelled model/venue child is being reaped.
            try:
                if failed:
                    with self.engine.journal.write() as db:
                        for index, task in enumerate(tasks):
                            if task.done():
                                error = (
                                    "CancelledError"
                                    if task.cancelled()
                                    else type(task.exception()).__name__
                                    if task.exception()
                                    else None
                                )
                                self.engine.journal.event(
                                    db,
                                    self.clock(),
                                    "RUNTIME_TASK_FAILED",
                                    {
                                        "component": ("supervisor", "heartbeat", "cycles")[index],
                                        "error_class": error,
                                    },
                                )
                self._publish("FAILED" if failed else "STOPPING")
            finally:
                cleanup = asyncio.create_task(drain())
                interrupted = False
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        interrupted = True
                        continue
                result, other_results = cleanup.result()
                failed = (
                    failed
                    or isinstance(result, BaseException)
                    or result != 0
                    or any(
                        isinstance(value, BaseException)
                        and not isinstance(value, asyncio.CancelledError)
                        for value in other_results
                    )
                )
                try:
                    self._publish("FAILED" if failed else "STOPPED")
                finally:
                    self.owner = None
                if interrupted:
                    raise asyncio.CancelledError
        return 1 if failed else 0

    async def run(self, stop):
        with runtime_lease(self.engine.journal.path):
            return await self._serve(stop)
