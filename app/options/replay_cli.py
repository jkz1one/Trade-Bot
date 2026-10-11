"""Run a separate create-only scripted A/B/C PAPER replay; no provider calls."""

import argparse
import asyncio
import json
import os
import sqlite3
import stat
import sys

from pydantic import Field

from app.options.market_tape import load_tape
from app.options.models import OptionRecord
from app.options.replay import ReplaySettings, run_replay


class ReplayRequest(OptionRecord):
    settings: ReplaySettings
    tape: str = Field(min_length=1, max_length=4096)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", required=True, help="Private JSON settings and sealed tape path"
    )
    parser.add_argument("--output", required=True, help="New private run directory; never resumed")
    args = parser.parse_args(argv)
    try:
        fd = os.open(args.request, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= 256 * 1024
            ):
                raise ValueError("Private bounded replay request required")
            raw = stream.read(256 * 1024 + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > 256 * 1024 or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Replay request changed")
        request = ReplayRequest.model_validate_json(raw)
        if not os.path.isabs(request.tape) or not os.path.isabs(args.output):
            raise ValueError("Absolute tape and output paths required")
        result = asyncio.run(run_replay(request.settings, load_tape(request.tape), args.output))
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        ArithmeticError,
        TimeoutError,
    ):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "REPLAY_UNAVAILABLE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result["report"], sort_keys=True))
    return 0 if result["report"]["status"] == "COMPLETE_ARITHMETIC" else 1


if __name__ == "__main__":
    sys.exit(main())
