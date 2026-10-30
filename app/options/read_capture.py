"""Bounded fixed-process schema/sample acquisition; no feed or execution authority."""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from app.domain.models import utc_now
from app.execution.market_reads import market_read_lease, private_oauth
from app.execution.process import _cleanup
from app.options.models import OptionRecord
from app.options.read_gateway import ENDPOINT, CapturePlan, ReadSchemas, encoded

MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024

OAuthFailure = Literal[
    "invalid_request",
    "invalid_client",
    "invalid_grant",
    "unauthorized_client",
    "unsupported_grant_type",
    "invalid_scope",
    "access_denied",
    "server_error",
    "temporarily_unavailable",
]


class FailureCause(OptionRecord):
    error_class: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    http_status: int | None = Field(
        default=None, ge=100, le=599, strict=True, exclude_if=lambda v: v is None
    )
    oauth_error: OAuthFailure | None = Field(default=None, exclude_if=lambda v: v is None)


class CaptureFailure(OptionRecord):
    stage: Literal[
        "PRIVATE_AUTH", "CONNECT", "DISCOVER", "VALIDATE_PLAN", "MARKET_READ", "CLOSE", "PARENT"
    ]
    causes: tuple[FailureCause, ...] = Field(min_length=1, max_length=16)
    truncated: bool = Field(default=False, strict=True)


def failure_evidence(exc, stage):
    """Bounded class/status codes only; never serialize messages, URLs or headers."""
    import httpx2

    pending, seen, causes, truncated = [(exc, 0)], set(), [], False
    while pending and len(causes) < 16:
        current, depth = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        status, oauth_error = None, None
        if isinstance(current, httpx2.HTTPStatusError):
            candidate = current.response.status_code
            if type(candidate) is int and 100 <= candidate <= 599:
                status = candidate
            try:
                body = current.response.content
                value = json.loads(body) if len(body) <= 8192 else None
                code = value.get("error") if isinstance(value, dict) else None
                if isinstance(code, str) and code in OAuthFailure.__args__:
                    oauth_error = code
            except (ValueError, RuntimeError):
                pass
        causes.append(
            FailureCause(
                error_class=type(current).__name__, http_status=status, oauth_error=oauth_error
            )
        )
        children = list(current.exceptions[:17]) if isinstance(current, BaseExceptionGroup) else []
        linked = current.__cause__ or current.__context__
        if linked is not None:
            children.append(linked)
        if depth >= 4:
            truncated |= bool(children)
        else:
            pending.extend((child, depth + 1) for child in children)
            if len(pending) > 16:
                truncated = True
                pending = pending[:16]
    return CaptureFailure(stage=stage, causes=tuple(causes), truncated=truncated or bool(pending))


class CapturePolicy(OptionRecord):
    endpoint: Literal[ENDPOINT] = ENDPOINT
    redirect_uri: Literal["http://127.0.0.1:8765/callback"] = "http://127.0.0.1:8765/callback"
    oauth_file: str = Field(min_length=1, max_length=4096)
    timeout_seconds: float = Field(gt=0, le=30, strict=True)

    @field_validator("oauth_file")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("Explicit absolute existing OAuth path required")
        return value


class CaptureRequest(OptionRecord):
    operation: Literal["DISCOVER", "CAPTURE", "INPUT_PROBE"]
    policy: CapturePolicy
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    started_at: datetime
    parent_pid: int = Field(gt=0, strict=True)
    deadline_monotonic: float = Field(gt=0)
    schemas: ReadSchemas | None = None
    plan: CapturePlan | None = None
    include_inventory: bool = Field(default=False, strict=True, exclude_if=lambda v: not v)

    @model_validator(mode="after")
    def paired(self):
        if self.include_inventory and self.operation != "DISCOVER":
            raise ValueError("Inventory is discovery-only, never a market tool call")
        if (self.operation == "CAPTURE") != (
            self.schemas is not None and self.plan is not None
        ) or (self.operation != "CAPTURE" and (self.schemas is not None or self.plan is not None)):
            raise ValueError("Capture requires exactly its reviewed schema and plan")
        return self


