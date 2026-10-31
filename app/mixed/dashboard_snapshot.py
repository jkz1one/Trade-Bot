"""Consistent read-only dashboard snapshots of one existing native simulation owner.

No credential reads, execution owner, entry resume, provider or model attachment.
"""

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import stat
import threading
import time
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from app.domain.models import utc_now
from app.mixed.connected_runtime import inspect_owner
from app.mixed.observer import MixedObserver
from app.options.engine import clock, fingerprint
from app.options.observer import MAX_DATABASE_BYTES
from app.options.operator_inbox import read, save, sync_directory
from app.options.runtime_cli import load
from app.options.venue import private_path

VERSION = "native-dashboard-snapshot-v1"
BACKUP_SECONDS = 5


def binding_for(owner, destination, reader_uid, reader_gid, *, clock_source):
    owner, destination = Path(owner), Path(destination)
    if any(not p.is_absolute() or p.resolve() != p for p in (owner, destination)):
        raise ValueError("Canonical absolute source and snapshot paths required")
    if owner.is_relative_to(destination) or destination.is_relative_to(owner):
        raise ValueError("Separate non-nested source and snapshot directories required")
    if any(type(v) is not int or not 0 <= v < 2**31 for v in (reader_uid, reader_gid)):
        raise ValueError("Explicit numeric dashboard reader UID and GID required")
    settings = load(owner / "runtime.json")
    if settings.execution.mixed_owner is None or settings.execution.mixed_owner.portfolio is None:
        raise ValueError("Native two-play simulation owner required")
    _, state = inspect_owner(owner, settings, clock_source=clock_source)
    return {
        "version": VERSION,
        "source_journal": str(owner / "options.db"),
        "destination": str(destination),
        "population_id": settings.limits.population_id,
        "owner_configuration_sha256": state["owner_configuration_sha256"],
        "publisher_uid": os.getuid(),
        "reader_uid": reader_uid,
        "reader_gid": reader_gid,
    }, state


def directory_mode(binding):
    return 0o700 if binding["reader_uid"] == binding["publisher_uid"] else 0o711


def bound_directory(directory, binding):
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != directory_mode(binding)
    ):
        raise ValueError("Dedicated publisher-owned snapshot directory required")
    if json.loads(read(directory / "binding.json")) != binding:
        raise ValueError("Snapshot source, population or reader binding changed")


def file_identity(path, uid, gid=None):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != uid
        or (gid is not None and info.st_gid != gid)
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 0 < info.st_size <= MAX_DATABASE_BYTES
    ):
        raise ValueError("Bounded private snapshot database required")
    return info.st_dev, info.st_ino


def connect_readonly(path):
    db = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True, timeout=0)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    return db


def checkpoint(db, binding):
    config = json.loads(
        db.execute("SELECT config_json FROM execution_option_runtime WHERE id=1").fetchone()[0]
    )
    if fingerprint(config) != binding["owner_configuration_sha256"]:
        raise ValueError("Snapshot native owner configuration changed")
    if config["engine"]["limits"]["population_id"] != binding["population_id"]:
        raise ValueError("Snapshot population changed")
    generation, sequence = db.execute(
        "SELECT generation,feed_sequence FROM execution_option_runtime WHERE id=1"
    ).fetchone()
    revision = db.execute("SELECT COALESCE(MAX(sequence),0) FROM execution_events").fetchone()[0]
    return {"owner_revision": revision, "runtime_generation": generation, "feed_sequence": sequence}


