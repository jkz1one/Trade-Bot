"""One bounded fixed local options child. No generic adapter or external tools."""

import asyncio
import json
import os
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context

from app.execution.process import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    FixtureProcessFailed,
    FixtureProcessProtocolError,
    FixtureProcessTimeout,
    _cleanup,
)
from app.options.process_models import OptionProcessResult, OptionRequest
from app.options.process_trace import OptionProcessDiagnostics, TraceReader
from app.options.runtime_timing import native_diagnostics
from app.options.runtime_timing import phase as timing_phase
from app.options.snapshot_worker import VERSION as SNAPSHOT_VERSION
from app.options.venue import DurableOptionVenue


class NativeAcceptNotStarted(FixtureProcessTimeout):
    """The local acceptance child was never started for this intent."""


async def _isolated_accept(venue, **request):
    # The owner loop can be busy committing another tick. The private loop
    # must launch, read, validate and reap the same child on the original lease.
    cancelled = Future()

    async def accept():
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()

        def cancel_operation(_):
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                if not loop.is_closed():
                    raise

        cancelled.add_done_callback(cancel_operation)
        if cancelled.done():
            raise asyncio.CancelledError
        with timing_phase("NATIVE_ACCEPT_TRANSPORT"):
            return await _run_option_process(venue, **request)

    def drive():
        return asyncio.run(accept())

    # Submit immediately. Waiting for the owner's next loop turn can itself
    # exhaust the lease. Copy its diagnostic context into this single operation.
    # History and publication may already occupy every default-executor thread.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="paper-venue-accept") as executor:
        worker = asyncio.get_running_loop().run_in_executor(executor, copy_context().run, drive)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled.set_result(None)
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled():
                worker.exception()
            raise


async def run_option_process(
    venue, *, now, timeout_seconds, intent=None, stock_intent=None, deadline=None
):
    accept = intent is not None or stock_intent is not None
    with timing_phase("NATIVE_ACCEPT" if accept else "NATIVE_SNAPSHOT"):
        run = _run_option_process
        if accept and type(venue) is DurableOptionVenue and venue.portfolio_policy is not None:
            timeout_at = time.monotonic() + timeout_seconds
            deadline = min(deadline, timeout_at) if deadline is not None else timeout_at
            run = _isolated_accept
        return await run(venue, now=now, timeout_seconds=timeout_seconds,
                         intent=intent, stock_intent=stock_intent, deadline=deadline)


async def _spawn_option_child(module, payload, env):
    # A fixed request that fits the kernel pipe can accompany the child at exec.
    # The child still validates it and checks its original lease before committing.
    # Use the existing async stream when the pipe cannot hold the entire request.
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as source:
        try:
            os.set_blocking(write_fd, False)
            try:
                buffered = os.write(write_fd, payload) == len(payload)
            except BlockingIOError:
                buffered = False
        finally:
            os.close(write_fd)
        return await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", module,
            stdin=source if buffered else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )


async def _run_option_process(
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
    module = "app.options.snapshot_worker" if snapshot_read else "app.options.worker"
    if not snapshot_read and time.monotonic() >= deadline:
        # No spawn task exists. A timeout once that task exists stays uncertain.
        raise NativeAcceptNotStarted("Local acceptance deadline expired before spawn")
    spawn = asyncio.create_task(_spawn_option_child(module, payload, env))
    child = None
    trace = TraceReader()
    trace_task = None
    phase = "SPAWN"
    validated = False
    try:
        spawn_phase = "NATIVE_SNAPSHOT_SPAWN" if snapshot_read else "NATIVE_ACCEPT_SPAWN"
        with timing_phase(spawn_phase, deadline=deadline):
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                child = await asyncio.shield(spawn)
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            trace_task = asyncio.create_task(trace.drain(child.stderr))
            if child.stdin is not None:
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
            validated = True
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
        elapsed = time.monotonic() - started
        if not validated:
            native_diagnostics(OptionProcessDiagnostics(phase, elapsed, trace.invalid, tuple(trace.records)))
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
            if validated:
                # A preloaded child may have exited before its trace reader first
                # runs. Reaping gives the reader a turn with the buffered stderr.
                # The recorded validation time and the original deadline stay fixed.
                native_diagnostics(OptionProcessDiagnostics(phase, elapsed, trace.invalid, tuple(trace.records)))
