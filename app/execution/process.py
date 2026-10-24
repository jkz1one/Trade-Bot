"""Killable subprocess calls to the built-in durable fake venue only."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.execution.durable_fixture import DurableFixtureVenue, FixtureFault
from app.execution.models import Contract, Intent, Snapshot

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
TERMINATION_GRACE_SECONDS = 1


class FixtureProcessTimeout(TimeoutError):
    pass


class FixtureProcessFailed(RuntimeError):
    pass


class FixtureProcessProtocolError(RuntimeError):
    pass


class FixtureRequest(Contract):
    operation: Literal["accept", "snapshot"]
    path: str
    venue_id: str
    account_id: str
    now: datetime
    deadline_monotonic: float = Field(gt=0)
    parent_pid: int = Field(gt=0)
    intent: Intent | None = None
    fault: FixtureFault = "NONE"

    @model_validator(mode="after")
    def paired(self):
        if (self.operation == "accept") != (self.intent is not None):
            raise ValueError("Operation and intent do not match")
        return self


class FixtureResult(Contract):
    order_id: str | None = Field(default=None, min_length=1, max_length=128)
    snapshot: Snapshot | None = None


async def _terminate(process):
    def send(sig):
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    async def drain():
        while await process.stdout.read(65536):
            pass

    output = asyncio.create_task(drain())
    process.stdin.close()
    send(signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), TERMINATION_GRACE_SECONDS)
    except TimeoutError:
        pass
    finally:
        send(signal.SIGKILL)
        await process.wait()
        await output


async def _cleanup(process):
    task = asyncio.create_task(_terminate(process))
    cancelled = False
    # Even repeated cancellation cannot advance past cleanup or orphan the child.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            continue
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def run_fixture_process(
    venue: DurableFixtureVenue, *, now, intent=None, timeout_seconds, deadline_monotonic=None
):
    if type(venue) is not DurableFixtureVenue:
        raise ValueError("Only the built-in durable fixture venue is supported")
    if not 0 < timeout_seconds <= 30:
        raise ValueError("A bounded fixture process deadline is required")
    deadline_monotonic = min(
        deadline_monotonic or (time.monotonic() + timeout_seconds),
        time.monotonic() + timeout_seconds,
    )
    if deadline_monotonic <= time.monotonic():
        raise FixtureProcessTimeout("Fixture admission lease already expired")
    request = FixtureRequest(
        operation="accept" if intent is not None else "snapshot",
        path=str(venue.path),
        venue_id=venue.venue_id,
        account_id=venue.account_id,
        now=now,
        deadline_monotonic=deadline_monotonic,
        parent_pid=os.getpid(),
        intent=intent,
        fault=venue.fault,
    )
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise FixtureProcessProtocolError("Fixture request exceeded protocol limit")
    # Deliberately exclude broker/model secrets, settings and OAuth state from the child environment.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "app.execution.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    )
    process = None
    try:
        async with asyncio.timeout(max(0, deadline_monotonic - time.monotonic())):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            data = bytearray()
            while chunk := await process.stdout.read(4096):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise FixtureProcessProtocolError("Fixture response exceeded protocol limit")
            await process.wait()
            if process.returncode:
                raise FixtureProcessFailed("Fixture process failed")
            try:
                result = FixtureResult.model_validate_json(data)
            except ValueError:
                raise FixtureProcessProtocolError("Invalid fixture response") from None
            if intent is not None:
                if result.order_id is None or result.snapshot is not None:
                    raise FixtureProcessProtocolError("Invalid fixture acknowledgment envelope")
            elif (
                result.order_id is not None
                or result.snapshot is None
                or result.snapshot.account_id != venue.account_id
            ):
                raise FixtureProcessProtocolError("Invalid fixture snapshot envelope")
            return result
    except TimeoutError:
        raise FixtureProcessTimeout("Fixture process deadline exceeded") from None
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
