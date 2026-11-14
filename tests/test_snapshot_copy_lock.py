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
@pytest.mark.parametrize("stall", [False, True])
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

    class FrequentWriter(sqlite3.Connection):
        def backup(self, target, *, progress, **kwargs):
            def write_after_step(status, remaining, total):
                if self.in_transaction and stall:
                    time.sleep(.03)
                progress(status, remaining, total)
                if status == sqlite3.SQLITE_OK and 0 < remaining < total:
                    commit_marker()
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

    if stall:
        from app.mixed import sqlite_copy
        monkeypatch.setattr(sqlite_copy if backend == "dashboard" else reports._copy,
                            "PINNED_COPY_SECONDS", .02)
        began = time.monotonic()
        with pytest.raises(TimeoutError):
            private_view()
        assert time.monotonic() - began < .4
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
