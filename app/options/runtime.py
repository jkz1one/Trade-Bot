"""One continuous local options PAPER owner; protection does not wait for reasoning."""

import asyncio
import json
import os
import stat
from datetime import datetime

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.engine import fingerprint
from app.options.runtime_models import RuntimePacket, RuntimePolicy

MAX_PACKET_BYTES = 256 * 1024


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= MAX_PACKET_BYTES
        ):
            raise ValueError("Bounded private normalized fixture packet required")
        raw = stream.read(MAX_PACKET_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > MAX_PACKET_BYTES or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("Fixture packet changed during read")
    return raw


def read_packet(path):
    return RuntimePacket.model_validate_json(read_private(path))


class OptionRuntime:
    def __init__(self, coordinator, policy, *, create=False):
        if type(coordinator) is not DegenCoordinator or coordinator.replay_model is not None:
            raise ValueError("A native built-in Degen owner is required")
        if getattr(coordinator.engine, "_option_runtime", None) is not None:
            raise ValueError("One runtime per active owner")
        self.c = coordinator
        self.policy = RuntimePolicy.model_validate(policy.model_dump())
        budget = self.policy.tick_seconds + self.c.engine.policy.process_timeout_seconds
        if budget >= min(
            self.policy.heartbeat_max_age_seconds,
            self.c.engine.policy.supervisor_max_age_seconds,
            self.c.engine.limits.account_max_age_seconds,
        ):
            raise ValueError("Protection budget exceeds freshness bounds")
        self.frozen = json.dumps(
            {
                "runtime": self.policy.model_dump(mode="json"),
                "engine": json.loads(self.c.engine._config),
                "strategy": json.loads(self.c._frozen),
            },
            sort_keys=True,
        )
        self.task = None
        self.running = False
        self.stop = None
        self.last_at = None
        self.operator = None
        with self.c.engine.journal.write() as db:
            self.c._bound(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_runtime(id INTEGER PRIMARY KEY CHECK(id=1),config_json TEXT NOT NULL,status TEXT NOT NULL,heartbeat_at TEXT,feed_sequence INTEGER NOT NULL,frame_hash TEXT,frame_json TEXT,reason TEXT,generation INTEGER NOT NULL,session_json TEXT,feed_recorded_at TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_runtime_slots(slot INTEGER PRIMARY KEY,session TEXT NOT NULL,status TEXT NOT NULL,reason TEXT,started_at TEXT NOT NULL,completed_at TEXT)"
            )
            row = db.execute("SELECT * FROM execution_option_runtime WHERE id=1").fetchone()
            if row is None:
                if (
                    not create
                    or db.execute("SELECT 1 FROM execution_option_opportunities LIMIT 1").fetchone()
                ):
                    raise ExecutionBlocked("NEW_RUNTIME_POPULATION_REQUIRED")
                db.execute(
                    "INSERT INTO execution_option_runtime VALUES(1,?,'ENROLLED',NULL,0,NULL,NULL,NULL,0,NULL,NULL)",
                    (self.frozen,),
                )
                self.c.engine.journal.event(db, self.c.now(), "OPTION_RUNTIME_ENROLLED", {})
            elif create or row["config_json"] != self.frozen:
                raise ExecutionBlocked("FROZEN_OPTION_RUNTIME_CHANGED")
            elif row["status"] in {"RUNNING", "BLOCKED", "STOPPING"}:
                self.c.engine._halt(db, "OPTION_RUNTIME_INTERRUPTED", self.c.now())
                db.execute(
                    "UPDATE execution_option_runtime SET status='FAILED',reason='OPTION_RUNTIME_INTERRUPTED' WHERE id=1"
                )
                db.execute(
                    "UPDATE execution_option_runtime_slots SET status='INTERRUPTED',reason='OPTION_RUNTIME_INTERRUPTED',completed_at=? WHERE status='STARTED'",
                    (self.c.now().isoformat(),),
                )
        self.c.engine._option_runtime = self
        if self.policy.operator_key_file is not None:
            from app.options.operator_inbox import CommandInbox

            self.operator = CommandInbox(self.c.engine, self.policy.operator_key_file)

    def _bound(self, db):
        self.c._bound(db)
        row = db.execute("SELECT * FROM execution_option_runtime WHERE id=1").fetchone()
        if (
            row is None
            or row["config_json"] != self.frozen
            or (self.c.engine._option_runtime is not self)
        ):
            raise ExecutionBlocked("OPTION_RUNTIME_OWNER_CHANGED")
        return row

    async def _cycle(self, slot, frame):
        status, reason = "INTERRUPTED", "OPTION_RUNTIME_CYCLE_INTERRUPTED"
        try:
            result = await self.c.cycle(frame)
            status, reason = "COMPLETE", result.get("reason")
        finally:
            with self.c.engine.journal.write() as db:
                self._bound(db)
                db.execute(
                    "UPDATE execution_option_runtime_slots SET status=?,reason=?,completed_at=? WHERE slot=?",
                    (status, reason, self.c.now().isoformat(), slot),
                )

    async def tick(self):
        if not self.running:
            raise ExecutionBlocked("OPTION_RUNTIME_NOT_RUNNING")
        if self.task is not None and self.task.done():
            self.task.result()
            self.task = None
        at = self.c.now()
        if self.last_at is not None and at < self.last_at:
            raise ValueError("Runtime clock moved backwards")
        self.last_at = at
        operator_issue = self.operator.poll(now=at) if self.operator is not None else None
        if operator_issue:
            with self.c.engine.journal.write() as db:
                self._bound(db)
                control = self.c.engine._control(db)
                if not control["halted"] or control["halt_reason"] != operator_issue:
                    self.c.engine._halt(db, operator_issue, at)
        packet, issue = None, None
        try:
            packet = read_packet(self.policy.feed_file)
            with self.c.engine.journal.read() as db:
                row = self._bound(db)
                if (
                    packet.population_id != self.c.engine.limits.population_id
                    or not 0
                    <= (at - packet.recorded_at).total_seconds()
                    < self.policy.feed_max_age_seconds
                    or packet.sequence < row["feed_sequence"]
                    or (
                        row["feed_recorded_at"]
                        and packet.recorded_at < datetime.fromisoformat(row["feed_recorded_at"])
                    )
                    or (
                        packet.sequence == row["feed_sequence"]
                        and fingerprint(packet) != row["frame_hash"]
                    )
                ):
                    raise ValueError("Fixture feed identity, time or sequence mismatch")
        except (OSError, ValueError):
            packet, issue = None, "OPTION_RUNTIME_FEED_UNAVAILABLE"
        issue = issue or operator_issue
        if issue:
            # Fence a pending model/entry before the next native snapshot can suspend.
            with self.c.engine.journal.write() as db:
                self._bound(db)
                control = self.c.engine._control(db)
                if not control["halted"] or control["halt_reason"] != issue:
                    self.c.engine._halt(db, issue, at)
                db.execute(
                    "UPDATE execution_option_runtime SET status='BLOCKED',reason=? WHERE id=1",
                    (issue,),
                )
        frame = packet.frame if packet else DegenFrame()
        # Feed failure never skips reconciliation/protection or invents market quotes.
        result = await self.c.supervise(frame.quotes, frame.underlyings)
        if result.get("reconciled") is False and result.get("issues") not in (
            ["OPTION_READ_SUPERSEDED"],
            ["OPTION_SUBMISSION_IN_PROGRESS"],
        ):
            issue = issue or "OPTION_RUNTIME_RECONCILIATION_BLOCKED"
        window = self.c.engine.calendar.current_window(at)
        current = self.c.engine.calendar.current_window(self.c.now())
        with self.c.engine.journal.write() as db:
            self._bound(db)
            if issue:
                control = self.c.engine._control(db)
                if not control["halted"] or control["halt_reason"] != issue:
                    self.c.engine._halt(db, issue, at)
            db.execute(
                "UPDATE execution_option_runtime SET status=?,heartbeat_at=?,reason=?,session_json=? WHERE id=1",
                (
                    "BLOCKED" if issue else "RUNNING",
                    self.c.now().isoformat(),
                    issue,
                    json.dumps(
                        {
                            "status": "OPEN",
                            "date": current.session_date,
                            "opens_at": current.opens_at.isoformat(),
                            "closes_at": current.closes_at.isoformat(),
                        }
                    )
                    if current
                    else json.dumps({"status": "CLOSED"}),
                ),
            )
            if packet:
                db.execute(
                    "UPDATE execution_option_runtime SET feed_sequence=?,frame_hash=?,frame_json=?,feed_recorded_at=? WHERE id=1",
                    (
                        packet.sequence,
                        fingerprint(packet),
                        packet.frame.model_dump_json(),
                        packet.recorded_at.isoformat(),
                    ),
                )
            if window is None:
                return result
            slot = int(self.c.now().timestamp()) // 300
            # The completed protection tick may cross a session/slot boundary.
            if current is None or current.session_date != window.session_date:
                return result
            previous = db.execute(
                "SELECT MAX(slot) FROM execution_option_runtime_slots WHERE session=?",
                (window.session_date,),
            ).fetchone()[0]
            start = int(window.opens_at.timestamp()) // 300 if previous is None else previous + 1
            for missing in range(start, slot):
                db.execute(
                    "INSERT OR IGNORE INTO execution_option_runtime_slots VALUES(?,?,'SKIPPED','RUNTIME_SLOT_NOT_OBSERVED',?,?)",
                    (missing, window.session_date, at.isoformat(), self.c.now().isoformat()),
                )
            if db.execute(
                "SELECT 1 FROM execution_option_runtime_slots WHERE slot=?", (slot,)
            ).fetchone():
                return result
            reason = issue or ("MODEL_OR_CYCLE_IN_PROGRESS" if self.task else None)
            db.execute(
                "INSERT INTO execution_option_runtime_slots VALUES(?,?,?,?,?,?)",
                (
                    slot,
                    window.session_date,
                    "SKIPPED" if reason else "STARTED",
                    reason,
                    self.c.now().isoformat(),
                    self.c.now().isoformat() if reason else None,
                ),
            )
        if reason is None:
            self.task = asyncio.create_task(self._cycle(slot, frame))
        return result

    async def run(self, stop):
        if self.running:
            raise ExecutionBlocked("OPTION_RUNTIME_ALREADY_RUNNING")
        if type(stop) is not asyncio.Event:
            raise ValueError("Explicit runtime shutdown event required")
        self.stop = stop
        self.running = True
        failed = False
        from app.options.release_identity import inspect_release

        try:
            release = inspect_release(now=self.c.now())
            with self.c.engine.journal.write() as db:
                previous = self._bound(db)
                db.execute(
                    "UPDATE execution_option_runtime SET status='RUNNING',heartbeat_at=NULL,generation=generation+1,reason=NULL WHERE id=1"
                )
                self.c.engine.journal.event(
                    db,
                    self.c.now(),
                    "OPTION_RUNTIME_STARTED",
                    {
                        "generation": previous["generation"] + 1,
                        "release": release.model_dump(mode="json"),
                    },
                )
            while not stop.is_set():
                await self.tick()
                try:
                    await asyncio.wait_for(stop.wait(), self.policy.tick_seconds)
                except TimeoutError:
                    pass
        except BaseException:
            failed = True
            raise
        finally:
            try:
                try:
                    with self.c.engine.journal.write() as db:
                        self._bound(db)
                        self.c.engine._halt(
                            db,
                            "OPTION_RUNTIME_FAILED" if failed else "OPTION_RUNTIME_STOPPED",
                            self.c.now(),
                        )
                        db.execute(
                            "UPDATE execution_option_runtime SET status='STOPPING' WHERE id=1"
                        )
                finally:
                    if self.task is not None:
                        self.task.cancel()
                        await asyncio.gather(self.task, return_exceptions=True)
                        self.task = None
                with self.c.engine.journal.write() as db:
                    self._bound(db)
                    db.execute(
                        "UPDATE execution_option_runtime_slots SET status='INTERRUPTED',reason='OPTION_RUNTIME_CYCLE_INTERRUPTED',completed_at=? WHERE status='STARTED'",
                        (self.c.now().isoformat(),),
                    )
                    db.execute(
                        "UPDATE execution_option_runtime SET status=?,reason=? WHERE id=1",
                        (
                            "FAILED" if failed else "STOPPED",
                            "OPTION_RUNTIME_FAILED" if failed else "OPTION_RUNTIME_STOPPED",
                        ),
                    )
                    self.c.engine.journal.event(
                        db, self.c.now(), "OPTION_RUNTIME_STOPPED", {"failed": failed}
                    )
            finally:
                self.running = False
