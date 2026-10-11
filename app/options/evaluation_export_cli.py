"""Export three existing native first-session journals without opening execution authority."""

import argparse
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

from pydantic import Field, field_validator

from app.options.evaluation_export import export_comparison
from app.options.evaluation_models import Arm, EvaluationManifest
from app.options.market_tape import load_tape
from app.options.models import Money, OptionRecord


class ExportSource(OptionRecord):
    arm: Arm
    journal: str = Field(min_length=1, max_length=4096)
    data_cost: Money | None = Field(default=None, ge=0)
    host_cost: Money | None = Field(default=None, ge=0)

    @field_validator("journal")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("Absolute native source path required")
        return value


class ExportRequest(OptionRecord):
    manifest: EvaluationManifest
    tape: str = Field(min_length=1, max_length=4096)
    sources: tuple[ExportSource, ExportSource, ExportSource]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
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
                raise ValueError("Private bounded export request required")
            raw = stream.read(256 * 1024 + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > 256 * 1024 or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Export request changed")
        request = ExportRequest.model_validate_json(raw)
        if {s.arm for s in request.sources} != {"A", "B", "C"}:
            raise ValueError("Unique A/B/C sources required")
        tape = load_tape(request.tape)
        result = export_comparison(
            request.manifest, tape, {s.arm: s.model_dump(exclude={"arm"}) for s in request.sources}
        )
        result["bundle"] = result["bundle"].model_dump(mode="json")
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, IndexError, ArithmeticError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "NATIVE_EXPORT_UNAVAILABLE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["report"]["status"] == "COMPLETE_ARITHMETIC" else 1


if __name__ == "__main__":
    sys.exit(main())
