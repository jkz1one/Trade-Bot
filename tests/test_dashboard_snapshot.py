"""Offline native-account snapshot publication; no provider or model attachment."""

import asyncio
import json
import os
import sqlite3
import stat
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from test_connected_runtime import digest
from test_degen_options import AT
from test_portfolio_replay import request

from app.mixed import dashboard_snapshot as snapshot
from app.mixed.observer import MixedObserver
from app.options.runtime_cli import existing_runtime, initialize


def owner(tmp_path, *, positions=False):
    value = request(tmp_path)
    directory = tmp_path / "owner"
    initialize(directory, value.settings, clock=lambda: AT)
    if positions:
        from test_mixed_accounting import changed
        from test_portfolio_controls import get_intent

        with existing_runtime(directory, clock=lambda: AT) as (runtime, _):
            outcome = asyncio.run(runtime.c.cycle(value.packets[0].frame))
            assert [e["status"] for e in outcome["entries"]] == ["OPEN", "OPEN"]
            for entry in outcome["entries"]:
                intent = get_intent(runtime.c.engine, entry["client_id"])
                quote = next(
                    x.quote
                    for x in value.packets[0].frame.stocks
                    if x.quote.instrument == intent.instrument
                )
                runtime.c.engine.venue.fill_stock(
                    intent,
                    intent.quantity,
                    changed(
                        quote,
                        source_at=AT + timedelta(seconds=1),
                        received_at=AT + timedelta(seconds=1),
                    ),
                    AT + timedelta(seconds=1),
                    fill_id=intent.client_id,
                )
            assert runtime.c.engine.reconcile(
                runtime.c.engine.venue.snapshot(AT + timedelta(seconds=1)),
                now=AT + timedelta(seconds=1),
            )["reconciled"]
    return directory, value.settings


def publisher(
    source, destination, *, create=True, at=AT + timedelta(seconds=2), uid=None, gid=None
):
    return snapshot.DashboardPublisher(
        source,
        destination,
        os.getuid() if uid is None else uid,
        os.getgid() if gid is None else gid,
        create=create,
        clock_source=lambda: at,
    )


def view(path, settings, at=AT + timedelta(seconds=2)):
    return MixedObserver(path, settings.limits.population_id, clock=lambda: at).report(limit=100)


@pytest.mark.parametrize("positions", [False, True])
def test_consistent_snapshot_keeps_native_account_and_two_plays(tmp_path, monkeypatch, positions):
    source, settings = owner(tmp_path, positions=positions)
    expected = view(source / "options.db", settings)
    before = digest(source)

    def forbidden(*a, **k):
        pytest.fail("Publisher opened execution, model or credential transport")

    monkeypatch.setattr("app.options.runtime_cli.existing_runtime", forbidden)
    monkeypatch.setattr("app.options.coordinator.model_key", forbidden)
    monkeypatch.setattr("app.options.read_capture.collect", forbidden)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination)
    try:
        result = p.publish()
        assert result["status"] == "PUBLISHED"
        assert result["held_plays"] == result["fills"] == (2 if positions else 0)
        assert not result["source_modified"] and not result["execution_authority"]
        assert not result["credentials_opened"] and not result["provider_calls"]
        assert view(destination / "options.db", settings) == expected
        assert digest(source) == before
        assert not (destination / "runtime.json").exists()
        assert not (destination / "venue.db").exists()
        assert not (destination / ".pending.db").exists()
    finally:
        p.close()
    all_before = digest(tmp_path)
    result = snapshot.check(
        source,
        destination,
        os.getuid(),
        os.getgid(),
        clock_source=lambda: AT + timedelta(seconds=12),
    )
    assert result["publication_age_seconds"] == 10
    assert not result["state_modified"] and digest(tmp_path) == all_before
    with pytest.raises(FileNotFoundError), existing_runtime(destination):
        pass
    with pytest.raises(FileExistsError):
        publisher(source, destination)


def test_existing_native_owner_lease_does_not_block_stored_snapshot(tmp_path):
    source, settings = owner(tmp_path)
    destination = tmp_path / "dashboard"
    with existing_runtime(source, clock=lambda: AT) as (runtime, _):
        before = digest(source)
        p = publisher(source, destination)
        try:
            p.publish()
        finally:
            p.close()
        assert digest(source) == before
        assert view(destination / "options.db", settings)["status"] == "OK"
        assert not runtime.running


