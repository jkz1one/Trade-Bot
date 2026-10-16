"""Authenticated options recovery within the current owner and restore transaction."""

import hashlib
import hmac
import json
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.execution.operator import _key_hash
from app.options.engine import OptionExecution, clock
from app.options.operator_models import OptionsCommand


def body(command):
    command = OptionsCommand.model_validate(command.model_dump())
    return json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def sign(command, key):
    _key_hash(key)
    return hmac.new(key, body(command).encode(), hashlib.sha256).hexdigest()


def binding(db, key, population_id):
    row = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
    control = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
    config = json.loads(control[0])
    if (
        config["schema"] != "option-paper-execution-v1"
        or config["limits"]["population_id"] != population_id
        or row is None
        or row["revoked"]
        or not hmac.compare_digest(row["key_hash"], _key_hash(key))
    ):
        raise ValueError("Options operator authentication failed")
    return row


class OptionsControl:
    def __init__(self, engine, key):
        if type(engine) is not OptionExecution:
            raise ValueError("An owned options PAPER engine is required")
        self.engine, self.key = engine, key
        with engine.journal.read() as db:
            self._binding(db)

    def _binding(self, db):
        self.engine._control(db)
        return binding(db, self.key, self.engine.limits.population_id)

    @staticmethod
    def enroll(engine, key, *, now):
        if type(engine) is not OptionExecution:
            raise ValueError("An owned options PAPER engine is required")
        digest = _key_hash(key)
        with engine.journal.write() as db:
            engine._control(db)
            if db.execute("SELECT 1 FROM execution_operator WHERE id=1").fetchone():
                raise ValueError("Explicit new operator enrollment required")
            db.execute(
                "INSERT INTO execution_operator(id,journal_id,key_hash) VALUES(1,?,?)",
                (uuid4().hex, digest),
            )
            engine.journal.event(db, clock(now), "OPTIONS_OPERATOR_ENROLLED", {})

    def apply(self, command, signature, *, now):
        now = clock(now)
        wire = body(command)
        command = OptionsCommand.model_validate_json(wire)
        if (
            not isinstance(signature, str)
            or len(signature) != 64
            or any(c not in "0123456789abcdef" for c in signature)
            or not hmac.compare_digest(signature, sign(command, self.key))
        ):
            raise ValueError("Options operator authentication failed")
        digest = hashlib.sha256(wire.encode()).hexdigest()
        # Authenticated replays are read-only, including after the original expiry.
        with self.engine.journal.read() as db:
            b = self._binding(db)
            self._command_binding(command, b)
            old = self._old(db, command, digest)
            if old:
                return old
        with self.engine.journal.write() as db:
            b = self._binding(db)
            self._command_binding(command, b)
            old = self._old(db, command, digest)
            if old:
                return old
            reason = (
                "COMMAND_FROM_FUTURE"
                if now < command.issued_at
                else ("COMMAND_EXPIRED" if now >= command.expires_at else None)
            )
            if reason is None and command.action in {"RESUME", "RESET_LOSS_LOCK"}:
                runtime = getattr(self.engine, "_option_runtime", None)
                if runtime is not None and runtime.task is not None and not runtime.task.done():
                    reason = "OPTION_RUNTIME_CYCLE_IN_PROGRESS"
                else:
                    try:
                        if command.action == "RESET_LOSS_LOCK":
                            from app.options.loss_control import reset_reviewed

                            reset_reviewed(self.engine, db, command, now)
                        else:
                            self.engine._resume(
                                db,
                                command.reason,
                                expected_revision=command.expected_revision,
                                now=now,
                            )
                    except ExecutionBlocked as exc:
                        reason = str(exc)
            elif reason is None:
                self.engine._halt(db, command.reason, now)
                if command.action == "REVOKE_KEY":
                    db.execute(
                        "UPDATE execution_operator SET revoked=1,generation=generation+1 WHERE id=1"
                    )
            result = {
                **({"loss_family": command.loss_family} if command.loss_family is not None else {}),
                "status": "REJECTED" if reason else "APPLIED",
                "command_id": command.command_id,
                "action": command.action,
                "actor": command.actor,
                "review_reason": command.reason,
                "reason": reason,
                "replayed": False,
                "network_calls": False,
                "live_enabled": False,
            }
            self.engine.journal.event(
                db,
                now,
                "OPTIONS_OPERATOR_COMMAND",
                {"command": command.model_dump(mode="json"), "result": result},
            )
            result["revision"] = self.engine.journal.revision(db)
            db.execute(
                "INSERT INTO execution_commands VALUES(?,?,?)",
                (command.command_id, digest, json.dumps(result, sort_keys=True)),
            )
            return result

    def _command_binding(self, command, b):
        if (
            command.population_id != self.engine.limits.population_id
            or command.journal_id != b["journal_id"]
            or command.credential_generation != b["generation"]
        ):
            raise ValueError("Options operator command binding mismatch")

    @staticmethod
    def _old(db, command, digest):
        old = db.execute(
            "SELECT fingerprint,result_json FROM execution_commands WHERE command_id=?",
            (command.command_id,),
        ).fetchone()
        if old is None:
            return None
        if old["fingerprint"] != digest:
            raise ValueError("Options operator command identity conflict")
        return json.loads(old["result_json"]) | {"replayed": True}


def summary(db):
    row = db.execute("SELECT generation,revoked FROM execution_operator WHERE id=1").fetchone()
    return {
        "status": "NOT_ENROLLED" if row is None else "REVOKED" if row["revoked"] else "ENROLLED",
        "credential_generation": row["generation"] if row else None,
        "recent_commands": [
            json.loads(r[0])
            for r in db.execute(
                "SELECT result_json FROM execution_commands ORDER BY rowid DESC LIMIT 20"
            )
        ],
        "execution_authority": False,
    }