def published(directory, binding, *, include_runtime=False):
    path = directory / "options.db"
    if not path.exists() and not path.is_symlink():
        return None
    identity = file_identity(path, binding["reader_uid"], binding["reader_gid"])
    db = connect_readonly(path)
    deadline = time.monotonic() + BACKUP_SECONDS
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        db.execute("BEGIN")
        row = db.execute("SELECT payload FROM dashboard_snapshot WHERE id=1").fetchone()
        if row is None or len(row[0]) > 4096:
            raise ValueError("Bounded snapshot receipt required")
        receipt = json.loads(row[0])
        if (
            receipt["version"] != VERSION
            or receipt["binding_sha256"] != fingerprint(binding)
            or receipt["checkpoint"] != checkpoint(db, binding)
        ):
            raise ValueError("Snapshot publication receipt changed")
        clock(datetime.fromisoformat(receipt["published_at"]))
        if include_runtime:
            # Read terminal state in the same transaction as the verified receipt.
            # This is derived evidence, not a change to the persisted receipt/hash.
            runtime = db.execute("SELECT status FROM execution_option_runtime WHERE id=1").fetchone()
            control = db.execute("SELECT halted FROM execution_control WHERE id=1").fetchone()
            if runtime is None or control is None:
                raise ValueError("Snapshot runtime state unavailable")
            receipt = receipt | {"stored_runtime": {"status": runtime[0], "halted": control[0] == 1}}
        if file_identity(path, binding["reader_uid"], binding["reader_gid"]) != identity:
            raise ValueError("Snapshot changed while reading")
        return receipt
    finally:
        db.close()


class DashboardPublisher:
    def __init__(
        self, owner, destination, reader_uid, reader_gid, *, create=False, clock_source=utc_now
    ):
        self.owner, self.directory = Path(owner), Path(destination)
        self.clock = clock_source
        self.binding, _ = binding_for(
            owner, destination, reader_uid, reader_gid, clock_source=self.clock
        )
        if create:
            self.directory.mkdir(mode=0o700)
            save(self.directory / "binding.json", self.binding)
            self.directory.chmod(directory_mode(self.binding))
            sync_directory(self.directory.parent)
        bound_directory(self.directory, self.binding)
        lock = self.directory / "publisher.lock"
        if not create:
            private_path(lock)
        self.fd = os.open(
            lock, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if create else 0), 0o600
        )
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            private_path(lock)
            self.previous = published(self.directory, self.binding)
            if (self.directory / ".pending.db").exists() or (
                self.directory / ".pending.db"
            ).is_symlink():
                raise ValueError("Retained failed snapshot requires inspection")
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def publish(self):
        binding, _ = binding_for(
            self.owner,
            self.directory,
            self.binding["reader_uid"],
            self.binding["reader_gid"],
            clock_source=self.clock,
        )
        if binding != self.binding:
            raise ValueError("Snapshot owner binding changed")
        bound_directory(self.directory, self.binding)
        source = self.owner / "options.db"
        source_identity = file_identity(source, os.getuid())
        temporary = self.directory / ".pending.db"
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        deadline = time.monotonic() + BACKUP_SECONDS
        with ExitStack() as connections:
            source_db = connections.enter_context(closing(connect_readonly(source)))
            target_db = connections.enter_context(closing(sqlite3.connect(temporary)))
            page_size = source_db.execute("PRAGMA page_size").fetchone()[0]

            def progress(_status, _remaining, total):
                if time.monotonic() > deadline or total * page_size > MAX_DATABASE_BYTES:
                    raise TimeoutError("Snapshot backup exceeded its bound")

            source_db.backup(target_db, pages=64, progress=progress, sleep=0.01)
            if file_identity(source, os.getuid()) != source_identity:
                raise ValueError("Source journal identity changed during backup")
            target_db.execute("PRAGMA journal_mode=DELETE")
            current = checkpoint(target_db, self.binding)
            at = clock(self.clock())
            if self.previous is not None and (
                at < datetime.fromisoformat(self.previous["published_at"])
                or any(current[k] < self.previous["checkpoint"][k] for k in current)
            ):
                raise ValueError("Snapshot source checkpoint or clock regressed")
            if target_db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='dashboard_snapshot'"
            ).fetchone():
                raise ValueError("A dashboard snapshot cannot be used as an execution source")
            receipt = {
                "version": VERSION,
                "binding_sha256": fingerprint(self.binding),
                "published_at": at.isoformat(),
                "checkpoint": current,
            }
            target_db.execute(
                "CREATE TABLE dashboard_snapshot(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)"
            )
            target_db.execute(
                "INSERT INTO dashboard_snapshot VALUES(1,?)", (json.dumps(receipt, sort_keys=True),)
            )
            target_db.commit()
        view = MixedObserver(temporary, self.binding["population_id"], clock=lambda: at).report(
            limit=100
        )
        if view.get("status") != "OK" or view.get("accounting") != "VERIFIED":
            raise ValueError("Native snapshot accounting unavailable")
        if time.monotonic() > deadline:
            raise TimeoutError("Snapshot verification exceeded its bound")
        fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
            os.fchmod(fd, 0o600)
            os.fchown(fd, self.binding["reader_uid"], self.binding["reader_gid"])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, self.directory / "options.db")
        sync_directory(self.directory)
        self.previous = receipt
        return {
            "status": "PUBLISHED",
            "population_id": self.binding["population_id"],
            **receipt,
            "held_plays": len(view["positions"]),
            "fills": view["fill_count"],
            "source_modified": False,
            "provider_calls": False,
            "credentials_opened": False,
            "execution_authority": False,
            "live_enabled": False,
        }