def test_wal_commit_is_copied_without_copying_uncommitted_rows(tmp_path):
    source, settings = owner(tmp_path)
    writer = sqlite3.connect(source / "options.db")
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)",
            (AT.isoformat(), "COMMITTED_SNAPSHOT_TEST", "{}"),
        )
        writer.commit()
        committed = writer.execute("SELECT MAX(sequence) FROM execution_events").fetchone()[0]
        writer.execute(
            "INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)",
            (AT.isoformat(), "UNCOMMITTED_SNAPSHOT_TEST", "{}"),
        )
        destination = tmp_path / "dashboard"
        p = publisher(source, destination)
        try:
            result = p.publish()
        finally:
            p.close()
        assert result["checkpoint"]["owner_revision"] == committed
        with sqlite3.connect(destination / "options.db") as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM execution_events WHERE kind='UNCOMMITTED_SNAPSHOT_TEST'"
                ).fetchone()[0]
                == 0
            )
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert view(destination / "options.db", settings)["status"] == "OK"
    finally:
        writer.rollback()
        writer.close()


def test_atomic_replace_leaves_existing_open_reader_on_complete_old_snapshot(tmp_path):
    source, settings = owner(tmp_path)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination)
    try:
        first = p.publish()
        original_inode = (destination / "options.db").stat().st_ino
        old_reader = sqlite3.connect(f"file:{destination / 'options.db'}?mode=ro", uri=True)
        old_reader.execute("BEGIN")
        old_revision = old_reader.execute("SELECT MAX(sequence) FROM execution_events").fetchone()[
            0
        ]
        with sqlite3.connect(source / "options.db") as db:
            db.execute(
                "INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)",
                (AT.isoformat(), "NEXT_SNAPSHOT", "{}"),
            )
        second = p.publish()
        assert second["checkpoint"]["owner_revision"] == first["checkpoint"]["owner_revision"] + 1
        assert (destination / "options.db").stat().st_ino != original_inode
        assert (
            old_reader.execute("SELECT MAX(sequence) FROM execution_events").fetchone()[0]
            == old_revision
        )
        old_reader.close()
        assert view(destination / "options.db", settings)["revision"] == old_revision + 1
    finally:
        p.close()


def test_publisher_lease_excludes_second_writer(tmp_path):
    source, _ = owner(tmp_path)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination)
    try:
        p.publish()
        with pytest.raises(BlockingIOError):
            publisher(source, destination, create=False)
    finally:
        p.close()
    reopened = publisher(source, destination, create=False)
    try:
        assert reopened.publish()["status"] == "PUBLISHED"
    finally:
        reopened.close()


@pytest.mark.parametrize("damage", ["revision", "generation", "sequence", "clock"])
def test_backward_source_never_replaces_latest_good_snapshot(tmp_path, damage):
    source, _ = owner(tmp_path)
    destination = tmp_path / "dashboard"
    with sqlite3.connect(source / "options.db") as db:
        db.execute("UPDATE execution_option_runtime SET generation=2,feed_sequence=2")
    p = publisher(source, destination)
    try:
        p.publish()
        before = (destination / "options.db").read_bytes()
        if damage == "clock":
            p.clock = lambda: AT + timedelta(seconds=1)
        else:
            with sqlite3.connect(source / "options.db") as db:
                if damage == "revision":
                    db.execute(
                        "DELETE FROM execution_events WHERE sequence=(SELECT MAX(sequence) FROM execution_events)"
                    )
                else:
                    db.execute(
                        "UPDATE execution_option_runtime SET "
                        + ("generation" if damage == "generation" else "feed_sequence")
                        + "=1"
                    )
        with pytest.raises(ValueError, match="regressed"):
            p.publish()
        assert (destination / "options.db").read_bytes() == before
        assert (destination / ".pending.db").exists()
    finally:
        p.close()
    with pytest.raises(ValueError, match="Retained failed"):
        publisher(source, destination, create=False)


