"""Run or verify a private mixed A/B/C/D fixture bundle, without service credentials."""

import argparse
import asyncio
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

from app.execution.engine import ExecutionBlocked
from app.mixed.comparison import MAX_BUNDLE_BYTES, verify_mixed_comparison
from app.mixed.replay import MAX_REQUEST_BYTES, MixedComparison, run_mixed_comparison


def read_private(path, maximum):
    if not Path(path).is_absolute():
        raise ValueError("Absolute private input path required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("Private bounded regular input required")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if len(data) != before.st_size or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Private replay input changed while reading")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Create four fresh native PAPER fixture accounts")
    run.add_argument("--request", required=True)
    run.add_argument("--output", required=True, help="New absolute directory; never resumed")
    verify = commands.add_parser("verify", help="Reconstruct portable native evidence read-only")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--expected-hash", required=True, help="Independently retained bundle hash")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            request = MixedComparison.model_validate_json(
                read_private(args.request, MAX_REQUEST_BYTES)
            )
            bundle = asyncio.run(run_mixed_comparison(request, args.output))
            report = bundle["report"]
            digest = bundle["bundle_hash"]
        else:
            bundle = json.loads(read_private(args.bundle, MAX_BUNDLE_BYTES))
            report = verify_mixed_comparison(bundle, args.expected_hash)
            digest = args.expected_hash
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        ArithmeticError,
        TimeoutError,
        ExecutionBlocked,
    ):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "MIXED_REPLAY_UNAVAILABLE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps({"bundle_hash": digest, "report": report}, sort_keys=True))
    return 0 if report["comparison_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