class CaptureResult(OptionRecord):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["DISCOVER", "CAPTURE", "INPUT_PROBE"]
    started_at: datetime
    collected_at: datetime
    elapsed_seconds: float = Field(ge=0, le=30)
    status: Literal["COMPLETE", "FAILED"]
    execution_authority: Literal[False] = False
    normalized_data_verified: Literal[False] = False
    schemas: ReadSchemas | None = None
    plan: CapturePlan | None = None
    observations: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=8)
    error_class: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    failure: CaptureFailure | None = Field(default=None, exclude_if=lambda v: v is None)
    input_probe: dict[str, JsonValue] | None = Field(default=None, exclude_if=lambda v: v is None)
    inventory: dict[str, JsonValue] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coherence(self):
        if self.input_probe is not None and (
            self.operation != "INPUT_PROBE" or len(encoded(self.input_probe)) > 64 * 1024
        ):
            raise ValueError("Bounded input-probe report required")
        if self.inventory is not None:
            from app.options.capability_inventory import MAX_INVENTORY_BYTES

            if self.operation != "DISCOVER" or len(encoded(self.inventory)) > MAX_INVENTORY_BYTES:
                raise ValueError("Bounded discovery-only inventory required")
        if (self.status == "FAILED") != (self.error_class is not None):
            raise ValueError("Capture status and failure evidence must agree")
        if self.failure is not None and (
            self.status != "FAILED" or self.failure.causes[0].error_class != self.error_class
        ):
            raise ValueError("Failure diagnostics must match the failed result")
        if self.operation == "DISCOVER" and (self.plan is not None or self.observations):
            raise ValueError("Discovery cannot report tool calls")
        if self.operation == "CAPTURE" and self.plan is None:
            raise ValueError("Capture must retain its reviewed plan")
        if self.operation == "INPUT_PROBE" and self.plan is not None:
            raise ValueError("Input probe uses only its fixed reviewed calls")
        return self


def policy_digest(policy):
    import hashlib

    return hashlib.sha256(encoded(policy.model_dump(mode="json"))).hexdigest()


async def _read(request):
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Capture request exceeds protocol bound")
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "app.options.read_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ},
        )
    )
    child = None
    try:
        async with asyncio.timeout(max(0, request.deadline_monotonic - time.monotonic())):
            child = await asyncio.shield(spawn)
            child.stdin.write(payload)
            await child.stdin.drain()
            child.stdin.close()
            output = bytearray()
            while chunk := await child.stdout.read(4096):
                output.extend(chunk)
                if len(output) > MAX_RESPONSE_BYTES:
                    raise ValueError("Capture response exceeds protocol bound")
            await child.wait()
            if child.returncode:
                raise ValueError("Capture child failed")
            return CaptureResult.model_validate_json(output)
    finally:
        if child is None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                child = spawn.result()
        if child is not None:
            await _cleanup(child)


async def collect(policy, *, schemas=None, plan=None, clock_source=utc_now,
                  include_inventory=False, input_probe=False):
    policy = CapturePolicy.model_validate(policy.model_dump(warnings=False))
    with market_read_lease(policy.oauth_file):
        return await _collect_owned(policy, schemas=schemas, plan=plan, clock_source=clock_source,
                                    include_inventory=include_inventory, input_probe=input_probe)


async def _collect_owned(policy, *, schemas, plan, clock_source, include_inventory=False,
                         input_probe=False):
    # Parent orchestration only. The read child imports protocol models from this
    # module and must not rebuild the execution engine just to decode a request.
    from app.options.engine import clock

    if input_probe and (schemas is not None or plan is not None or include_inventory):
        raise ValueError("Input probe cannot accompany another operation")
    private_oauth(policy.oauth_file)
    started = clock(clock_source())
    request = CaptureRequest(
        operation="INPUT_PROBE" if input_probe else ("CAPTURE" if plan is not None else "DISCOVER"),
        policy=policy,
        request_id=uuid4().hex,
        started_at=started,
        parent_pid=os.getpid(),
        deadline_monotonic=time.monotonic() + policy.timeout_seconds,
        schemas=schemas,
        plan=plan,
        include_inventory=include_inventory,
    )
    result = await _read(request)
    finished = clock(clock_source())
    if (
        result.request_id != request.request_id
        or result.operation != request.operation
        or result.policy_sha256 != policy_digest(policy)
        or result.started_at != started
        or not started <= result.collected_at <= finished
        or result.elapsed_seconds > policy.timeout_seconds
        or result.plan != request.plan
    ):
        raise ValueError("Capture identity, policy, operation, timing or plan mismatch")
    if input_probe:
        from app.options.input_probe import summary, validate_observations

        validate_observations(result.observations, started, complete=result.status == "COMPLETE",
                              expected_calendar_days=1)
        if result.status == "COMPLETE" and result.input_probe is None:
            raise ValueError("Completed input probe lacks its report")
        if result.input_probe is not None and result.input_probe != summary(result.observations):
            raise ValueError("Input probe report does not match original observations")
    if result.status == "COMPLETE":
        if include_inventory != (result.inventory is not None):
            raise ValueError("Requested capability inventory coverage mismatch")
        if result.schemas is None or result.error_class is not None:
            raise ValueError("Completed capture lacks schema evidence")
        if plan is not None and (
            result.schemas.sha256 != schemas.sha256 or len(result.observations) != len(plan.calls)
        ):
            raise ValueError("Completed capture lacks exact call/schema coverage")
    if plan is not None:
        for i, row in enumerate(result.observations):
            if (
                i >= len(plan.calls)
                or row.get("label") != plan.calls[i].label
                or row.get("tool") != plan.calls[i].tool
                or (
                    result.status == "COMPLETE"
                    and (row.get("completed") is not True or "raw" not in row)
                )
            ):
                raise ValueError("Capture call identity or completion mismatch")
    return result