@pytest.mark.parametrize("damage", ["frozen", "binding", "symlink", "public", "reader"])
def test_invalid_bindings_fail_before_publication(tmp_path, damage):
    source, _ = owner(tmp_path)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination)
    try:
        p.publish()
    finally:
        p.close()
    if damage == "frozen":
        with sqlite3.connect(source / "options.db") as db:
            db.execute("UPDATE execution_control SET halt_reason='FROZEN_OFFLINE_REPLAY'")
    elif damage == "binding":
        (destination / "binding.json").write_text("{}")
    elif damage == "public":
        (destination / "options.db").chmod(0o644)
    elif damage == "symlink":
        (destination / "options.db").rename(destination / "retained.db")
        (destination / "options.db").symlink_to(destination / "retained.db")
    before = digest(tmp_path)
    with pytest.raises(ValueError):
        publisher(
            source, destination, create=False, uid=os.getuid() + 1 if damage == "reader" else None
        )
    assert digest(tmp_path) == before


def test_failed_validation_preserves_last_good_snapshot_and_partial_evidence(tmp_path, monkeypatch):
    source, _ = owner(tmp_path)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination)
    try:
        p.publish()
        before = (destination / "options.db").read_bytes()
        monkeypatch.setattr(MixedObserver, "report", lambda *a, **k: {"status": "UNAVAILABLE"})
        with pytest.raises(ValueError, match="accounting unavailable"):
            p.publish()
        assert (destination / "options.db").read_bytes() == before
        assert (destination / ".pending.db").exists()
    finally:
        p.close()


def test_shutdown_stops_only_the_publisher(tmp_path):
    source, _ = owner(tmp_path)
    p = publisher(source, tmp_path / "dashboard")
    before = digest(source)

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True

    try:
        result = snapshot.run(p, Stop(), seconds=10)
        assert result["snapshots_published"] == 1
        stop = threading.Event()
        stop.set()
        assert snapshot.run(p, stop, seconds=10)["snapshots_published"] == 0
        assert digest(source) == before
    finally:
        p.close()


def test_cross_uid_snapshot_is_readable_by_unprivileged_dashboard_without_auth_copy(tmp_path):
    if os.getuid() != 0:
        pytest.skip("Cross-UID publication requires root")
    for kind in ("uid", "gid"):
        mapping = Path(f"/proc/self/{kind}_map")
        if mapping.exists() and not any(
            int(start) <= 10001 < int(start) + int(count)
            for start, _outside, count in (
                line.split() for line in mapping.read_text().splitlines()
            )
        ):
            pytest.skip(f"Reader 10001 is not mapped in this environment: {kind}")
    source, settings = owner(tmp_path, positions=True)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination, uid=10001, gid=10001)
    try:
        p.publish()
        p.publish()  # Existing reader-owned snapshot can be checked and replaced.
    finally:
        p.close()
    info = (destination / "options.db").stat()
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (10001, 10001, 0o600)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o711
    assert (destination / "binding.json").stat().st_uid == 0
    # A child inherits the directory descriptor to model a Docker directory bind
    # without opening up pytest's private ancestor directories.
    fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            os.fchdir(fd)
            os.close(fd)
            os.setgroups([])
            os.setgid(10001)
            os.setuid(10001)
            report = view(Path("/proc/self/cwd/options.db"), settings)
            out = {
                "uid": os.getuid(),
                "status": report["status"],
                "plays": len(report["positions"]),
                "fills": report["fill_count"],
            }
            os.write(write_fd, json.dumps(out).encode())
            os._exit(0)
        except BaseException:  # noqa: BLE001 -- forked child must not reenter pytest
            os._exit(1)
    os.close(write_fd)
    os.close(fd)
    payload = os.read(read_fd, 4096)
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    assert status == 0 and json.loads(payload) == {
        "uid": 10001,
        "status": "OK",
        "plays": 2,
        "fills": 2,
    }


@pytest.mark.parametrize("failure", ["deadline", "ownership", "replace"])
def test_failed_publication_retains_last_complete_snapshot(tmp_path, monkeypatch, failure):
    source, _ = owner(tmp_path)
    destination = tmp_path / "dashboard"
    p = publisher(source, destination)
    try:
        p.publish()
        original = (destination / "options.db").read_bytes()
        before = digest(source)

        def fail(*_args, **_kwargs):
            raise PermissionError("injected publication failure")

        if failure == "deadline":
            monkeypatch.setattr(snapshot, "BACKUP_SECONDS", -1)
        elif failure == "ownership":
            monkeypatch.setattr(snapshot.os, "fchown", fail)
        else:
            monkeypatch.setattr(snapshot.os, "replace", fail)
        with pytest.raises(OSError):
            p.publish()
        assert (destination / "options.db").read_bytes() == original
        assert (destination / ".pending.db").exists()
        assert digest(source) == before
    finally:
        p.close()
