"""Correlated diagnostics preserve cancellation, original clocks and failures."""
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_option_execution import NOW, owned
from test_paper_session_report import module as reports

from app.execution.process import FixtureProcessTimeout
from app.options import runtime_timing as timing
from app.options.process import run_option_process


def test_native_success_timeout_and_cancellation_keep_separate_spans_and_reap(tmp_path, monkeypatch):
    children = []
    spawn = asyncio.create_subprocess_exec
    async def watch(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', watch)
    trace = {'spans': [], 'native': [], 'spans_omitted': 0}
    async def exercise(venue):
        token = timing.CURRENT.set(trace)
        try:
            await run_option_process(venue, now=NOW, timeout_seconds=2)
            venue.fault = 'STALL_READ'
            with pytest.raises(FixtureProcessTimeout):
                await run_option_process(venue, now=NOW, timeout_seconds=.4)
            task = asyncio.create_task(run_option_process(venue, now=NOW, timeout_seconds=2))
            while len(children) < 3:
                await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            timing.CURRENT.reset(token)
    with owned(tmp_path) as (_, venue, _):
        before = venue.path.read_bytes()
        asyncio.run(exercise(venue))
        assert venue.path.read_bytes() == before
    assert [s['status'] for s in trace['spans']] == ['COMPLETE', 'FAILED', 'INTERRUPTED']
    assert len(trace['native']) == 3
    assert all(child.returncode is not None for child in children)
    assert str(tmp_path) not in json.dumps(trace)


@contextmanager
def runtime(db):
    @contextmanager
    def write():
        yield db
    yield SimpleNamespace(c=SimpleNamespace(now=lambda: NOW, engine=SimpleNamespace(
        journal=SimpleNamespace(write=write))), _bound=lambda _: {'generation': 7})


def test_cycle_context_isolated_from_concurrent_protection_and_original_clocks():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    async def exercise(r):
        waiting, release = asyncio.Event(), asyncio.Event()
        async def cycle():
            with timing.root(r, 'CYCLE', slot=123):
                with timing.phase('ENTRY_MODEL'):
                    waiting.set()
                    await release.wait()
        with timing.root(r, 'TICK'):
            task = asyncio.create_task(cycle())
            await waiting.wait()
            with timing.phase('DISPATCH', now=NOW, quote=SimpleNamespace(
                    source_at=NOW-timedelta(seconds=3), received_at=NOW-timedelta(seconds=2))):
                pass
            release.set()
            await task
    with runtime(db) as r:
        asyncio.run(exercise(r))
    records = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM execution_runtime_timings ORDER BY id')]
    assert [s['phase'] for s in records[0]['spans']] == ['DISPATCH']
    assert [s['phase'] for s in records[1]['spans']] == ['ENTRY_MODEL']
    span = records[0]['spans'][0]
    assert (span['quote_age_seconds'], span['receive_lag_seconds'], span['local_age_seconds']) == (3, 1, 2)
    assert timing.CURRENT.get() is None
    db.close()


def test_report_counts_unfinished_corrupt_omitted_and_failed_without_private_fields():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    with runtime(db) as r:
        with pytest.raises(ValueError):
            with timing.root(r, 'TICK'):
                with timing.phase('NATIVE_SNAPSHOT'):
                    raise ValueError('PRIVATE')
    good = db.execute('SELECT payload_json FROM execution_runtime_timings').fetchone()[0]
    for i in range(2002):
        raw = json.loads(good)
        raw['private'] = 'PRIVATE'
        if i == 2000:
            raw['status'] = 'RUNNING'
        if i == 2001:
            raw['elapsed_seconds'] = float('nan')
        db.execute('INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)', (NOW.isoformat(), json.dumps(raw)))
    result = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
    assert (result['records'], result['omitted'], result['measured'], result['missing_or_invalid']) == (2003, 3, 1998, 2)
    assert result['by_status']['TICK:FAILED'] == 1998
    assert 'PRIVATE' not in json.dumps(result)
    assert len(result['recent']) == 25
    db.close()


def test_diagnostic_storage_failure_does_not_interrupt_protection():
    @contextmanager
    def broken():
        raise sqlite3.OperationalError('unavailable diagnostic storage')
        yield
    r = SimpleNamespace(c=SimpleNamespace(now=lambda: NOW, engine=SimpleNamespace(
        journal=SimpleNamespace(write=broken))))
    with timing.root(r, 'TICK'):
        with timing.phase('PROTECTION'):
            assert timing.CURRENT.get() is not None
    assert timing.CURRENT.get() is None
