"""Copy setup must tolerate the same bounded locks as SQLite's backup loop."""
import sqlite3
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
