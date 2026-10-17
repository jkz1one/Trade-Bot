"""Opt-in native-TLS fixture control transport. Never an order/model/broker API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import stat
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError, field_validator
from starlette.requests import ClientDisconnect

from app.domain.models import utc_now
from app.execution.engine import ExecutionBlocked, ExecutionEngine, _clock
from app.execution.models import Contract
from app.execution.operator import OperatorCommand, OperatorControl


class ControlAPIConfig(Contract):
    origin: str
    max_body_bytes: int = Field(default=16384, gt=0, le=16384, strict=True)
    body_timeout_seconds: float = Field(default=5, gt=0, le=10)
    max_inflight: int = Field(default=4, gt=0, le=8, strict=True)

    @field_validator("origin")
    @classmethod
    def https_origin(cls, value):
        parsed = urlsplit(value)
        if (
            not value.isascii()
            or any(c.isspace() for c in value)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or "*" in parsed.netloc
            or "\\" in parsed.netloc
            or parsed.netloc.endswith(":")
        ):
            raise ValueError("An exact native HTTPS origin is required")
        return "https://" + parsed.netloc.lower()


class SignedCommand(Contract):
    command: OperatorCommand
    signature: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


def _secret(path):
    """No symlink/FIFO, broad permissions, huge reads or default credentials."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
            or info.st_size not in {64, 65}
        ):
            raise ValueError("Private owner-only secret file required")
        value = os.read(fd, 66).decode("ascii")
        if len(value) == 65 and value.endswith("\n"):
            value = value[:-1]
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("A 32-byte lowercase hex secret is required")
        return value
    finally:
        os.close(fd)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Nonfinite JSON value")


async def _finish_work(function, *args, **kwargs):
    """Retain bounded admission until local work finishes, even after repeated cancel."""
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 -- drain the local result, then preserve cancellation
                break
        if work.done() and not work.cancelled():
            work.exception()
        raise


