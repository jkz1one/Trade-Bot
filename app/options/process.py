"""One bounded fixed local options child. No generic adapter or external tools."""

import asyncio
import json
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
from app.mixed.portfolio_venue import PortfolioPolicy, PortfolioVenueSnapshot
from app.mixed.stock_models import StockIntent, StockLimits
from app.options.lifecycle import OptionIntent, OptionVenueSnapshot
from app.options.models import Name, OptionRecord
from app.options.venue import DurableOptionVenue
from app.options.process_trace import OptionProcessDiagnostics, TraceReader
from app.options.snapshot_worker import VERSION as SNAPSHOT_VERSION


class OptionRequest(OptionRecord):
    operation: Literal["accept", "stock_accept", "snapshot"]
    path: str
    venue_id: Name
    account_id: Name
    population_id: Name
    now: datetime
    deadline_monotonic: float = Field(gt=0, allow_inf_nan=False)
    parent_pid: int = Field(gt=0, strict=True)
    intent: OptionIntent | None = None
    portfolio_policy: PortfolioPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    stock_limits: StockLimits | None = Field(default=None, exclude_if=lambda v: v is None)
    stock_intent: StockIntent | None = Field(default=None, exclude_if=lambda v: v is None)
    fault: FixtureFault = "NONE"

    @model_validator(mode="after")
    def paired(self):
        if (self.operation == "accept") != (self.intent is not None):
            raise ValueError("Operation and option intent must agree")
        if (self.operation == "stock_accept") != (self.stock_intent is not None):
            raise ValueError("Operation and stock intent must agree")
        if self.stock_intent is not None and self.stock_limits is None:
            raise ValueError("Stock worker request needs its frozen limits")
        return self


class OptionProcessResult(OptionRecord):
    order_id: Name | None = None
    snapshot: PortfolioVenueSnapshot | OptionVenueSnapshot | None = None


async def run_option_process(
    venue, *, now, timeout_seconds, intent=None, stock_intent=None, deadline=None
):
    if type(venue) is not DurableOptionVenue or not 0 < timeout_seconds <= 30:
        raise ValueError("Only the bounded built-in option fixture is supported")
    if stock_intent is not None and (intent is not None or venue.stock_limits is None):
        raise ValueError("One explicitly enrolled stock request required")
    started = time.monotonic()
    deadline = (
        min(deadline, time.monotonic() + timeout_seconds)
        if deadline is not None
        else time.monotonic() + timeout_seconds
    )
    request = OptionRequest(
        operation="stock_accept"
        if stock_intent is not None
        else "accept"
        if intent
        else "snapshot",
        path=str(venue.path),
        venue_id=venue.venue_id,
        account_id=venue.account_id,
        population_id=venue.population_id,
        now=now,
        deadline_monotonic=deadline,
        parent_pid=os.getpid(),
        intent=intent,
        stock_intent=stock_intent,
        stock_limits=venue.stock_limits,
        portfolio_policy=venue.portfolio_policy,
        fault=venue.fault,
    )
    snapshot_read = request.operation == "snapshot"
    payload = (
        json.dumps({
            "version": SNAPSHOT_VERSION,
            "path": request.path,
            "parent_pid": request.parent_pid,
            "deadline_monotonic": request.deadline_monotonic,
            "fault": "STALL_READ" if request.fault == "STALL_READ" else "NONE",
        }).encode()
        if snapshot_read else request.model_dump_json().encode()
    )
    if len(payload) > MAX_REQUEST_BYTES:
        raise FixtureProcessProtocolError("Option request exceeds fixed protocol")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "app.options.snapshot_worker" if snapshot_read else "app.options.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
    )
    child = None
    trace = TraceReader()
    trace_task = None
    phase = "SPAWN"
    try:
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            child = await asyncio.shield(spawn)
            trace_task = asyncio.create_task(trace.drain(child.stderr))
            phase = "REQUEST_WRITE"
            child.stdin.write(payload)
            await child.stdin.drain()
            child.stdin.close()
            phase = "RESPONSE_READ"
            data = bytearray()
            while chunk := await child.stdout.read(4096):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise FixtureProcessProtocolError("Option response exceeds fixed protocol")
            phase = "CHILD_EXIT"
            await child.wait()
            if child.returncode:
                raise FixtureProcessFailed("Option fixture child failed")
            try:
                phase = "RESPONSE_VALIDATE"
                if time.monotonic() >= deadline:
                    raise TimeoutError
                if snapshot_read:
                    record = json.loads(data)
                    if (type(record) is not dict or set(record) != {"version", "meta", "state"}
                            or record["version"] != SNAPSHOT_VERSION
                            or type(record["meta"]) is not str or type(record["state"]) is not str):
                        raise ValueError("Invalid snapshot record")
                    result = OptionProcessResult(snapshot=venue.snapshot_from_record(
                        record["meta"], record["state"], now
                    ))
                else:
                    result = OptionProcessResult.model_validate_json(data)
                # Native validation remains inside the original deadline. A late
                # read cannot become an accepted snapshot merely because it is local.
                if time.monotonic() >= deadline:
                    raise TimeoutError
            except (ValueError, KeyError, TypeError):
                raise FixtureProcessProtocolError("Invalid option fixture response") from None
            if intent is not None or stock_intent is not None:
                if result.order_id is None or result.snapshot is not None:
                    raise FixtureProcessProtocolError("Invalid option acknowledgment")
            elif (
                result.order_id is not None
                or result.snapshot is None
                or result.snapshot.venue_id != venue.venue_id
                or result.snapshot.account_id != venue.account_id
                or result.snapshot.population_id != venue.population_id
                or result.snapshot.stock_limits != venue.stock_limits
                or getattr(result.snapshot, "portfolio_policy", None) != venue.portfolio_policy
            ):
                raise FixtureProcessProtocolError("Invalid option snapshot binding")
            return result
    except TimeoutError:
        failure = FixtureProcessTimeout("Option child deadline exceeded")
        # Freeze what the parent observed before cleanup; missing progress does
        # not prove the child never reached a stage (the event loop may be late).
        failure.option_process_diagnostics = OptionProcessDiagnostics(
            phase, time.monotonic() - started, trace.invalid, tuple(trace.records)
        )
        raise failure from None
    finally:
        if child is None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                child = spawn.result()
        try:
            if child is not None:
                if trace_task is None:
                    trace_task = asyncio.create_task(trace.drain(child.stderr))
                await _cleanup(child)
        finally:
            if trace_task is not None:
                trace_task.cancel()
                await asyncio.gather(trace_task, return_exceptions=True)
