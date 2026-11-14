"""Opt-in durable, bounded HTTPS alert delivery. No order/model capabilities."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field, field_validator

from app.domain.models import utc_now
from app.execution import alert_state, restore
from app.execution.engine import ExecutionEngine, _clock
from app.execution.models import Contract
from app.execution.process import _cleanup

MAX_REQUEST_BYTES = 16384
MAX_RESPONSE_BYTES = 1024


def ca_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024 * 1024:
            raise ValueError("A bounded regular CA file is required")
        return os.read(fd, 1024 * 1024 + 1)
    finally:
        os.close(fd)


class AlertAlreadyRunning(RuntimeError):
    pass


@contextmanager
def alert_delivery_lease(journal):
    """Single-host ownership includes idle polling and native child cleanup."""
    journal = Path(journal).expanduser().absolute()
    retained = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(retained)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("A private owned existing execution journal is required")
        journal = journal.resolve(strict=True)
    finally:
        os.close(retained)
    fd = os.open(
        str(journal) + ".alerts.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("Private current-owner alert lock required")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlertAlreadyRunning("An alert service already owns this journal") from None
        yield journal
    finally:
        os.close(fd)


class AlertLimits(Contract):
    timeout_seconds: float = Field(default=10, gt=0, le=30)
    retry_seconds: float = Field(default=60, ge=30, le=300)
    max_attempts: int = Field(default=3, ge=1, le=3, strict=True)
    max_pending_age_seconds: float = Field(default=120, ge=30, le=300)
    poll_seconds: float = Field(default=5, ge=1, le=30)


class AlertConfig(Contract):
    origin: str = Field(max_length=256)
    limits: AlertLimits = Field(default_factory=AlertLimits)

    @field_validator("origin")
    @classmethod
    def origin_only(cls, value):
        p = urlsplit(value)
        if (
            not value.isascii()
            or any(c.isspace() or ord(c) < 32 for c in value)
            or p.scheme != "https"
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.path not in {"", "/"}
            or p.query
            or p.fragment
            or p.port == 0
            or any(c in p.netloc for c in "*\\%")
            or p.netloc.endswith(":")
        ):
            raise ValueError("An exact HTTPS alert sink origin is required")
        return "https://" + p.netloc.lower()


class AlertMessage(Contract):
    schema_version: Literal["execution-alert-v1"] = "execution-alert-v1"
    delivery_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_id: str = Field(min_length=1, max_length=64)
    event_sequence: int = Field(gt=0, strict=True)
    occurred_at: datetime
    kind: str = Field(min_length=1, max_length=80)


class AlertReceipt(Contract):
    delivery_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: bool = Field(strict=True)


class AlertRequest(Contract):
    config: AlertConfig
    message: AlertMessage
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_file: str
    ca_file: str | None = None
    ca_sha256: str | None = None
    parent_pid: int = Field(gt=0)
    deadline_monotonic: float = Field(gt=0)


async def _send(request):
    """Only the fixed child receives the sink credential path; pipes are bounded."""
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Alert request exceeded protocol limit")
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "app.execution.alert_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ},
        )
    )
    process = None
    try:
        async with asyncio.timeout(max(0, request.deadline_monotonic - time.monotonic())):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            data = bytearray()
            while chunk := await process.stdout.read(1024):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ValueError("Alert response exceeded protocol limit")
            await process.wait()
            if process.returncode:
                raise ValueError("Alert sink did not confirm acceptance")
            receipt = AlertReceipt.model_validate_json(data)
            if (
                not receipt.accepted
                or receipt.delivery_id != request.message.delivery_id
                or receipt.payload_sha256 != request.payload_sha256
            ):
                raise ValueError("Alert receipt binding mismatch")
            return receipt
    finally:
        if process is None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            await _cleanup(process)


class AlertDelivery:
    def __init__(self, engine, config, *, token_file, ca_file=None, clock=utc_now):
        self._configure(engine, config, token_file=token_file, ca_file=ca_file, clock=clock)
        now = clock()
        _clock(now)
        now = now.astimezone(UTC)
        with engine.journal.write() as db:
            engine._control(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_alert_delivery (id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_alert_attempts (event_sequence INTEGER PRIMARY KEY REFERENCES execution_alerts(event_sequence),delivery_id TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,attempts INTEGER NOT NULL,batch_attempts INTEGER NOT NULL,status TEXT NOT NULL,claim_id TEXT NOT NULL,next_at TEXT NOT NULL,completed_at TEXT)"
            )
            frozen = self._policy()
            row = db.execute(
                "SELECT policy_json FROM execution_alert_delivery WHERE id=1"
            ).fetchone()
            if row:
                if row[0] != frozen:
                    raise ValueError("Alert delivery policy is immutable")
            else:
                if db.execute("SELECT 1 FROM execution_orders").fetchone():
                    raise ValueError("Alert enrollment must precede order preparation")
                db.execute("INSERT INTO execution_alert_delivery VALUES(1,?)", (frozen,))
                engine.journal.event(
                    db, now, "ALERT_DELIVERY_ENROLLED", {"journal_id": self.journal_id}
                )

    def _configure(self, engine, config, *, token_file, ca_file, clock):
        if type(engine) is not ExecutionEngine:
            raise ValueError("Only the built-in fixture execution engine is supported")
        self.engine, self.clock = engine, clock
        self.config = AlertConfig.model_validate(config.model_dump())
        self.token_file = str(Path(token_file).expanduser().absolute())
        self.ca_file = str(Path(ca_file).expanduser().absolute()) if ca_file else None
        self.ca_sha256 = hashlib.sha256(ca_bytes(self.ca_file)).hexdigest() if ca_file else None
        _clock(clock())
        # Enrollment is explicit, never adopts a damaged or unfenced journal.
        with engine.journal.read() as db:
            if (
                restore.status(db, restore.authority_path(engine.journal.path))["status"]
                != "VERIFIED"
            ):
                raise ValueError("Verified restore authority required for alert delivery")
            self.journal_id = db.execute(
                "SELECT authority_id FROM execution_restore_binding WHERE id=1"
            ).fetchone()[0]

    @classmethod
    def attach_existing(cls, engine, *, clock=utc_now):
        """Read-only attachment; never enroll, migrate or recover trading attempts."""
        if cls is not AlertDelivery or type(engine) is not ExecutionEngine:
            raise ValueError("Only built-in alert attachment is supported")
        with engine.journal.read() as db:
            names = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                    "('execution_alert_delivery','execution_alert_attempts')"
                )
            }
            if len(names) != 2:
                raise ValueError("Explicit alert enrollment required")
            row = db.execute(
                "SELECT CASE WHEN length(CAST(policy_json AS BLOB))<=16384 "
                "THEN policy_json ELSE NULL END FROM execution_alert_delivery WHERE id=1"
            ).fetchone()
            if not row or not row[0]:
                raise ValueError("Bounded enrolled alert policy required")
            policy = json.loads(row[0])
        delivery = object.__new__(cls)
        delivery._configure(
            engine,
            AlertConfig(origin=policy["origin"], limits=policy["limits"]),
            token_file=policy["token_file"],
            ca_file=policy["ca_file"],
            clock=clock,
        )
        with engine.journal.read() as db:
            delivery._state(db)
        return delivery

    def _policy(self):
        return json.dumps(
            {
                "policy": "https-alert-v1",
                "journal_id": self.journal_id,
                **self.config.model_dump(mode="json"),
                "token_file": self.token_file,
                "ca_file": self.ca_file,
                "ca_sha256": self.ca_sha256,
            },
            sort_keys=True,
        )

    def _state(self, db):
        self.engine._control(db)
        row = db.execute("SELECT policy_json FROM execution_alert_delivery WHERE id=1").fetchone()
        if not row or row[0] != self._policy():
            raise ValueError("Alert delivery configuration changed")

    def report(self, *, now=None, limit=25):
        now = now or self.clock()
        _clock(now)
        if not 1 <= limit <= 100:
            raise ValueError("Invalid delivery report page")
        with self.engine.journal.read() as db:
            self._state(db)
            return {
                **alert_state.report(db, now),
                "restore_fence": restore.status(
                    db, restore.authority_path(self.engine.journal.path)
                ),
                "attempts": [
                    dict(r)
                    for r in db.execute(
                        "SELECT event_sequence,delivery_id,attempts,batch_attempts,status,next_at,completed_at FROM execution_alert_attempts ORDER BY event_sequence LIMIT ?",
                        (limit,),
                    )
                ],
            }

    def _claim(self, now):
        with self.engine.journal.write() as db:
            self._state(db)
            row = db.execute(
                "SELECT e.sequence,e.kind,e.occurred_at,d.* FROM execution_alerts a "
                "JOIN execution_events e ON e.sequence=a.event_sequence "
                "LEFT JOIN execution_alert_attempts d ON d.event_sequence=a.event_sequence "
                "WHERE d.status IS NULL OR (d.status IN ('RETRY','IN_FLIGHT') AND d.next_at<=?) "
                "ORDER BY e.sequence LIMIT 1",
                (now.isoformat(),),
            ).fetchone()
            if row is None:
                return None
            if (
                row["attempts"] is not None
                and row["batch_attempts"] >= self.config.limits.max_attempts
            ):
                db.execute(
                    "UPDATE execution_alert_attempts SET status='EXHAUSTED' WHERE event_sequence=?",
                    (row["sequence"],),
                )
                return {"exhausted": True}
            identifier = hashlib.sha256(f"{self.journal_id}:{row['sequence']}".encode()).hexdigest()
            message = AlertMessage(
                delivery_id=identifier,
                journal_id=self.journal_id,
                event_sequence=row["sequence"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                kind=row["kind"],
            )
            body = message.model_dump_json()
            digest = hashlib.sha256(body.encode()).hexdigest()
            if row["delivery_id"] is not None and (
                row["delivery_id"] != identifier
                or row["payload_json"] != body
                or row["payload_sha256"] != digest
            ):
                raise ValueError("Alert event binding changed")
            claim = uuid4().hex
            attempts = (row["attempts"] or 0) + 1
            batch_attempts = (row["batch_attempts"] or 0) + 1
            retry_at = now + timedelta(
                seconds=max(
                    self.config.limits.timeout_seconds + 5,
                    self.config.limits.retry_seconds * 2 ** (batch_attempts - 1),
                )
            )
            db.execute(
                "INSERT INTO execution_alert_attempts VALUES(?,?,?,?,?,?,'IN_FLIGHT',?,?,NULL) "
                "ON CONFLICT(event_sequence) DO UPDATE SET attempts=excluded.attempts,batch_attempts=excluded.batch_attempts,status=excluded.status,claim_id=excluded.claim_id,next_at=excluded.next_at,completed_at=NULL",
                (
                    row["sequence"],
                    identifier,
                    body,
                    digest,
                    attempts,
                    batch_attempts,
                    claim,
                    retry_at.isoformat(),
                ),
            )
            self.engine.journal.event(
                db,
                now,
                "ALERT_DELIVERY_ATTEMPTED",
                {
                    "event_sequence": row["sequence"],
                    "delivery_id": identifier,
                    "attempt": attempts,
                    "batch_attempt": batch_attempts,
                },
            )
            return {
                "message": message,
                "digest": digest,
                "claim": claim,
                "attempts": attempts,
                "batch_attempts": batch_attempts,
            }

    def rearm(self, event_sequence, reason, *, now):
        """Explicit trusted-local outage recovery only; no HTTP route or trading resume."""
        _clock(now)
        self.engine._reason(reason)
        if type(event_sequence) is not int or event_sequence <= 0 or len(reason) > 300:
            raise ValueError("A reviewed alert target and bounded reason are required")
        now = now.astimezone(UTC)
        with self.engine.journal.write() as db:
            self._state(db)
            row = db.execute(
                "SELECT * FROM execution_alert_attempts WHERE event_sequence=?", (event_sequence,)
            ).fetchone()
            if not row or row["status"] != "EXHAUSTED":
                raise ValueError("Only an exhausted alert can be rearmed")
            db.execute(
                "UPDATE execution_alert_attempts SET batch_attempts=0,status='RETRY',next_at=?,completed_at=NULL WHERE event_sequence=?",
                (now.isoformat(), event_sequence),
            )
            self.engine.journal.event(
                db,
                now,
                "ALERT_DELIVERY_REARMED",
                {
                    "event_sequence": event_sequence,
                    "reason": reason,
                    "prior_attempts": row["attempts"],
                },
            )

    async def deliver_once(self):
        try:
            with alert_delivery_lease(self.engine.journal.path):
                return await self._deliver_owned()
        except AlertAlreadyRunning:
            return {"status": "BUSY"}

    async def _deliver_owned(self):
        now = self.clock()
        _clock(now)
        now = now.astimezone(UTC)
        with self.engine.journal.read() as db:
            self._state(db)
            fence = restore.status(db, restore.authority_path(self.engine.journal.path))
            if fence["status"] != "VERIFIED":
                raise ValueError(fence.get("reason", "Verified restore authority required"))
            due = db.execute(
                "SELECT 1 FROM execution_alerts a LEFT JOIN execution_alert_attempts d ON d.event_sequence=a.event_sequence WHERE d.status IS NULL OR (d.status IN ('RETRY','IN_FLIGHT') AND d.next_at<=?) LIMIT 1",
                (now.isoformat(),),
            ).fetchone()
        if due is None:
            return {"status": "IDLE"}
        claimed = self._claim(now)
        if claimed is None:
            return {"status": "IDLE"}
        if claimed.get("exhausted"):
            return {"status": "EXHAUSTED"}
        # Deadline starts at admission, before process creation.
        request = AlertRequest(
            config=self.config,
            message=claimed["message"],
            payload_sha256=claimed["digest"],
            token_file=self.token_file,
            ca_file=self.ca_file,
            ca_sha256=self.ca_sha256,
            parent_pid=os.getpid(),
            deadline_monotonic=time.monotonic() + self.config.limits.timeout_seconds,
        )
        try:
            await _send(request)
        except asyncio.CancelledError:
            # Preserve IN_FLIGHT until its conservative lease expires; never assume nondelivery.
            raise
        except Exception:  # noqa: BLE001 -- no endpoint/credential/response exception text in audit
            status = (
                "EXHAUSTED"
                if claimed["batch_attempts"] >= self.config.limits.max_attempts
                else "RETRY"
            )
        else:
            status = "DELIVERED"
        done = self.clock()
        _clock(done)
        done = done.astimezone(UTC)
        with self.engine.journal.write() as db:
            self._state(db)
            changed = db.execute(
                "UPDATE execution_alert_attempts SET status=?,completed_at=? WHERE event_sequence=? AND claim_id=? AND status='IN_FLIGHT'",
                (status, done.isoformat(), request.message.event_sequence, claimed["claim"]),
            ).rowcount
            if changed != 1:
                raise ValueError("Alert claim ownership changed")
            self.engine.journal.event(
                db,
                done,
                "ALERT_DELIVERY_RESULT",
                {
                    "event_sequence": request.message.event_sequence,
                    "attempt": claimed["attempts"],
                    "status": status,
                },
            )
        return {"status": status, "event_sequence": request.message.event_sequence}

    async def run(self, stop_event):
        with alert_delivery_lease(self.engine.journal.path):
            await self._run_owned(stop_event)

    async def _run_owned(self, stop_event):
        while not stop_event.is_set():
            await self._deliver_owned()
            try:
                await asyncio.wait_for(stop_event.wait(), self.config.limits.poll_seconds)
            except TimeoutError:
                pass
