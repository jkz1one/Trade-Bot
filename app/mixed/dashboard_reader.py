"""Read-only current dashboard from a bound native snapshot, never an owner."""

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from app.domain.models import utc_now
from app.mixed.dashboard_snapshot import VERSION, published
from app.mixed.observer import MixedObserver
from app.options.engine import clock
from app.options.release_identity import inspect_release
from app.web.options import create_options_app

MAX_PUBLICATION_AGE = 30


def parse_binding(raw):
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError("Bounded publisher binding required")
    binding = json.loads(raw)
    expected = {
        "version",
        "source_journal",
        "destination",
        "population_id",
        "owner_configuration_sha256",
        "publisher_uid",
        "reader_uid",
        "reader_gid",
    }
    if not isinstance(binding, dict) or set(binding) != expected or binding["version"] != VERSION:
        raise ValueError("Native snapshot binding required")
    for field in ("publisher_uid", "reader_uid", "reader_gid"):
        if type(binding[field]) is not int or not 0 <= binding[field] < 2**31:
            raise ValueError("Explicit numeric publisher and reader identity required")
    if (binding["reader_uid"], binding["reader_gid"]) != (os.getuid(), os.getgid()):
        raise ValueError("Snapshot reader identity mismatch")
    if not re.fullmatch(r"[a-f0-9]{64}", binding["owner_configuration_sha256"]):
        raise ValueError("Native configuration hash required")
    if not isinstance(binding["population_id"], str) or not binding["population_id"]:
        raise ValueError("Native population required")
    for field in ("source_journal", "destination"):
        if not isinstance(binding[field], str) or not Path(binding[field]).is_absolute():
            raise ValueError("Absolute publisher paths required")
    return binding


def guard(directory, binding, *, clock_source=utc_now):
    try:
        receipt = published(Path(directory), binding)
        if receipt is None:
            raise ValueError("Completed snapshot required")
        age = (
            clock(clock_source()) - datetime.fromisoformat(receipt["published_at"])
        ).total_seconds()
        if not 0 <= age <= MAX_PUBLICATION_AGE:
            raise ValueError("Recent snapshot publication required")
        return receipt
    except sqlite3.Error as exc:
        raise ValueError("Snapshot receipt unavailable") from exc


def inspect(directory, binding, *, clock_source=utc_now):
    receipt = guard(directory, binding, clock_source=clock_source)
    report = MixedObserver(
        Path(directory) / "options.db", binding["population_id"], clock=clock_source
    ).report()
    if report.get("status") != "OK" or report.get("accounting") != "VERIFIED":
        raise ValueError("Native snapshot accounting unavailable")
    release = inspect_release()
    if release.status != "VERIFIED_FILES":
        raise ValueError("Installed application identity unavailable")
    return {
        "status": "SNAPSHOT_READER_READY",
        "population_id": binding["population_id"],
        "binding_sha256": receipt["binding_sha256"],
        "published_at": receipt["published_at"],
        "checkpoint": receipt["checkpoint"],
        "held_plays": len(report["positions"]),
        "fills": report["fill_count"],
        "installed_files": release.file_count,
        "application_sha256": release.application_sha256,
        "execution_authority": False,
        "live_enabled": False,
        "admin_enabled": False,
        "trading_ready": False,
    }


def create_app(directory, binding, password_file, *, clock_source=utc_now):
    inspect(directory, binding, clock_source=clock_source)
    return create_options_app(
        str(Path(directory) / "options.db"),
        binding["population_id"],
        password_file,
        mixed=True,
        clock=clock_source,
        stored_guard=lambda: guard(directory, binding, clock_source=clock_source),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "serve"))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--binding-json", required=True)
    parser.add_argument("--password-file", required=True)
    args = parser.parse_args(argv)
    try:
        binding = parse_binding(args.binding_json)
        app = create_app(args.directory, binding, args.password_file)
        if args.operation == "inspect":
            print(json.dumps(inspect(args.directory, binding), sort_keys=True))
        else:
            import uvicorn

            uvicorn.run(app, host="0.0.0.0", port=8790, access_log=False, log_level="warning")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error):
        print(json.dumps({"status": "UNAVAILABLE", "reason": "DASHBOARD_READER_UNAVAILABLE"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
