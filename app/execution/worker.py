"""Single local fake-venue operation; no broker imports, tools or credentials."""

from __future__ import annotations

import os
import signal
import sys
import time

from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.process import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    FixtureRequest,
    FixtureResult,
)


def _stall(parent_pid):
    while True:
        if os.getppid() != parent_pid:
            os._exit(96)
        time.sleep(1)


def main():
    data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        return 1
    try:
        request = FixtureRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid:
            return 1
        venue = DurableFixtureVenue(request.path)
        if venue.venue_id != request.venue_id or venue.account_id != request.account_id:
            return 1
        if request.operation == "snapshot":
            if request.fault == "STALL_READ":
                _stall(request.parent_pid)
            result = FixtureResult(snapshot=venue.snapshot(request.now))
        else:
            if request.fault == "STALL_BEFORE_ACCEPT":
                _stall(request.parent_pid)
            order_id = venue._accept(
                request.intent, request.now, request.deadline_monotonic, request.parent_pid
            )
            # Faults occur only at the built-in fake venue; an accepted order is already durable.
            if request.fault == "IGNORE_TERM_AFTER_ACCEPT":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                _stall(request.parent_pid)
            if request.fault == "STALL_AFTER_ACCEPT":
                _stall(request.parent_pid)
            if request.fault == "CRASH_AFTER_ACCEPT":
                os._exit(95)
            if request.fault == "LOST_ACK":
                return 1
            if request.fault == "INVALID_ACK":
                sys.stdout.write('{"order_id": 123}')
                return 0
            if request.fault == "OVERSIZED_ACK":
                sys.stdout.write("x" * (MAX_RESPONSE_BYTES + 1))
                sys.stdout.flush()
                _stall(request.parent_pid)
            result = FixtureResult(order_id=order_id)
        sys.stdout.write(result.model_dump_json())
        return 0
    except (ValueError, OSError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
