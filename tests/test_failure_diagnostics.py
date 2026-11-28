"""Persist useful local failure evidence without leaking exception contents."""

import asyncio
import json
import sqlite3
from contextlib import closing

import pytest
from test_option_execution import NOW, owned

from app.execution.failure import failure_details
from app.execution.process import (
    FixtureProcessFailed,
    FixtureProcessProtocolError,
    FixtureProcessTimeout,
)
from app.mixed import connected_runtime


@pytest.mark.parametrize(
    "kind",
    [
        FixtureProcessTimeout,
        FixtureProcessFailed,
        FixtureProcessProtocolError,
        sqlite3.OperationalError,
        ValueError,
        asyncio.CancelledError,
    ],
)
def test_failed_fixture_read_is_recorded_then_reraised_and_halted(tmp_path, monkeypatch, kind):
    secret = "DO-NOT-LOG-PRIVATE-CONTENTS"
    failure = kind(secret)

    async def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("app.options.engine.run_option_process", fail)
    with owned(tmp_path) as (engine, venue, _):
        original = venue.path.read_bytes()
        with pytest.raises(kind) as caught:
            asyncio.run(engine.reconcile_fixture(now=NOW))
        assert caught.value is failure
        assert venue.path.read_bytes() == original
        with engine.journal.read() as db:
            control = db.execute(
                "SELECT halted,halt_reason FROM execution_control WHERE id=1"
            ).fetchone()
            row = db.execute(
                "SELECT payload FROM execution_events WHERE kind='FIXTURE_READ_FAILED' ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        details = json.loads(row[0])
        assert tuple(control) == (1, "OPTION_FIXTURE_READ_FAILED")
        assert details["error_class"] == kind.__name__
        assert details["timeout_seconds"] == 5
        assert details["operation"] == "snapshot" and details["elapsed_seconds"] >= 0
        assert any(frame["file"] == "app/options/engine.py" for frame in details["frames"])
        assert secret not in row[0] and str(tmp_path) not in row[0]


def test_unknown_exception_name_is_not_logged():
    kind = type("PRIVATE_SECRET_CLASS_NAME", (RuntimeError,), {})
    result = failure_details(kind("private message"))
    assert result == {"error_class": "OTHER_ERROR", "frames": []}


@pytest.mark.parametrize('cause', ['full', 'interrupt', 'constraint'])
def test_real_sqlite_codes_survive_application_report_and_retained_readers(cause):
    from test_paper_session_report import module as reports
    from test_paper_soak_host import host
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('CREATE TABLE evidence(id INTEGER PRIMARY KEY, payload TEXT)')
        db.execute("INSERT INTO evidence VALUES(1,'PRIVATE_VALUE')")
        if cause == 'full':
            db.execute('PRAGMA max_page_count=2')
            statement = 'INSERT INTO evidence VALUES(2,zeroblob(32768))'
        elif cause == 'interrupt':
            db.set_progress_handler(lambda: 1, 1)
            statement = 'SELECT * FROM evidence'
        else:
            statement = "INSERT INTO evidence VALUES(1,'PRIVATE_VALUE')"
        with pytest.raises(sqlite3.Error) as caught:
            db.execute(statement)
        db.set_progress_handler(None, 0)
        record = failure_details(caught.value)
    expected = {'full': 'SQLITE_FULL', 'interrupt': 'SQLITE_INTERRUPT',
                'constraint': 'SQLITE_CONSTRAINT_PRIMARYKEY'}[cause]
    assert record['sqlite_errorname'] == expected
    assert record['sqlite_errorcode'] == getattr(sqlite3, expected)
    for projected in (reports.failure_evidence(json.dumps(record)), host.failure_detail(record)):
        assert projected['sqlite_errorname'] == expected
        assert projected['sqlite_errorcode'] == record['sqlite_errorcode']
        assert 'PRIVATE_VALUE' not in json.dumps(projected)


@pytest.mark.parametrize('code,name', [
    (13, 'PRIVATE_SQL_TEXT'), (9, 'SQLITE_FULL'), (True, 'SQLITE_ERROR'),
    (-1, 'SQLITE_ERROR'), (65536, 'SQLITE_ERROR'), (13, []),
])
def test_sqlite_evidence_rejects_unrecognized_or_mismatched_attributes(code, name):
    from test_paper_session_report import module as reports
    from test_paper_soak_host import host
    exc = sqlite3.OperationalError('PRIVATE_SQL_TEXT')
    exc.sqlite_errorcode, exc.sqlite_errorname = code, name
    record = {'error_class': 'OperationalError', 'sqlite_errorcode': code,
              'sqlite_errorname': name, 'message': 'PRIVATE_SQL_TEXT'}
    for result in (failure_details(exc), reports.failure_evidence(json.dumps(record)), host.failure_detail(record)):
        assert 'sqlite_errorcode' not in result and 'sqlite_errorname' not in result
        assert 'PRIVATE_SQL_TEXT' not in json.dumps(result)


def test_cli_reports_component_type_without_private_messages(monkeypatch, capsys):
    async def serve(args):
        async def fail(stop):
            raise FixtureProcessTimeout("private credential-like payload")

        async def wait(stop):
            await stop.wait()

        await connected_runtime.supervise(fail, wait, asyncio.Event())

    monkeypatch.setattr(connected_runtime, "serve", serve)
    assert (
        connected_runtime.main(
            [
                "run",
                "--directory",
                "/unused",
                "--feed-directory",
                "/unused-feed",
                "--policy",
                "/unused-policy",
                "--schemas",
                "/unused-schemas",
                "--seconds",
                "1",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["reason"] == "CONNECTED_COMPONENT_STOPPED:RUNTIME"
    assert report["failures"][0]["component"] == "RUNTIME"
    assert report["failures"][0]["error_class"] == "FixtureProcessTimeout"
    assert report["live_enabled"] is False and "private credential" not in output
