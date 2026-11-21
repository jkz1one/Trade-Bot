from __future__ import annotations

import asyncio
import json
import os
import signal
import sys

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.agent.trader import AgentRun
from app.domain.models import TradeDecision


MAX_RESPONSE_BYTES = 128 * 1024
TERMINATION_GRACE_SECONDS = 2


class ModelProcessTimeout(TimeoutError):
    pass


class ModelProcessProtocolError(RuntimeError):
    pass


class ModelProcessFailed(RuntimeError):
    pass


class ModelProcessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: TradeDecision
    input_tokens: StrictInt = Field(ge=0)
    output_tokens: StrictInt = Field(ge=0)
    error: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


async def _terminate(process):
    # The child owns a new process group. No parent/broker process is signalled.
    def send(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    async def discard_output():
        while await process.stdout.read(65536):
            pass

    # Reaping must not deadlock on an unread/full stdout pipe after protocol failure.
    drain = asyncio.create_task(discard_output())
    process.stdin.close()
    send(signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), TERMINATION_GRACE_SECONDS)
    except TimeoutError:
        pass
    finally:
        send(signal.SIGKILL)
        await process.wait()  # Reap the process before allowing a future cycle.
        await drain


async def _cleanup(process):
    task = asyncio.create_task(_terminate(process))
    cancelled = False
    # Repeated cancellation must not orphan the child while cleanup is pending.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            continue
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def run_model_process(model, packet, *, timeout_seconds, request_timeout_seconds,
                            _command=None):
    """One tool-less model turn in a killable child; no broker/database handles.

    _command is an internal failure-injection seam, never exposed through settings/CLI.
    The deadline includes process startup, SDK imports, request and response parsing.
    """
    command = _command or (sys.executable, "-m", "app.agent.worker")
    payload = json.dumps({"model": model, "packet": packet.model_dump(mode="json"),
                          "request_timeout_seconds": request_timeout_seconds}).encode()
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    ))
    process = None
    try:
        async with asyncio.timeout(timeout_seconds):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            data = bytearray()
            while chunk := await process.stdout.read(4096):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ModelProcessProtocolError("Model response exceeded protocol limit")
            await process.wait()
            if process.returncode:
                raise ModelProcessFailed("Model process exited without a valid response")
            try:
                result = ModelProcessResult.model_validate_json(data)
            except Exception as exc:
                raise ModelProcessProtocolError("Invalid model process response") from exc
            if result.error:
                # An error envelope cannot smuggle an executable proposal or invented usage.
                from app.agent.trader import fail_closed_agent_run
                run = fail_closed_agent_run(RuntimeError())
                decision = run.decision.model_copy(update={"risks": [f"Agent failure: {result.error}"]})
                return AgentRun(decision, error=result.error)
            return AgentRun(result.decision, result.input_tokens, result.output_tokens)
    except TimeoutError as exc:
        raise ModelProcessTimeout("Model process deadline exceeded") from exc
    finally:
        if process is None:
            # Cancellation during process creation can still leave a newly spawned child.
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            await _cleanup(process)
