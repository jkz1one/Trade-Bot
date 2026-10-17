"""One bounded fixed local options child. No generic adapter or external tools."""

import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.execution.durable_fixture import FixtureFault
from app.execution.process import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    FixtureProcessFailed,
    FixtureProcessProtocolError,
    FixtureProcessTimeout,
    _cleanup,
)
from app.options.lifecycle import OptionIntent, OptionVenueSnapshot
from app.options.models import Name, OptionRecord
from app.options.venue import DurableOptionVenue


class OptionRequest(OptionRecord):
    operation: Literal["accept", "snapshot"]
    path: str
    venue_id: Name
    account_id: Name
    population_id: Name
    now: datetime
    deadline_monotonic: float = Field(gt=0, allow_inf_nan=False)
    parent_pid: int = Field(gt=0, strict=True)
    intent: OptionIntent | None = None
    fault: FixtureFault = "NONE"

    @model_validator(mode="after")
    def paired(self):
        if (self.operation == "accept") != (self.intent is not None):
            raise ValueError("Operation and option intent must agree")
        return self


class OptionProcessResult(OptionRecord):
    order_id: Name | None = None
    snapshot: OptionVenueSnapshot | None = None


async def run_option_process(venue, *, now, timeout_seconds, intent=None, deadline=None):
    if type(venue) is not DurableOptionVenue or not 0 < timeout_seconds <= 30:
        raise ValueError("Only the bounded built-in option fixture is supported")
    deadline = (
        min(deadline, time.monotonic() + timeout_seconds)
        if deadline is not None
        else time.monotonic() + timeout_seconds
    )
    request = OptionRequest(
        operation="accept" if intent else "snapshot",
        path=str(venue.path),
        venue_id=venue.venue_id,
        account_id=venue.account_id,
        population_id=venue.population_id,
        now=now,
        deadline_monotonic=deadline,
        parent_pid=os.getpid(),
        intent=intent,
        fault=venue.fault,
    )
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise FixtureProcessProtocolError("Option request exceeds fixed protocol")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "app.options.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    )
    child = None
    try:
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            child = await asyncio.shield(spawn)
            child.stdin.write(payload)
            await child.stdin.drain()
            child.stdin.close()
            data = bytearray()
            while chunk := await child.stdout.read(4096):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise FixtureProcessProtocolError("Option response exceeds fixed protocol")
            await child.wait()
            if child.returncode:
                raise FixtureProcessFailed("Option fixture child failed")
            try:
                result = OptionProcessResult.model_validate_json(data)
            except ValueError:
                raise FixtureProcessProtocolError("Invalid option fixture response") from None
            if intent is not None:
                if result.order_id is None or result.snapshot is not None:
                    raise FixtureProcessProtocolError("Invalid option acknowledgment")
            elif (
                result.order_id is not None
                or result.snapshot is None
                or result.snapshot.venue_id != venue.venue_id
                or result.snapshot.account_id != venue.account_id
                or result.snapshot.population_id != venue.population_id
            ):
                raise FixtureProcessProtocolError("Invalid option snapshot binding")
            return result
    except TimeoutError:
        raise FixtureProcessTimeout("Option child deadline exceeded") from None
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