def create_control_app(engine, config, *, operator_key_file, read_token_file, clock=utc_now):
    if type(engine) is not ExecutionEngine:
        raise ValueError("Only the built-in offline execution engine is supported")
    config = ControlAPIConfig.model_validate(config.model_dump())
    # Do not resolve symlinks before the no-follow credential open.
    key_path = Path(operator_key_file).expanduser().absolute()
    token_path = Path(read_token_file).expanduser().absolute()
    _clock(clock())

    def credentials():
        key, token = _secret(key_path), _secret(token_path)
        if hmac.compare_digest(key, token):
            raise ValueError("Read and signing credentials must be separate")
        return bytes.fromhex(key), token

    key, _ = credentials()
    # Explicit provisioning only: startup never enrolls, resumes or migrates state.
    OperatorControl(engine, key).review_summary(now=clock())
    capacity = asyncio.Semaphore(config.max_inflight)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def error(code, reason):
        return JSONResponse({"status": "UNAVAILABLE", "reason": reason}, status_code=code)

    class Boundary:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "lifespan":
                await self.app(scope, receive, send)
                return
            if scope["type"] != "http":
                await send({"type": "websocket.close", "code": 1008})
                return
            request = Request(scope, receive)

            async def private_send(message):
                if message["type"] == "http.response.start":
                    private = {
                        b"cache-control": b"no-store",
                        b"x-content-type-options": b"nosniff",
                        b"x-frame-options": b"DENY",
                        b"referrer-policy": b"no-referrer",
                        b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                    }
                    message = {
                        **message,
                        "headers": [
                            (k, v) for k, v in message["headers"] if k.lower() not in private
                        ]
                        + list(private.items()),
                    }
                await send(message)

            # Raw forwarding headers cannot provide transport or origin authority.
            names = [name.lower() for name, _ in scope["headers"]]
            result = None
            if any(name == b"forwarded" or name.startswith(b"x-forwarded-") for name in names):
                result = error(400, "FORWARDED_HEADERS_REJECTED")
            elif any(
                names.count(name) > 1
                for name in (
                    b"host",
                    b"authorization",
                    b"origin",
                    b"content-type",
                    b"content-length",
                )
            ):
                result = error(400, "AMBIGUOUS_HEADERS")
            elif scope["scheme"] != "https":
                result = error(426, "HTTPS_REQUIRED")
            elif request.headers.get("host", "").lower() != urlsplit(config.origin).netloc:
                result = error(421, "ORIGIN_MISMATCH")
            elif request.headers.get("origin", config.origin) != config.origin:
                result = error(403, "ORIGIN_MISMATCH")
            elif request.headers.get("sec-fetch-site") == "cross-site":
                result = error(403, "CROSS_SITE_REJECTED")
            elif capacity.locked():
                result = error(429, "CONTROL_BUSY")
            else:
                # Keep admission around the whole ASGI call, including cancelled thread cleanup.
                async with capacity:
                    try:
                        _, token = await _finish_work(credentials)
                    except (OSError, ValueError, UnicodeError):
                        result = error(503, "CONTROL_CREDENTIALS_UNAVAILABLE")
                    else:
                        auth = request.headers.get("authorization", "")
                        if not hmac.compare_digest(
                            hashlib.sha256(auth.encode()).digest(),
                            hashlib.sha256(("Bearer " + token).encode()).digest(),
                        ):
                            result = error(401, "AUTHENTICATION_REQUIRED")
                        else:
                            await self.app(scope, receive, private_send)
                            return
            await result(scope, receive, private_send)

    app.add_middleware(Boundary)

    def operator():
        key, _ = credentials()
        return OperatorControl(engine, key)

    @app.get("/v1/review")
    async def review():
        try:
            data = await _finish_work(lambda: operator().review_summary(now=clock()))
            payload = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
            if len(payload) > 65536:
                return error(503, "CONTROL_REVIEW_TOO_LARGE")
            return JSONResponse(data)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, ExecutionBlocked):
            return error(503, "CONTROL_STATE_UNAVAILABLE")

    @app.post("/v1/commands")
    async def commands(request: Request):
        if (
            request.headers.get("content-type", "").lower()
            not in {"application/json", "application/json; charset=utf-8"}
            or request.headers.get("content-encoding", "identity") != "identity"
        ):
            return error(415, "JSON_REQUIRED")
        length = request.headers.get("content-length")
        if length is not None and (not length.isascii() or not length.isdecimal()):
            return error(400, "INVALID_CONTENT_LENGTH")
        if length is not None and (len(length) > 6 or int(length) > config.max_body_bytes):
            return error(413, "COMMAND_TOO_LARGE")
        body = bytearray()
        try:
            async with asyncio.timeout(config.body_timeout_seconds):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > config.max_body_bytes:
                        return error(413, "COMMAND_TOO_LARGE")
                    body.extend(chunk)
        except TimeoutError:
            return error(408, "COMMAND_BODY_TIMEOUT")
        except ClientDisconnect:
            return error(400, "COMMAND_BODY_INCOMPLETE")
        try:
            raw = json.loads(
                body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_constant
            )
            envelope = SignedCommand.model_validate(raw)
        except (ValueError, TypeError, UnicodeError, RecursionError, ValidationError):
            return error(400, "INVALID_COMMAND")
        try:

            def apply():
                control = operator()
                # Reject changed configuration/restore authority before exposing a write boundary.
                control.review_summary(now=clock())
                return control.apply(envelope.command, envelope.signature, now=clock())

            data = await _finish_work(apply)
            return JSONResponse(data, status_code=200 if data["status"] == "APPLIED" else 409)
        except ValueError:
            return error(403, "COMMAND_AUTHORITY_REJECTED")
        except (OSError, sqlite3.Error, ExecutionBlocked, KeyError, TypeError):
            return error(503, "CONTROL_STATE_UNAVAILABLE")

    return app
