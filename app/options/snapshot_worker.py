"""Fixed read-only SQLite transport. Domain validation stays in the native parent.

Only standard-library imports: frequent reconciliation must not cold-build the
trading/model schemas. This worker has no order or mutation operation.
"""

import json
import math
import os
import sqlite3
import stat
import sys
import time
from pathlib import Path
from urllib.parse import quote

from app.options.process_trace import ChildTrace

VERSION = "option-snapshot-record-v1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def read_record(path):
    path = Path(path)
    before = path.lstat()
    if (not path.is_absolute() or not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600):
        raise ValueError("Private owned regular venue required")
    db = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True,
                         timeout=1, isolation_level=None)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {
            "option_fixture_control"
        }:
            raise ValueError("Dedicated venue required")
        lengths = db.execute("SELECT length(CAST(meta AS BLOB)),length(CAST(state AS BLOB)) "
                             "FROM option_fixture_control WHERE id=1").fetchone()
        if (lengths is None or any(type(n) is not int or n < 1 for n in lengths)
                or sum(lengths) > MAX_RESPONSE_BYTES):
            raise ValueError("Bounded venue record required")
        row = db.execute("SELECT meta,state FROM option_fixture_control WHERE id=1").fetchone()
        if any(type(value) is not str for value in row):
            raise ValueError("Text venue record required")
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_uid, before.st_mode) != (
            after.st_dev, after.st_ino, after.st_uid, after.st_mode
        ):
            raise ValueError("Venue path changed during read")
        return {"version": VERSION, "meta": row[0], "state": row[1]}
    finally:
        db.close()


def main():
    trace = ChildTrace()
    trace.mark("REQUEST")
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            return 1
        request = json.loads(data)
        if (type(request) is not dict or set(request) != {
                "version", "path", "parent_pid", "deadline_monotonic", "fault"}
                or request["version"] != VERSION
                or type(request["path"]) is not str or not 0 < len(request["path"]) <= 4096
                or type(request["parent_pid"]) is not int
                or request["parent_pid"] != os.getppid()
                or type(request["deadline_monotonic"]) not in (int, float)
                or not math.isfinite(request["deadline_monotonic"])
                or request["fault"] not in ("NONE", "STALL_READ")):
            return 1
        if time.monotonic() >= request["deadline_monotonic"]:
            return 1
        trace.mark("VENUE_OPEN")
        trace.mark("SNAPSHOT")
        if request["fault"] == "STALL_READ":
            while os.getppid() == request["parent_pid"]:
                time.sleep(0.1)
            return 1
        result = read_record(request["path"])
        if (os.getppid() != request["parent_pid"]
                or time.monotonic() >= request["deadline_monotonic"]):
            return 1
        trace.mark("SERIALIZE")
        encoded = json.dumps(result, separators=(",", ":")).encode()
        if len(encoded) > MAX_RESPONSE_BYTES:
            return 1
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        trace.mark("COMPLETE")
        return 0
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
