"""Run a separate create-only scripted A/B/C PAPER replay; no provider calls."""

import argparse
import asyncio
import json
import os
import sqlite3
import stat
import sys

from pydantic import Field, model_validator

from app.options.market_tape import load_tape, validate_tape_series
from app.options.models import OptionRecord
from app.options.replay import ReplaySettings, run_replay_series


class ReplayRequest(OptionRecord):
    settings: ReplaySettings
    tape: str | None = Field(default=None, min_length=1, max_length=4096)
    tapes: tuple[str, ...] = Field(default=(), max_length=60)

    @model_validator(mode="after")
    def one_source_form(self):
        paths = (self.tape,) if self.tape is not None else self.tapes
        if (
            (self.tape is not None and self.tapes)
            or not paths
            or any(not os.path.isabs(p) or len(p) > 4096 or "\x00" in p for p in paths)
        ):
            raise ValueError("One absolute tape or an ordered tape series required")
        return self


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
        if not os.path.isabs(args.output):
            raise ValueError("Absolute tape and output paths required")
        paths = (request.tape,) if request.tape is not None else request.tapes
        result = asyncio.run(
            run_replay_series(
                request.settings, validate_tape_series(load_tape(p) for p in paths), args.output
            )
        )
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
