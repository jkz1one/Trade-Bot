"""Export existing native session-boundary journals without opening execution authority."""

import argparse
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

from pydantic import Field, TypeAdapter, field_validator

from app.options.evaluation_export import export_comparison, export_series
from app.options.evaluation_models import Arm, EvaluationManifest, UnderlyingSettlement
from app.options.market_tape import load_tape, validate_tape_series
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
    underlying_settlements: tuple[UnderlyingSettlement, ...] = Field(default=(), max_length=180)
    tape: str = Field(min_length=1, max_length=4096)
    sources: tuple[ExportSource, ...] = Field(min_length=3, max_length=4)


class ExportBoundary(OptionRecord):
    session_key: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    tape: str = Field(min_length=1, max_length=4096)
    sources: tuple[ExportSource, ...] = Field(min_length=3, max_length=4)


class SeriesExportRequest(OptionRecord):
    manifest: EvaluationManifest
    underlying_settlements: tuple[UnderlyingSettlement, ...] = Field(default=(), max_length=180)
    boundaries: tuple[ExportBoundary, ...] = Field(min_length=1, max_length=60)


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
        request = TypeAdapter(ExportRequest | SeriesExportRequest).validate_json(raw)
        if isinstance(request, ExportRequest):
            if len(request.sources) != len(request.manifest.arms) or {
                s.arm for s in request.sources
            } != {d.arm for d in request.manifest.arms}:
                raise ValueError("Unique A/B/C sources required")
            result = export_comparison(
                request.manifest,
                load_tape(request.tape),
                {s.arm: s.model_dump(exclude={"arm"}) for s in request.sources},
                underlying_settlements=request.underlying_settlements,
            )
        else:
            if tuple(b.session_key for b in request.boundaries) != tuple(
                s.key for s in request.manifest.sessions
            ) or any(
                (
                    len(b.sources) != len(request.manifest.arms)
                    or {s.arm for s in b.sources} != {d.arm for d in request.manifest.arms}
                )
                or not Path(b.tape).is_absolute()
                for b in request.boundaries
            ):
                raise ValueError("Exact ordered private native boundaries required")
            result = export_series(
                request.manifest,
                validate_tape_series(load_tape(b.tape) for b in request.boundaries),
                {
                    b.session_key: {s.arm: s.model_dump(exclude={"arm"}) for s in b.sources}
                    for b in request.boundaries
                },
                underlying_settlements=request.underlying_settlements,
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
