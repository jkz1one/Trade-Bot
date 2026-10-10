"""Fixed private option-fixture protocol. No broker imports or credentials."""

import os
import signal
import sys

from app.execution.process import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES
from app.execution.worker import _stall
from app.options.process import OptionProcessResult, OptionRequest
from app.options.venue import DurableOptionVenue


def main():
    data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        return 1
    try:
        request = OptionRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid:
            return 1
        venue = DurableOptionVenue(request.path)
        if (venue.venue_id, venue.account_id, venue.population_id) != (
            request.venue_id,
            request.account_id,
            request.population_id,
        ):
            return 1
        if request.operation == "snapshot":
            if request.fault == "STALL_READ":
                _stall(request.parent_pid)
            result = OptionProcessResult(snapshot=venue.snapshot(request.now))
        else:
            if request.fault == "STALL_BEFORE_ACCEPT":
                _stall(request.parent_pid)
            order_id = venue._accept(
                request.intent, request.now, request.deadline_monotonic, request.parent_pid
            )
            if request.fault == "IGNORE_TERM_AFTER_ACCEPT":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if request.fault in {"STALL_AFTER_ACCEPT", "IGNORE_TERM_AFTER_ACCEPT"}:
                _stall(request.parent_pid)
            if request.fault == "CRASH_AFTER_ACCEPT":
                os._exit(95)
            if request.fault == "LOST_ACK":
                return 1
            if request.fault == "INVALID_ACK":
                sys.stdout.write('{"order_id":123}')
                return 0
            if request.fault == "OVERSIZED_ACK":
                sys.stdout.write("x" * (MAX_RESPONSE_BYTES + 1))
                sys.stdout.flush()
                _stall(request.parent_pid)
            result = OptionProcessResult(order_id=order_id)
        sys.stdout.write(result.model_dump_json())
        return 0
    except (ValueError, OSError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
