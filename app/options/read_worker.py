"""Headless fixed options-market read worker. Outputs private evidence only."""

import asyncio
import os
import sys
import threading
import time

from app.domain.models import utc_now
from app.execution.market_read_worker import _watch, connection
from app.execution.market_reads import private_oauth
from app.options.read_capture import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    CaptureRequest,
    CaptureResult,
    policy_digest,
)
from app.options.read_gateway import OptionReadGateway, encoded


async def collect(request):
    started = time.monotonic()
    gateway, observations, error = None, [], None
    try:
        private_oauth(request.policy.oauth_file)
        async with connection(request.policy).client() as client:
            gateway = OptionReadGateway(client)
            await gateway.discover()
            if request.operation == "CAPTURE":
                plan = gateway.validate_plan(request.plan, request.schemas)
                for call in plan.calls:
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
    except Exception as exc:  # noqa: BLE001 -- sanitized failure evidence, never provider text
        error = type(exc).__name__
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
