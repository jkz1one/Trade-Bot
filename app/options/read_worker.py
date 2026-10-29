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


async def collect(request):
    started = time.monotonic()
    gateway, observations, error, failure = None, [], None, None
    stage = "PRIVATE_AUTH"
    try:
        private_oauth(request.policy.oauth_file)
        stage = "CONNECT"
        async with connection(request.policy).client() as client:
            gateway = OptionReadGateway(client)
            stage = "DISCOVER"
            if request.include_inventory:
                await gateway.discover(include_inventory=True)
            else:
                await gateway.discover()
            if request.operation == "CAPTURE":
                stage = "VALIDATE_PLAN"
                plan = gateway.validate_plan(request.plan, request.schemas)
                for call in plan.calls:
                    stage = "MARKET_READ"
                    at, tick = utc_now(), time.monotonic()
                    row = {
                        "label": call.label,
                        "tool": call.tool,
                        "attempted_at": at.isoformat(),
                        "completed": False,
                    }
                    observations.append(row)
                    try:
                        raw, checked = await gateway.sample(call, request.schemas)
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
            stage = "CLOSE"
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
        inventory=gateway.inventory if gateway and request.include_inventory else None,
    )


def main():
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            return 1
        request = CaptureRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid or time.monotonic() >= request.deadline_monotonic:
            return 1
        threading.Thread(target=_watch, args=(request,), daemon=True).start()
        result = asyncio.run(collect(request))
        data = result.model_dump_json().encode()
        if len(data) > MAX_RESPONSE_BYTES:
            return 1
        sys.stdout.buffer.write(data)
        return 0
    except Exception:  # noqa: BLE001 -- no credential/provider errors on stderr
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
