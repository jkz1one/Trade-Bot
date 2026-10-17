"""Read a bounded offline evaluation bundle and print evidence-only JSON."""

import argparse
import json
import os
import stat
import sys

from app.options.evaluation import MAX_BUNDLE_BYTES, evaluate
from app.options.evaluation_models import EvaluationBundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument(
        "--tape",
        action="append",
        default=None,
        help="Optional sealed session tape; repeat for each session",
    )
    args = parser.parse_args(argv)
    try:
        fd = os.open(args.bundle, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BUNDLE_BYTES:
                raise ValueError("Bounded regular file required")
            raw = stream.read(MAX_BUNDLE_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > MAX_BUNDLE_BYTES or (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("Evidence changed or exceeded capacity")
        tapes = None
        if args.tape is not None:
            from app.options.market_tape import MAX_TAPE_BYTES, load_tape

            if len(args.tape) > 60:
                raise ValueError("Tape count exceeds capacity")
            tapes, size = [], 0
            for path in args.tape:
                tape = load_tape(path)
                size += len(tape.model_dump_json().encode())
                if size > 2 * MAX_TAPE_BYTES:
                    raise ValueError("Combined tape evidence capacity exceeded")
                tapes.append(tape)
        result = evaluate(EvaluationBundle.model_validate_json(raw), tapes=tapes)
    except (OSError, ValueError, ArithmeticError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "INVALID_EVALUATION_EVIDENCE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "COMPLETE_ARITHMETIC" else 1


if __name__ == "__main__":
    sys.exit(main())
