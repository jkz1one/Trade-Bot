"""Preserve original native populations before an explicitly separate v2 enrollment.

A binary upgrade never rewrites an old population's frozen accounting/model policy.
Backups include the matching restore authority and simulated venue, never secrets.
"""

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import quote

from app.execution import restore
from app.execution.runtime import runtime_lease
from app.options.engine import fingerprint
from app.options.operator_inbox import sync_directory


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preserve(journal, venue, destination):
    journal, venue, destination = map(Path, (journal, venue, destination))
    if any(not p.is_absolute() for p in (journal, venue, destination)) or destination.exists():
        raise ValueError("Absolute originals and new backup directory required")
    authority = restore.authority_path(journal)
    files = {"options.db": journal, "options.db.authority.db": authority, "venue.db": venue}
    if len({p.resolve() for p in files.values()}) != 3 or any(
        p.is_symlink() or not p.is_file() for p in files.values()
    ):
        raise ValueError("Three distinct regular native evidence files required")
    with runtime_lease(journal):
        before = {name: digest(path) for name, path in files.items()}
        with sqlite3.connect("file:" + quote(str(journal)) + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("Stopped restore-fenced delete-journal population required")
            if restore.status(db, authority)["status"] != "VERIFIED":
                raise ValueError("Original restore authority verification required")
            row = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
            config = json.loads(row[0])
            if config["schema"] != "option-paper-execution-v1":
                raise ValueError("Native options or mixed population required")
            revision = db.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM execution_events"
            ).fetchone()[0]
        with sqlite3.connect("file:" + quote(str(venue)) + "?mode=ro", uri=True) as db:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("Stopped durable venue required")
        from app.options.venue import DurableOptionVenue

        owned = DurableOptionVenue(venue)
        if owned.venue_id != config["venue_id"]:
            raise ValueError("Exact original owned venue required")
        destination.mkdir(mode=0o700)
        for name, path in files.items():
            target = destination / name
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with path.open("rb") as source, os.fdopen(fd, "wb") as target_stream:
                shutil.copyfileobj(source, target_stream)
                target_stream.flush()
                os.fsync(target_stream.fileno())
        if before != {name: digest(path) for name, path in files.items()} or before != {
            name: digest(destination / name) for name in files
        }:
            raise ValueError("Original evidence changed during backup; backup is not accepted")
        with sqlite3.connect(
            "file:" + quote(str(destination / "options.db")) + "?mode=ro", uri=True
        ) as db:
            db.row_factory = sqlite3.Row
            if restore.status(db, destination / "options.db.authority.db")["status"] != "VERIFIED":
                raise ValueError("Copied original restore authority verification failed")
        manifest = {
            "version": "native-portfolio-compatibility-v2",
            "population_id": config["limits"]["population_id"],
            "original_configuration_hash": fingerprint(config),
            "revision": revision,
            "sha256": before,
            "original_enrollment": "PORTFOLIO_V2"
            if (config["policy"].get("mixed_owner") or {}).get("portfolio")
            else "LEGACY_V1",
            "migration": "PRESERVE_EXISTING_ENROLLMENT",
            "rewritten_ids": False,
            "live_enabled": False,
            "credentials_copied": False,
        }
        fd = os.open(destination / "manifest.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(destination)
        return manifest


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = preserve(args.journal, args.venue, args.output)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "version",
                    "population_id",
                    "revision",
                    "original_enrollment",
                    "migration",
                    "credentials_copied",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
