"""Real isolated timeout evidence stays bounded and preserves the existing halt."""

import asyncio
import json
import sys

import pytest
from test_option_execution import NOW, owned

from app.execution.failure import failure_details
from app.execution.process import FixtureProcessTimeout
from app.options.process import run_option_process
from app.options.process_trace import MAX_TRACE_BYTES, OptionProcessDiagnostics, TraceReader


def test_stalled_snapshot_records_native_progress_and_preserves_venue(tmp_path):
    with owned(tmp_path) as (engine, venue, _):
        before = venue.path.read_bytes()
        venue.fault = "STALL_READ"
        with pytest.raises(FixtureProcessTimeout) as caught:
            asyncio.run(engine.reconcile_fixture(now=NOW))
        details = failure_details(caught.value)["option_process"]
        assert details["parent_phase"] == "RESPONSE_READ"
        assert details["child_trace_status"] == "OBSERVED"
        stages = details["child_stages"]
        assert [r["stage"] for r in stages] == ["REQUEST", "VENUE_OPEN", "SNAPSHOT"]
        assert all(r["elapsed_seconds"] >= 0 and r["cpu_seconds"] >= 0 for r in stages)
        assert venue.path.read_bytes() == before
        with engine.journal.read() as db:
            payload = db.execute("SELECT payload FROM execution_events WHERE kind='FIXTURE_READ_FAILED'").fetchone()[0]
            halted = db.execute("SELECT halted FROM execution_control WHERE id=1").fetchone()[0]
        assert halted == 1
        assert json.loads(payload)["option_process"] == details
        assert str(tmp_path) not in payload


def test_child_import_stall_is_distinct_from_venue_read_and_is_reaped(tmp_path, monkeypatch):
    children = []
    spawn = asyncio.create_subprocess_exec
    code = """
import time
from app.options.process_trace import ChildTrace
trace = ChildTrace()
trace.mark('IMPORTS')
time.sleep(10)
"""

    async def replace(*args, **kwargs):
        child = await spawn(sys.executable, "-I", "-c", code, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", replace)
    with owned(tmp_path) as (_, venue, _):
        with pytest.raises(FixtureProcessTimeout) as caught:
            asyncio.run(run_option_process(venue, now=NOW, timeout_seconds=1))
    details = failure_details(caught.value)["option_process"]
    assert [r["stage"] for r in details["child_stages"]] == ["IMPORTS"]
    assert all(c.returncode is not None for c in children)


@pytest.mark.parametrize("raw", [
    b"private-token\n", b"x" * (MAX_TRACE_BYTES + 1),
    b"OPTION_STAGE SNAPSHOT nan 0\n", b"OPTION_STAGE SNAPSHOT 0 -1\n",
    b"OPTION_STAGE SNAPSHOT 0 999999999\n",
    b"OPTION_STAGE IMPORTS 5 5\nOPTION_STAGE REQUEST 4 4\n",
    b"OPTION_STAGE IMPORTS 0 0\nOPTION_STAGE IMPORTS 1 1\n",
])
def test_unrecognized_or_oversized_stderr_is_discarded(raw):
    trace = TraceReader()
    trace.feed(raw)
    assert trace.invalid and not trace.records and not trace.pending
    trace.feed(b"OPTION_STAGE SNAPSHOT 1 1\n")
    assert not trace.records


def test_chunked_trace_and_plain_exception_cannot_leak_private_diagnostics():
    trace = TraceReader()
    trace.feed(b"OPTION_STAGE IMPORTS ")
    trace.feed(b"10 3\nOPTION_STAGE REQUEST 25 18\n")
    assert trace.records == [("IMPORTS", 10, 3), ("REQUEST", 25, 18)]
    exc = FixtureProcessTimeout("private message")
    exc.option_process_diagnostics = {"private": "private token"}
    assert "option_process" not in failure_details(exc)
    exc.option_process_diagnostics = OptionProcessDiagnostics(
        "RESPONSE_READ", 5.001, False, (("private token", 1, 1),)
    )
    assert "option_process" not in failure_details(exc)


def test_stderr_flood_does_not_deadlock_cleanup_or_retain_content(tmp_path, monkeypatch):
    spawn = asyncio.create_subprocess_exec
    children = []
    code = "import os,time; os.write(2, b'private-token' * 100000); time.sleep(10)"

    async def replace(*args, **kwargs):
        child = await spawn(sys.executable, "-I", "-c", code, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", replace)
    with owned(tmp_path) as (_, venue, _):
        with pytest.raises(FixtureProcessTimeout) as caught:
            asyncio.run(run_option_process(venue, now=NOW, timeout_seconds=1))
    details = failure_details(caught.value)
    assert details["option_process"]["child_trace_status"] == "INVALID"
    assert details["option_process"]["child_stages"] == []
    assert "private-token" not in json.dumps(details)
    assert all(c.returncode is not None for c in children)
