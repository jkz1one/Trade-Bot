"""Headless fixed options-market read worker. Outputs private evidence only."""

import asyncio
import os
import sys
import threading
import time

from app.domain.models import utc_now
from app.execution.market_read_worker import _watch
from app.execution.market_read_worker import connection as native_connection
from app.execution.market_reads import private_oauth
from app.options.read_capture import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    CaptureRequest,
    CaptureResult,
    CaptureProgress,
    PROGRESS_PREFIX,
    failure_evidence,
    policy_digest,
)
from app.options.read_gateway import OptionReadGateway, encoded


class ReadAuthorizationRequired(RuntimeError):
    """Existing headless authorization cannot complete; never open a login flow."""


async def authorization_required(*args):
    raise ReadAuthorizationRequired


def connection(policy):
    result = native_connection(policy)
    result.redirect_handler = authorization_required
    result.callback_handler = authorization_required
    return result


async def collect(request, *, progress=None):
    started = time.monotonic()
    gateway, observations, error, failure = None, [], None, None
    probe_report = None
    scope_rows, scope_error = [], None
    stage = "PRIVATE_AUTH"
    def note(value):
        nonlocal stage
        stage = value
        if progress is not None:
            progress(CaptureProgress(request_id=request.request_id, stage=stage,
                     completed_reads=sum(r.get('completed') is True for r in (*observations, *scope_rows))))
    try:
        note('PRIVATE_AUTH')
        private_oauth(request.policy.oauth_file)
        note('CONNECT')
        async with connection(request.policy).client() as client:
            gateway = OptionReadGateway(client)
            note('DISCOVER')
            if request.include_inventory or request.scope_requested or request.operation in {"INPUT_PROBE", "SCOPE_INPUT"}:
                await gateway.discover(include_inventory=True)
            else:
                await gateway.discover()
            if request.operation == "INPUT_PROBE":
                from app.options.input_probe import run, InputProbeIncomplete

                note('MARKET_READ')
                probe_report = await run(client, gateway.inventory, request.started_at, observations)
                if any(not row["completed"] for row in observations):
                    raise InputProbeIncomplete
            if request.operation == "SCOPE_INPUT":
                from app.options.scope_read import run
                note('MARKET_READ')
                await run(client, gateway.inventory, request.started_at, observations)
            if request.operation == "CAPTURE":
                note('VALIDATE_PLAN')
                plan = gateway.validate_plan(request.plan, request.schemas)
                async def ordinary_reads():
                    nonlocal error, failure
                    for call in plan.calls:
                        note('MARKET_READ')
                        at, tick = utc_now(), time.monotonic()
                        row = {
                            "label": call.label,
                            "tool": call.tool,
                            "attempted_at": at.isoformat(),
                            "completed": False,
                        }
                        observations.append(row)
                        try:
                            try:
                                raw, checked = await gateway.sample(call, request.schemas)
                            except Exception as exc:
                                # Intraday history is read before the books to
                                # preserve their original age. A failed history
                                # cannot suppress subsequent protection quotes.
                                # The capture remains FAILED; normalization alone
                                # decides whether complete market reads are usable.
                                if call.tool != 'get_equity_historicals' or call.label != 'history':
                                    raise
                                if error is None:
                                    error = type(exc).__name__
                                    failure = failure_evidence(exc, stage)
                                continue
                            if len(encoded([*observations, raw])) > 512 * 1024:
                                raise ValueError("Aggregate samples exceed bound")
                            row.update(
                                completed=True,
                                received_at=utc_now().isoformat(),
                                raw=raw,
                                output_schema_validated=checked,
                            )
                        finally:
                            row["elapsed_seconds"] = time.monotonic() - tick
                            note('MARKET_READ')
                async def index_reads():
                    nonlocal scope_error
                    from app.options.scope_read import run
                    try:
                        await run(client, gateway.inventory, request.started_at, scope_rows)
                    except Exception as exc:
                        scope_error = type(exc).__name__
                if request.scope_requested:
                    async with asyncio.TaskGroup() as group:
                        group.create_task(index_reads())
                        group.create_task(ordinary_reads())
                else:
                    await ordinary_reads()
            note('CLOSE')
    except Exception as exc:  # noqa: BLE001 -- sanitized failure evidence, never provider text
        error = type(exc).__name__
        failure = failure_evidence(exc, stage)
    return CaptureResult(
        request_id=request.request_id,
        policy_sha256=policy_digest(request.policy),
        operation=request.operation,
        started_at=request.started_at,
        collected_at=utc_now(),
        elapsed_seconds=time.monotonic() - started,
        status="FAILED" if error else "COMPLETE",
        schemas=gateway.schemas if gateway else None,
        plan=request.plan,
        observations=observations,
        error_class=error,
        failure=failure,
        input_probe=probe_report,
        scope_requested=request.scope_requested, scope_observations=scope_rows,
        scope_error_class=scope_error,
        inventory=gateway.inventory if gateway and request.include_inventory else None,
    )


def main():
    started = time.monotonic()
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            return 1
        request = CaptureRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid or time.monotonic() >= request.deadline_monotonic:
            return 1
        threading.Thread(target=_watch, args=(request,), daemon=True).start()
        def progress(value):
            elapsed = time.monotonic()-started
            value = value.model_copy(update={'elapsed_seconds': elapsed if 0 <= elapsed <= 120 else None})
            sys.stderr.buffer.write(PROGRESS_PREFIX + value.model_dump_json().encode() + b'\n')
            sys.stderr.buffer.flush()
        result = asyncio.run(collect(request, progress=progress))
        progress(CaptureProgress(request_id=request.request_id, stage='SERIALIZE',
                 completed_reads=sum(r.get('completed') is True for r in (*result.observations, *result.scope_observations))))
        data = result.model_dump_json().encode()
        if len(data) > MAX_RESPONSE_BYTES:
            return 1
        sys.stdout.buffer.write(data)
        return 0
    except Exception:  # noqa: BLE001 -- no credential/provider errors on stderr
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
