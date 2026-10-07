"""Authenticated local recovery commands, never broker/model or HTTP authority.

The shared signing key identifies an enrolled operator capability. Actor is an
audited label, not a separately authenticated person. Trusted local Python callers
retain the existing engine API; this boundary is for future command transports.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.execution.engine import ExecutionBlocked, ExecutionEngine, _clock
from app.execution.models import Contract, Ledger


class OperatorCommand(Contract):
    journal_id: str = Field(min_length=1, max_length=64)
    command_id: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=80)
    action: Literal["HALT", "RESUME", "ABANDON_PREPARED", "ACK_ALERT", "ROTATE_KEY", "REVOKE_KEY"]
    reason: str = Field(min_length=1, max_length=300)
    expected_revision: int = Field(ge=0, strict=True)
    issued_at: datetime
    expires_at: datetime
    client_id: str | None = Field(default=None, min_length=1, max_length=128)
    alert_sequence: int | None = Field(default=None, gt=0, strict=True)
    credential_generation: int = Field(default=1, gt=0, strict=True)
    replacement_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("journal_id", "command_id", "actor", "reason", "client_id")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Operator values cannot be blank")
        return value

    @model_validator(mode="after")
    def bounded(self):
        if not 0 < (self.expires_at - self.issued_at).total_seconds() <= 300:
            raise ValueError("Commands require a positive lifetime of at most five minutes")
        if (self.action == "ABANDON_PREPARED") != (self.client_id is not None):
            raise ValueError("Only abandonment has an order target")
        if (self.action == "ACK_ALERT") != (self.alert_sequence is not None):
            raise ValueError("Only acknowledgment has an alert target")
        if (self.action == "ROTATE_KEY") != (self.replacement_fingerprint is not None):
            raise ValueError("Only rotation has a replacement fingerprint")
        if self.replacement_fingerprint and any(
            c not in "0123456789abcdef" for c in self.replacement_fingerprint
        ):
            raise ValueError("Invalid replacement fingerprint")
        return self


def _key_hash(key):
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("Operator key requires at least 32 bytes")
    return hashlib.sha256(key).hexdigest()


def _body(command):
    command = OperatorCommand.model_validate(command.model_dump())
    return json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def sign_command(command: OperatorCommand, key: bytes):
    """Sign an exact envelope. Keep the key outside journal, model and worker state."""
    _key_hash(key)
    return hmac.new(key, _body(command).encode(), hashlib.sha256).hexdigest()


class OperatorControl:
    @staticmethod
    def enroll(engine: ExecutionEngine, key: bytes, *, now):
        """Explicit local provisioning; no automatic key adoption or replacement."""
        _clock(now)
        if type(engine) is not ExecutionEngine:
            raise ValueError("Only the offline execution engine is supported")
        key_hash = _key_hash(key)
        with engine.journal.write() as db:
            old = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
            if old:
                if old["revoked"] or not hmac.compare_digest(old["key_hash"], key_hash):
                    raise ValueError("Operator capability is already enrolled")
                return old["journal_id"]
            engine._control(db)
            journal_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO execution_operator(id,journal_id,key_hash) VALUES(1,?,?)",
                (journal_id, key_hash),
            )
            engine.journal.event(db, now, "OPERATOR_ENROLLED", {"journal_id": journal_id})
            return journal_id

    @staticmethod
    def recover_revoked(engine: ExecutionEngine, key: bytes, reason: str, *, now):
        """Trusted local recovery only; does not resume or release any reservation."""
        _clock(now)
        if type(engine) is not ExecutionEngine:
            raise ValueError("Only the offline execution engine is supported")
        engine._reason(reason)
        fingerprint = _key_hash(key)
        with engine.journal.write() as db:
            row = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
            if not row or not row["revoked"]:
                raise ValueError("Only a revoked capability can be recovered locally")
            if hmac.compare_digest(row["key_hash"], fingerprint):
                raise ValueError("Recovery requires a different operator key")
            if db.execute(
                "SELECT 1 FROM execution_retired_keys WHERE key_hash=?", (fingerprint,)
            ).fetchone():
                raise ValueError("Retired operator keys cannot be recovered")
            db.execute(
                "UPDATE execution_operator SET key_hash=?,generation=generation+1,revoked=0 WHERE id=1",
                (fingerprint,),
            )
            engine._halt(db, "OPERATOR_CAPABILITY_RECOVERED", now)
            engine.journal.event(
                db,
                now,
                "OPERATOR_RECOVERED",
                {"reason": reason, "generation": row["generation"] + 1},
            )
            return row["generation"] + 1

    def __init__(self, engine: ExecutionEngine, key: bytes):
        if type(engine) is not ExecutionEngine:
            raise ValueError("Only the offline execution engine is supported")
        key_hash = _key_hash(key)
        with engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
            if not row or row["revoked"] or not hmac.compare_digest(row["key_hash"], key_hash):
                raise ValueError("Operator authentication failed")
            self.journal_id = row["journal_id"]
            self.credential_generation = row["generation"]
        self.engine = engine
        self._key = key

    def review(self):
        """Read the exact revision/evidence to bind the next recovery request."""
        with self.engine.journal.read() as db:
            binding = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
            if (
                not binding
                or binding["revoked"]
                or binding["generation"] != self.credential_generation
                or binding["journal_id"] != self.journal_id
                or not hmac.compare_digest(binding["key_hash"], _key_hash(self._key))
            ):
                raise ValueError("Operator capability retired or unavailable")
        result = self.engine.journal.report()
        result["operator_journal_id"] = self.journal_id
        result["operator_credential_generation"] = self.credential_generation
        return result

    def apply(self, command: OperatorCommand, signature: str, *, now):
        _clock(now)
        body = _body(command)
        command = OperatorCommand.model_validate_json(body)
        if (
            type(signature) is not str
            or len(signature) != 64
            or any(c not in "0123456789abcdef" for c in signature)
            or not hmac.compare_digest(sign_command(command, self._key), signature)
        ):
            raise ValueError("Operator authentication failed")
        fingerprint = hashlib.sha256(body.encode()).hexdigest()
        journal = self.engine.journal
        with journal.write() as db:
            binding = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
            if (
                not binding
                or binding["revoked"]
                or binding["generation"] != self.credential_generation
                or command.credential_generation != binding["generation"]
                or binding["journal_id"] != self.journal_id
                or not hmac.compare_digest(binding["key_hash"], _key_hash(self._key))
                or command.journal_id != self.journal_id
            ):
                raise ValueError("Operator journal binding mismatch")
            old = db.execute(
                "SELECT * FROM execution_commands WHERE command_id=?", (command.command_id,)
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("Operator command identity conflict")
                # Authenticated repeat returns its original receipt, never reapplies it.
                return {**json.loads(old["result_json"]), "replayed": True}
            reason = None
            if now < command.issued_at:
                reason = "COMMAND_FROM_FUTURE"
            elif now >= command.expires_at:
                reason = "COMMAND_EXPIRED"
            elif command.action not in {
                "HALT",
                "REVOKE_KEY",
            } and command.expected_revision != journal.revision(db):
                reason = "OPERATOR_REVIEW_STALE"
            if reason is None:
                try:
                    self._execute(db, command, now)
                except ExecutionBlocked as exc:
                    reason = str(exc)
            result = {
                "status": "REJECTED" if reason else "APPLIED",
                "command_id": command.command_id,
                "action": command.action,
                "reason": reason,
                "replayed": False,
                "network_calls": False,
                "live_enabled": False,
            }
            journal.event(
                db,
                now,
                "OPERATOR_COMMAND",
                {"command": command.model_dump(mode="json"), "result": result},
            )
            result["revision"] = journal.revision(db)
            db.execute(
                "INSERT INTO execution_commands VALUES(?,?,?)",
                (command.command_id, fingerprint, json.dumps(result, sort_keys=True)),
            )
            return result

    def _execute(self, db, command, now):
        engine = self.engine
        if command.action == "HALT":
            # Safety reduction remains available even if review/config changed.
            engine._halt(db, command.reason, now)
        elif command.action == "RESUME":
            state = Ledger.model_validate_json(engine._control(db)["ledger_json"])
            if state.position:
                management = state.management
                if management is None or any(
                    timestamp is None
                    or not 0
                    <= (now - timestamp).total_seconds()
                    <= engine.settings.quote_max_age_seconds
                    for timestamp in (management.last_supervised_at, management.last_quote_at)
                ):
                    raise ExecutionBlocked("FRESH_POSITION_SUPERVISION_REQUIRED")
            engine._resume(db, command.reason, now)
        elif command.action == "ABANDON_PREPARED":
            engine._abandon_prepared(db, command.client_id, command.reason, now)
        elif command.action == "ACK_ALERT":
            row = db.execute(
                "SELECT * FROM execution_alerts WHERE event_sequence=?", (command.alert_sequence,)
            ).fetchone()
            if row is None:
                raise ExecutionBlocked("ALERT_NOT_FOUND")
            if row["acknowledged_at"]:
                raise ExecutionBlocked("ALERT_ALREADY_ACKNOWLEDGED")
            db.execute(
                "UPDATE execution_alerts SET acknowledged_at=?,actor=?,command_id=? WHERE event_sequence=?",
                (now.isoformat(), command.actor, command.command_id, command.alert_sequence),
            )
        else:
            if command.action == "ROTATE_KEY":
                row = db.execute("SELECT key_hash FROM execution_operator WHERE id=1").fetchone()
                if (
                    hmac.compare_digest(row["key_hash"], command.replacement_fingerprint)
                    or db.execute(
                        "SELECT 1 FROM execution_retired_keys WHERE key_hash=?",
                        (command.replacement_fingerprint,),
                    ).fetchone()
                ):
                    raise ExecutionBlocked("DIFFERENT_OPERATOR_KEY_REQUIRED")
                db.execute(
                    "INSERT INTO execution_retired_keys SELECT key_hash,?,generation FROM execution_operator WHERE id=1",
                    (now.isoformat(),),
                )
                db.execute(
                    "UPDATE execution_operator SET key_hash=?,generation=generation+1 WHERE id=1",
                    (command.replacement_fingerprint,),
                )
            else:
                db.execute(
                    "INSERT INTO execution_retired_keys SELECT key_hash,?,generation FROM execution_operator WHERE id=1",
                    (now.isoformat(),),
                )
                db.execute(
                    "UPDATE execution_operator SET revoked=1,generation=generation+1 WHERE id=1"
                )
            engine._halt(
                db,
                "OPERATOR_CAPABILITY_"
                + ("ROTATED" if command.action == "ROTATE_KEY" else "REVOKED"),
                now,
            )
