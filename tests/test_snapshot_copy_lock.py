"""Copy setup must tolerate the same bounded locks as SQLite's backup loop."""
import sqlite3
from contextlib import closing
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.mixed import dashboard_snapshot
from tests.test_paper_session_report import module as reports


@pytest.mark.parametrize("backend", ["dashboard", "report"])
@pytest.mark.parametrize("release", [True, False])
def test_copy_setup_transient_lock_and_deadline(tmp_path, monkeypatch, backend, release):
    source = tmp_path / "native.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE receipt(value)")
        db.execute("INSERT INTO receipt VALUES('original')")
    before = source.read_bytes()
    writer = sqlite3.connect(source)
    writer.execute("BEGIN EXCLUSIVE")
    budget = 2 if release else .1
    monkeypatch.setattr(reports, "REPORT_COPY_SECONDS", budget)
    def copy():
        if backend == "report":
            db = reports.connection(source)
            try:
                return db.execute("SELECT value FROM receipt").fetchone()[0]
            finally:
                db.close()
        destination = tmp_path / "copy.db"
        dashboard_snapshot.copy_source(source, destination, time.monotonic() + budget)
        with sqlite3.connect(destination) as db:
            return db.execute("SELECT value FROM receipt").fetchone()[0]
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            began = time.monotonic()
            result = pool.submit(copy)
            if release:
                # The old code immediately failed with SQLITE_BUSY.
                time.sleep(.1)
                assert not result.done()
                writer.rollback()
                assert result.result(timeout=3) == "original"
            else:
                with pytest.raises(TimeoutError, match="COPY_DEADLINE|copy exceeded"):
                    result.result(timeout=2)
                assert time.monotonic() - began < 1
    finally:
        writer.rollback()
        writer.close()
    assert source.read_bytes() == before


@pytest.mark.parametrize("backend", ["dashboard", "report"])
@pytest.mark.parametrize("stall", ["none", "persistent", "transient", "advancing"])
def test_repeated_commits_cannot_restart_private_copy_indefinitely(tmp_path, monkeypatch, backend, stall):
    """Write between SQLite backup steps, including while the bounded retry holds its view."""
    source = tmp_path / "paced.db"
    connect = sqlite3.connect
    with closing(connect(source)) as setup:
        setup.executescript("CREATE TABLE marker(value INTEGER); INSERT INTO marker VALUES(0);"
                            "CREATE TABLE mirror(value INTEGER); INSERT INTO mirror VALUES(0);"
                            "CREATE TABLE pages(payload BLOB);")
        setup.executemany("INSERT INTO pages VALUES(zeroblob(12000))", [()] * 160)
        setup.commit()
    commits = []

    def commit_marker():
        with closing(connect(source, timeout=0)) as writer:
            try:
                writer.execute("UPDATE marker SET value=value+1")
                writer.execute("UPDATE mirror SET value=value+1")
                writer.commit()
            except sqlite3.OperationalError as exc:
                assert exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                return
            commits.append(True)

    copy_modes = []
    commit_at_pages = [64, 192] if stall == "advancing" else []

    class FrequentWriter(sqlite3.Connection):
        def backup(self, target, *, progress, **kwargs):
            pinned = self.in_transaction
            copy_modes.append(pinned)
            released = stall in {"transient", "advancing"} and True in copy_modes and not pinned
            if released:
                before = len(commits)
                commit_marker()
                assert len(commits) == before + 1

            def write_after_step(status, remaining, total):
                if pinned and stall != "none":
                    time.sleep(.03)
                progress(status, remaining, total)
                if status == sqlite3.SQLITE_OK and 0 < remaining < total:
                    if not released:
                        commit_marker()
                    elif commit_at_pages and total - remaining >= commit_at_pages[0]:
                        before = len(commits)
                        commit_marker()
                        assert len(commits) == before + 1
                        commit_at_pages.pop(0)
            return super().backup(target, progress=write_after_step, **kwargs)

    def monitored(database, **kwargs):
        if str(database) in (source.as_uri() + "?mode=ro", "file:" + str(source) + "?mode=ro"):
            kwargs["factory"] = FrequentWriter
        return connect(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", monitored)
    monkeypatch.setattr(reports, "REPORT_COPY_SECONDS", .6)
    def private_view():
        if backend == "report":
            return reports.connection(source)
        destination = tmp_path / "private.db"
        dashboard_snapshot.copy_source(source, destination, time.monotonic() + .6)
        return connect(destination)

    if stall != "none":
        from app.mixed import sqlite_copy
        monkeypatch.setattr(sqlite_copy if backend == "dashboard" else reports._copy,
                            "PINNED_COPY_SECONDS", .02)
    if stall == "persistent":
        began = time.monotonic()
        with pytest.raises(TimeoutError):
            private_view()
        assert time.monotonic() - began < .4
        assert copy_modes.count(True) == 1
        assert commits
        before = len(commits)
        commit_marker()
        assert len(commits) == before + 1
        return
    result = private_view()
    with closing(result) as snapshot:
        a, b = snapshot.execute("SELECT marker.value,mirror.value FROM marker,mirror").fetchone()
        assert 0 < a == b
        before = len(commits)
        commit_marker()
        assert len(commits) == before + 1
        assert snapshot.execute("SELECT value FROM marker").fetchone()[0] == a
    if stall in {"transient", "advancing"}:
        assert not commit_at_pages
        assert copy_modes == [False, True, False]


@pytest.mark.parametrize("stop", ["pinned_deadline", "final_deadline", "final_capacity"])
def test_private_copy_enforces_original_bounds_after_restart(monkeypatch, stop):
    from types import SimpleNamespace
    from app.mixed import sqlite_copy

    # Drive SQLite's progress callback at its exact limits without depending
    # on the scheduler. The tests above exercise real file backups and writers.
    now = [0.0]
    attempts = []
    monkeypatch.setattr(sqlite_copy, "time", SimpleNamespace(monotonic=lambda: now[0]))

    class ControlledBackup(sqlite3.Connection):
        def backup(self, target, *, progress, **kwargs):
            attempts.append(self.in_transaction)
            if len(attempts) == 1:
                progress(sqlite3.SQLITE_OK, 4, 8)
                progress(sqlite3.SQLITE_OK, 4, 8)
            elif self.in_transaction:
                now[0] = 1.0 if stop == "pinned_deadline" else sqlite_copy.PINNED_COPY_SECONDS
                progress(sqlite3.SQLITE_OK, 2, 8)
            else:
                if stop == "final_deadline":
                    now[0] = 1.0
                pages = 9 if stop == "final_capacity" else 8
                progress(sqlite3.SQLITE_DONE, 0, pages)

    with closing(sqlite3.connect(":memory:", factory=ControlledBackup)) as source:
        page_size = source.execute("PRAGMA page_size").fetchone()[0]
        with closing(sqlite3.connect(":memory:")) as target:
            error, message = (ValueError, "size") if stop == "final_capacity" else (TimeoutError, "time")
            with pytest.raises(error, match=message):
                sqlite_copy.private_backup(source, target, deadline=1.0, max_bytes=8 * page_size,
                                           capacity_error="size", deadline_error="time")
        assert not source.in_transaction
    assert attempts == ([False, True] if stop == "pinned_deadline" else [False, True, False])
