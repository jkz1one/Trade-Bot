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
    calls = [s for s in trace['spans'] if s['phase'] == 'NATIVE_SNAPSHOT']
    assert [s['status'] for s in calls] == ['COMPLETE', 'FAILED', 'INTERRUPTED']
    spawns = [s for s in trace['spans'] if s['phase'] == 'NATIVE_SNAPSHOT_SPAWN']
    assert len(spawns) == 3
    for span, limit in zip(spawns, (2, .4, 2), strict=True):
        assert 0 < span['remaining_at_start_seconds'] <= limit
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
    measured = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
    assert measured["quote_age_by_phase"] == {"TICK:DISPATCH": {
        "samples": 1, "p50_seconds": 3, "p95_seconds": 3, "p99_seconds": 3, "max_seconds": 3,
    }}
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
    for i in range(20002):
        raw = json.loads(good)
        raw['private'] = 'PRIVATE'
        if i == 20000:
            raw['status'] = 'RUNNING'
        if i == 20001:
            raw['elapsed_seconds'] = float('nan')
        db.execute('INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)', (NOW.isoformat(), json.dumps(raw)))
    result = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
    assert (result['records'], result['omitted'], result['measured'], result['missing_or_invalid']) == (20003, 3, 19998, 2)
    assert result['by_status']['TICK:FAILED'] == 19998
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


def test_native_commitments_remain_counted_before_any_trace_and_after_unfinished_trace():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE execution_option_runtime_slots(slot INTEGER, status TEXT, started_at TEXT)')
    db.execute('CREATE TABLE execution_model_calls(source_key TEXT, started_at TEXT, cost TEXT)')
    at = NOW.isoformat()
    db.executemany('INSERT INTO execution_option_runtime_slots VALUES(?,?,?)',
        [(1, 'COMPLETE', at), (2, 'INTERRUPTED', at), (3, 'STARTED', at),
         (4, 'SKIPPED', at), (5, 'WAITING_FOR_FEED', at)])
    db.executemany('INSERT INTO execution_model_calls VALUES(?,?,?)',
                   [('settled', at, '.01'), ('unknown', at, None)])
    missing = reports.runtime_timing_evidence(db, at, at)['coverage']
    assert missing['cycles']['committed'] == missing['cycles']['without_matched_trace'] == 3
    assert missing['models']['committed'] == missing['models']['without_matched_trace'] == 2
    with runtime(db) as r:
        r._scheduler_delay = .25
        with timing.root(r, 'TICK'):
            timing.CURRENT.get()['native_omitted'] = 2
        with timing.root(r, 'CYCLE', slot=1):
            with timing.phase('ENTRY_MODEL', model_source_key='settled'):
                pass
        with timing.root(r, 'CYCLE', slot=3):
            with timing.phase('STOCK_MANAGEMENT_MODEL', model_source_key='unknown'):
                pass
    # The native attempt survived; its diagnostic update did not.
    db.execute("UPDATE execution_runtime_timings SET payload_json=json_set(payload_json,'$.status','RUNNING') WHERE id=3")
    result = reports.runtime_timing_evidence(db, at, at)
    assert result['coverage']['cycles']['matched'] == result['coverage']['models']['matched'] == 1
    assert result['coverage']['cycles']['without_matched_trace'] == 2
    assert result['coverage']['cycles']['not_started'] == 2
    assert result['coverage']['models']['without_matched_trace'] == result['coverage']['models']['unsettled'] == 1
    assert result['scheduler_delay']['max_seconds'] == .25 and result['native_omitted'] == 2
    assert result['missing_or_invalid'] == 1
    assert 'settled' not in json.dumps(result['recent'])
    db.close()


@pytest.mark.parametrize('after_trace_start', [False, True])
def test_real_process_exit_keeps_native_attempt_denominators(tmp_path, after_trace_start):
    import subprocess
    import sys
    path = tmp_path / 'crashed.db'
    program = '''
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
import os,sqlite3,sys
from app.options.runtime_timing import root
db=sqlite3.connect(sys.argv[1])
at=datetime.fromisoformat(sys.argv[2])
db.execute('CREATE TABLE execution_option_runtime_slots(slot INTEGER,status TEXT,started_at TEXT)')
db.execute('CREATE TABLE execution_model_calls(source_key TEXT,started_at TEXT,cost TEXT)')
db.execute("INSERT INTO execution_option_runtime_slots VALUES(1,'STARTED',?)",(at.isoformat(),))
db.execute("INSERT INTO execution_model_calls VALUES('committed-call',?,NULL)",(at.isoformat(),))
db.commit()
@contextmanager
def write():
    with db:
        yield db
r=SimpleNamespace(c=SimpleNamespace(now=lambda:at,engine=SimpleNamespace(journal=SimpleNamespace(write=write))),_bound=lambda _: {'generation':1})
if sys.argv[3]=='False':
    os._exit(17)
with root(r,'CYCLE',slot=1):
    os._exit(17)
'''
    result = subprocess.run([sys.executable, '-I', '-W', 'error', '-c', program,
        str(path), NOW.isoformat(), str(after_trace_start)], timeout=10, capture_output=True)
    assert result.returncode == 17, result.stderr.decode()
    db = reports.connection(path)
    try:
        result = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
        for name in ('cycles', 'models'):
            assert result['coverage'][name]['committed'] == result['coverage'][name]['without_matched_trace'] == 1
        assert result['coverage']['models']['unsettled'] == 1
        assert result['records'] == result['missing_or_invalid'] == int(after_trace_start)
        assert result['measured'] == 0
    finally:
        db.close()
