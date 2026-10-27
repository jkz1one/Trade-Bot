"""Independent observation journal and atomic snapshots. Never opens a bankroll for writing."""

import fcntl
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.events.assessment import prepare
from app.events.models import Coverage, Event, MarketSample, Policy, Session, Snapshot, Volatility
from app.options.engine import fingerprint
from app.options.operator_inbox import private_directory, read, sync_directory

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


class EventStore:
    """One writer per directory. A separate evidence DB, with no cash/account/order tables."""

    def __init__(self, directory, population_id, policy: Policy, *, create=False):
        self.directory = Path(directory).resolve()
        if create:
            self.directory.mkdir(mode=0o700)
        private_directory(self.directory)
        self.policy = policy
        self.binding = {
            "version": "event-audit-v1",
            "population_id": population_id,
            "policy": policy.model_dump(mode="json"),
        }
        self.path = self.directory / "events.db"
        if not create and not self.path.is_file():
            raise ValueError("Existing event audit required")
        if create:
            self.path.touch(mode=0o600, exist_ok=False)
            with self.db() as db:
                db.executescript(
                    "CREATE TABLE binding(payload TEXT NOT NULL);"
                    "CREATE TABLE collections(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);"
                    "CREATE TABLE snapshots(sequence INTEGER PRIMARY KEY,published_at TEXT NOT NULL,"
                    "digest TEXT NOT NULL UNIQUE,payload TEXT NOT NULL);"
                    "CREATE TABLE observations(digest TEXT PRIMARY KEY,payload TEXT NOT NULL);"
                )
                db.execute(
                    "INSERT INTO binding VALUES(?)", (json.dumps(self.binding, sort_keys=True),)
                )
        with self.db() as db:
            if json.loads(db.execute("SELECT payload FROM binding").fetchone()[0]) != self.binding:
                raise ValueError("Event audit population/policy changed")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=1)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def writer(self):
        fd = os.open(self.directory / "writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def retain(self, collection):
        """Append original normalized rows, revisions, raw payload and failure/latency evidence."""
        with self.writer(), self.db() as db:
            db.execute(
                "INSERT INTO collections(payload) VALUES(?)",
                (json.dumps(collection, sort_keys=True),),
            )

    def publish(self, *, now):
        with self.writer():
            with self.db() as db:
                rows = [
                    json.loads(r[0])
                    for r in db.execute("SELECT payload FROM collections ORDER BY id")
                ]
                sequence = db.execute(
                    "SELECT coalesce(max(sequence),0)+1 FROM snapshots"
                ).fetchone()[0]
                previous = db.execute(
                    "SELECT published_at FROM snapshots ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                if previous and now < datetime.fromisoformat(previous[0]):
                    raise ValueError("Publication clock regressed")
            events, coverage, samples, sessions, volatility = {}, {}, {}, {}, {}
            for row in rows:
                for raw in row.get("events", ()):
                    e = Event.model_validate(raw)
                    key = e.source, e.event_id
                    old = events.get(key, [])

                    def order(value):
                        return (
                            value.revision_sequence if value.revision_sequence is not None else -1,
                            value.source_at or value.received_at,
                        )

                    clock = order(e)
                    prior = max(map(order, old), default=None)
                    if prior is None or clock > prior:
                        events[key] = [e]
                    elif clock == prior:
                        # Retain competing same-revision payloads, but coalesce exact
                        # repeated receipts without making their content younger.
                        content = e.model_dump(exclude={"received_at"})
                        if not any(v.model_dump(exclude={"received_at"}) == content for v in old):
                            events[key].append(e)
                for raw in row.get("coverage", ()):
                    c = Coverage.model_validate(raw)
                    key = c.source, c.dataset, c.scope, c.symbols
                    if key not in coverage or c.checked_at >= coverage[key].checked_at:
                        coverage[key] = c
                for raw in row.get("samples", ()):
                    s = MarketSample.model_validate(raw)
                    key = s.source, s.instrument_id
                    if key not in samples or s.source_at >= samples[key].source_at:
                        samples[key] = s
                if "sessions" in row:
                    sessions = {s.day: s for s in map(Session.model_validate, row["sessions"])}
                for raw in row.get("volatility", ()):
                    v = Volatility.model_validate(raw)
                    volatility[v.source, v.symbol] = v
            snapshot = Snapshot(
                sequence=sequence,
                published_at=now,
                policy_hash=fingerprint(self.policy),
                events=tuple(e for group in events.values() for e in group),
                coverage=tuple(coverage.values()),
                samples=tuple(samples.values()),
                sessions=tuple(sessions.values()),
                volatility=tuple(volatility.values()),
            )
            payload = snapshot.model_dump_json()
            if len(payload.encode()) > MAX_SNAPSHOT_BYTES:
                raise ValueError("Snapshot exceeds bounded reader capacity")
            # Durably retain before publishing. A crash here leaves an unpublished
            # version; only versions with a publication receipt qualify for replay.
            with self.db() as db:
                db.execute(
                    "INSERT INTO snapshots VALUES(?,?,?,?)",
                    (sequence, now.isoformat(), fingerprint(snapshot), payload),
                )
            fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=self.directory)
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.directory / "risk.json")
                sync_directory(self.directory)
                with self.db() as db:
                    db.execute(
                        "INSERT INTO collections(payload) VALUES(?)",
                        (
                            json.dumps(
                                {
                                    "kind": "PUBLICATION",
                                    "sequence": sequence,
                                    "published_at": now.isoformat(),
                                    "snapshot_hash": fingerprint(snapshot),
                                }
                            ),
                        ),
                    )
            finally:
                Path(name).unlink(missing_ok=True)
            return snapshot

    def as_of(self, at):
        with self.db() as db:
            receipts = {
                json.loads(r[0])["sequence"]
                for r in db.execute(
                    "SELECT payload FROM collections WHERE json_extract(payload,'$.kind')='PUBLICATION'"
                )
            }
            for seq, raw in db.execute(
                "SELECT sequence,payload FROM snapshots ORDER BY sequence DESC"
            ):
                snapshot = Snapshot.model_validate_json(raw)
                if seq in receipts and snapshot.published_at <= at:
                    return snapshot
        return None

    def observe(self, payload):
        digest = fingerprint(payload)
        with self.writer(), self.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO observations VALUES(?,?)",
                (digest, json.dumps(payload, sort_keys=True)),
            )
        return digest

    def export(self):
        """Portable evidence only; deliberately separate from native accounting exports."""
        from app.events.consumer import observer_export

        with self.db() as db:
            db.execute("BEGIN")
            return {
                "binding": self.binding,
                "observer": observer_export(db),
                "collections": [
                    json.loads(r[0])
                    for r in db.execute("SELECT payload FROM collections ORDER BY id")
                ],
                "snapshots": [
                    json.loads(r[0])
                    for r in db.execute("SELECT payload FROM snapshots ORDER BY sequence")
                ],
                "observations": [
                    json.loads(r[0])
                    for r in db.execute("SELECT payload FROM observations ORDER BY rowid")
                ],
            }


class SnapshotLoader:
    """Call refresh in a separate loader; check uses only the immutable pointer.

    On missing/corrupt/regressed publication, expose UNKNOWN rather than serving
    an apparently current success. The last valid file remains in the audit.
    """

    def __init__(self, path, policy):
        self.path, self.policy = Path(path), policy
        self.view = prepare(None, policy)
        self.high_water = 0
        self.digest = None

    def refresh(self):
        try:
            snapshot = Snapshot.model_validate_json(read(self.path, MAX_SNAPSHOT_BYTES))
            view = prepare(snapshot, self.policy)
            if (
                snapshot.policy_hash != view.policy_hash
                or snapshot.sequence < self.high_water
                or (snapshot.sequence == self.high_water and view.snapshot_hash != self.digest)
            ):
                raise ValueError("Snapshot identity or sequence changed")
            self.high_water, self.digest = snapshot.sequence, view.snapshot_hash
            self.view = view
            return True
        except (OSError, ValueError):
            self.view = prepare(None, self.policy)
            return False
