"""Authenticated revision review and signed inbox transport; never runs an owner."""

import hmac
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import Field

from app.execution import restore
from app.execution.control_api import _secret
from app.options.models import OptionRecord
from app.options.operator import binding, sign
from app.options.operator_inbox import read, save
from app.options.operator_models import OptionsCommand, SignedOptionsCommand


class LimitChange(OptionRecord):
    review: SignedOptionsCommand
    max_plays: int = Field(strict=True, ge=0, le=2)
    reason: str = Field(min_length=1, max_length=300)


def install(app, authenticate, observer, journal, key_file, clock):
    path = Path(journal)
    if not Path(key_file).is_absolute():
        raise ValueError("Absolute private operator key required")

    def key():
        return bytes.fromhex(_secret(key_file))

    def reviewed(secret):
        now = clock()
        with observer.read() as db:
            bound = binding(db, secret, observer.population_id)
            if restore.status(db, restore.authority_path(path))["status"] != "VERIFIED":
                raise ValueError("Verified restore authority required")
            report = observer._snapshot(db, now, 5, None, "ALL")
            if report.get("schema") != "mixed-portfolio-observer-v2":
                raise ValueError("Portfolio controls require v2 enrollment")
            return bound, report

    @app.get("/admin/review", dependencies=[Depends(authenticate)])
    def review():
        try:
            secret = key()
            bound, report = reviewed(secret)
            now = clock()
            command = OptionsCommand(
                journal_id=bound["journal_id"],
                population_id=observer.population_id,
                credential_generation=bound["generation"],
                command_id=uuid4().hex,
                actor="authenticated dashboard",
                action="SET_MAX_PLAYS",
                max_plays=report["max_plays"],
                reason="Review current entry limit",
                expected_revision=report["revision"],
                issued_at=now,
                expires_at=now + timedelta(seconds=60),
            )
            return {
                "review": SignedOptionsCommand(
                    command=command, signature=sign(command, secret)
                ).model_dump(mode="json"),
                "max_plays": report["max_plays"],
                "occupied_plays": report["occupied_plays"],
                "revision": report["revision"],
            }
        except (OSError, ValueError):
            raise HTTPException(503, "Operator review unavailable") from None

    @app.post("/admin/max-plays", dependencies=[Depends(authenticate)])
    async def change(request: Request):
        if (
            request.headers.get("content-type", "").split(";")[0] != "application/json"
            or request.headers.get("x-portfolio-review") != "1"
        ):
            raise HTTPException(403, "Explicit reviewed JSON request required")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Same-origin operator request required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, "Operator request too large")
        try:
            value = LimitChange.model_validate_json(raw)
            secret = key()
            command = value.review.command
            if not hmac.compare_digest(value.review.signature, sign(command, secret)):
                raise ValueError("Review signature changed")
            bound, report = reviewed(secret)
            if (command.journal_id, command.population_id, command.credential_generation) != (
                bound["journal_id"],
                observer.population_id,
                bound["generation"],
            ):
                raise ValueError("Review identity changed")
            if not command.issued_at <= clock() < command.expires_at:
                raise HTTPException(409, "Review expired; review current state again")
            if command.expected_revision != report["revision"]:
                raise HTTPException(409, "Account changed; review current state again")
            command = OptionsCommand.model_validate(
                {**command.model_dump(), "max_plays": value.max_plays, "reason": value.reason}
            )
            signed = SignedOptionsCommand(command=command, signature=sign(command, secret))
            destination = path.parent / "operator-inbox" / (command.command_id + ".json")
            try:
                save(destination, signed.model_dump(mode="json"))
            except FileExistsError:
                if SignedOptionsCommand.model_validate_json(read(destination)) != signed:
                    raise ValueError("Command identity conflict") from None
            return {
                "status": "QUEUED",
                "command_id": command.command_id,
                "max_plays": value.max_plays,
                "live_enabled": False,
                "network_calls": False,
            }
        except (OSError, ValueError):
            raise HTTPException(422, "Invalid or unavailable reviewed operator request") from None

    @app.get("/admin/receipts/{command_id}", dependencies=[Depends(authenticate)])
    def receipt(command_id: str):
        if len(command_id) != 32 or any(c not in "abcdef0123456789" for c in command_id):
            raise HTTPException(422, "Invalid command identity")
        try:
            binding_key = key()
            reviewed(binding_key)
            return json.loads(read(path.parent / "operator-receipts" / (command_id + ".json")))
        except FileNotFoundError:
            return {"result": {"status": "PENDING"}}
        except (OSError, ValueError):
            raise HTTPException(503, "Operator receipt unavailable") from None