def check(owner, destination, reader_uid, reader_gid, *, clock_source=utc_now):
    binding, state = binding_for(
        owner, destination, reader_uid, reader_gid, clock_source=clock_source
    )
    directory = Path(destination)
    bound_directory(directory, binding)
    receipt = published(directory, binding)
    if receipt is None:
        raise ValueError("No completed dashboard snapshot")
    age = (clock(clock_source()) - datetime.fromisoformat(receipt["published_at"])).total_seconds()
    if age < 0:
        raise ValueError("Snapshot publication clock is in the future")
    return {
        "status": "SNAPSHOT_AVAILABLE",
        "population_id": binding["population_id"],
        **receipt,
        "publication_age_seconds": age,
        "source_owner_revision": state["owner_revision"],
        "state_modified": False,
        "provider_calls": False,
        "credentials_opened": False,
        "execution_authority": False,
        "live_enabled": False,
    }


def run(publisher, stop, *, seconds, interval=5):
    if (
        type(seconds) is not int
        or not 1 <= seconds <= 86400
        or type(interval) is not int
        or not 5 <= interval <= 60
    ):
        raise ValueError("Explicit bounded snapshot duration and cadence required")
    deadline = time.monotonic() + seconds
    count = 0
    while not stop.is_set() and time.monotonic() < deadline:
        publisher.publish()
        count += 1
        stop.wait(min(interval, max(0, deadline - time.monotonic())))
    return {
        "status": "STOPPED",
        "snapshots_published": count,
        "execution_authority": False,
        "live_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "publish", "check", "run"))
    for name in ("owner", "destination"):
        parser.add_argument("--" + name, required=True)
    for name in ("reader-uid", "reader-gid"):
        parser.add_argument("--" + name, required=True, type=int)
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args(argv)
    if (args.operation == "run") != (args.seconds is not None):
        parser.error("Only run requires an explicit --seconds")
    if args.operation == "run" and not (1 <= args.seconds <= 86400 and 5 <= args.interval <= 60):
        parser.error("Bounded duration and cadence required")
    try:
        paths = args.owner, args.destination, args.reader_uid, args.reader_gid
        if args.operation == "check":
            result = check(*paths)
        else:
            publisher = DashboardPublisher(*paths, create=args.operation == "create")
            try:
                if args.operation == "run":
                    stop = threading.Event()
                    prior = {
                        sig: signal.signal(sig, lambda *_: stop.set())
                        for sig in (signal.SIGINT, signal.SIGTERM)
                    }
                    try:
                        result = run(publisher, stop, seconds=args.seconds, interval=args.interval)
                    finally:
                        for sig, handler in prior.items():
                            signal.signal(sig, handler)
                else:
                    result = publisher.publish()
            finally:
                publisher.close()
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "DASHBOARD_SNAPSHOT_UNAVAILABLE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
