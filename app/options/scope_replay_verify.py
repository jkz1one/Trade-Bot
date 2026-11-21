"""Reproduce portable Scope research JSON in temporary independent PAPER state."""

import argparse
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.scope_replay import MAX_REQUEST_BYTES, ScopeReplayRequest, run_scope_replay

MAX_ACTION_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 128 * 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Scope export key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite Scope export value")


def _read(directory_fd, name, limit, budget):
    # Names are constructed locally, never taken from the report's artifact index.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= min(limit, budget[0])
        ):
            raise ValueError("Private bounded Scope export file required")
        raw = stream.read(min(limit, budget[0]) + 1)
        after = os.fstat(stream.fileno())
        if len(raw) != before.st_size or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Scope export changed during read")
    budget[0] -= len(raw)
    result = json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)
    if not isinstance(result, dict):
        raise TypeError("Scope export object required")
    return result


def _directory(path, *, parent=None):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        raise ValueError("Private owned Scope export directory required")
    return fd


def _complete(root):
    # lstat also detects dangling symlinks and non-file interruption markers.
    try:
        os.stat("interrupted.json", dir_fd=root, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError("Interrupted Scope export cannot verify")


def _inventory(directory_fd, expected):
    with os.scandir(directory_fd) as entries:
        found = set()
        for entry in entries:
            if entry.name not in expected:
                raise ValueError("Scope action inventory differs")
            found.add(entry.name)
    if found != expected:
        raise ValueError("Scope action inventory differs")


def _snapshot(directory, expected_request_hash):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute Scope export directory required")
    root = _directory(directory)
    try:
        _complete(root)
        budget = [MAX_EXPORT_BYTES]
        # The envelope adds the request hash and field names to the request bound.
        inputs = _read(root, "inputs.json", MAX_REQUEST_BYTES + 256, budget)
        request = ScopeReplayRequest.model_validate(inputs["request"])
        if fingerprint(request) != expected_request_hash or fingerprint(inputs) != fingerprint(
            {"request_hash": expected_request_hash, "request": request.model_dump(mode="json")}
        ):
            raise ValueError("Scope request differs from expected frozen input")
        report = _read(root, "report.json", MAX_REPORT_BYTES, budget)
        actions_fd = _directory("actions", parent=root)
        try:
            names = [f"{index:03d}.json" for index in range(len(request.steps))]
            _inventory(actions_fd, set(names))
            actions = [_read(actions_fd, name, MAX_ACTION_BYTES, budget) for name in names]
            _inventory(actions_fd, set(names))
        finally:
            os.close(actions_fd)
        _complete(root)
        return request, {"inputs": inputs, "actions": actions, "report": report}
    finally:
        os.close(root)


def verify_scope_replay(directory, expected_request_hash):
    """Verify a captured JSON snapshot, not the source journals or provider authenticity.

    The caller must retain the original request hash independently of the export.
    Reproduction uses this installed implementation and deletes all temporary state.
    """
    if not isinstance(expected_request_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_request_hash
    ):
        raise ValueError("Expected Scope request hash required")
    request, saved = _snapshot(directory, expected_request_hash)
    with TemporaryDirectory(prefix="scope-replay-verify-") as temporary:
        output = Path(temporary) / "reproduction"
        run_scope_replay(request, output)
        _, reproduced = _snapshot(output, expected_request_hash)
        if fingerprint(saved) != fingerprint(reproduced):
            raise ValueError("Scope export differs from native reproduction")
    return {
        "status": "VERIFIED_RESEARCH_REPLAY",
        "verification_kind": "DETERMINISTIC_REPRODUCTION",
        "request_hash": expected_request_hash,
        "export_hash": fingerprint(saved),
        "report_hash": fingerprint(saved["report"]),
        "actions_verified": len(request.steps),
        "recorded_actions": saved["report"]["recorded_actions"],
        "rejected_actions": saved["report"]["rejected_actions"],
        "evidence_kind": "LOCAL_FIXTURE",
        "economic_conclusion": "NOT_EVALUATED",
        "data_cost": None,
        "host_cost": None,
        "net_return": None,
        "source_journals_verified": False,
        "execution_authority": False,
        "live_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True, help="Absolute private Scope export directory")
    parser.add_argument("--request-hash", required=True, help="Independently retained request hash")
    args = parser.parse_args(argv)
    try:
        result = verify_scope_replay(args.export, args.request_hash)
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        ArithmeticError,
        TimeoutError,
        RecursionError,
        ExecutionBlocked,
    ):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "SCOPE_REPLAY_VERIFICATION_UNAVAILABLE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
