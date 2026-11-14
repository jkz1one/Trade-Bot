"""Timing preserves failures, old journals and original packet authority."""
import asyncio
from datetime import timedelta
import json
import sqlite3
import time

import pytest
from test_portfolio_feed import policy, reader
from test_robinhood_read_mapping import AT, schemas as schemas
from test_paper_session_report import module as reports
from app.mixed import continuous_feed
from app.mixed.continuous_feed import ContinuousFeed


def test_collector_times_success_failure_and_interruption_without_changing_packets(tmp_path, schemas, monkeypatch):
    native = continuous_feed.normalize
    def slow(*args, **kwargs):
        time.sleep(.02)
        return native(*args, **kwargs)
    monkeypatch.setattr(continuous_feed, 'normalize', slow)
    feed = ContinuousFeed(tmp_path / 'feed', policy(), schemas, create=True)
    async def exercise():
        assert (await feed.tick(now=AT, reader=reader(AT, [])))['status'] == 'DELIVERED'
        before = (feed.directory / 'feed.json').read_bytes()
        async def fail(*args, **kwargs):
            raise TimeoutError('private text not for telemetry')
        assert (await feed.tick(now=AT+timedelta(seconds=10), reader=fail))['status'] == 'FAILED'
        entered = asyncio.Event()
        async def stall(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(feed.tick(now=AT+timedelta(seconds=20), reader=stall))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (feed.directory / 'feed.json').read_bytes() == before
    asyncio.run(exercise())
    feed.close()
    feed = ContinuousFeed(tmp_path / 'feed', policy(), schemas)
    try:
        rows = [json.loads(r[0]) for r in feed.db.execute('SELECT payload_json FROM attempt_timings ORDER BY sequence')]
        assert [r['status'] for r in rows] == ['DELIVERED', 'FAILED', 'INTERRUPTED']
        assert rows[0]['phases']['NORMALIZE'] >= .02
        for row in rows:
            assert abs(sum(row['phases'].values())-row['elapsed_seconds']) < .00001
        assert 'private text' not in json.dumps(rows)
        summary = reports.timing_evidence(feed.db, AT.isoformat(), (AT+timedelta(seconds=30)).isoformat())
        assert summary['measured'] == 3 and summary['missing_or_invalid'] == 0
        assert set(summary['by_status']) == {'DELIVERED', 'FAILED', 'INTERRUPTED'}
    finally:
        feed.close()


def test_summary_keeps_missing_corrupt_and_failed_denominators():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('CREATE TABLE attempts(sequence INTEGER,started_at TEXT,status TEXT);'
                     'CREATE TABLE attempt_timings(sequence INTEGER,payload_json TEXT);')
    for n in range(1, 103):
        status = 'FAILED' if n == 100 else 'DELIVERED'
        db.execute('INSERT INTO attempts VALUES(?,?,?)', (n, AT.isoformat(), status))
        if n == 101:
            continue
        row = {'version':'collector-attempt-timing-v1', 'status':status,
               'elapsed_seconds': n/10, 'phases':{'CAPTURE':n/10},
               'read_process':{'parent_seconds':n/10, 'private':'SECRET', 'progress':[
                   {'stage':'CONNECT', 'elapsed_seconds':0},
                   {'stage':'DISCOVER', 'elapsed_seconds':.4}]}}
        if n == 102:
            row['elapsed_seconds'] = float('nan')
        db.execute('INSERT INTO attempt_timings VALUES(?,?)', (n,json.dumps(row)))
    result = reports.timing_evidence(db, AT.isoformat(), AT.isoformat())
    assert result['attempts'] == 102 and result['measured'] == 100
    assert result['missing_or_invalid'] == 2
    assert result['attempt_total'] == dict(samples=100,p50_seconds=5,p95_seconds=9.5,
                                         p99_seconds=9.9,max_seconds=10)
    assert result['by_status']['FAILED']['samples'] == 1
    assert result['child_observed_intervals']['CONNECT']['max_seconds'] == .4
    assert 'SECRET' not in json.dumps(result)
    db.execute('DROP TABLE attempt_timings')
    old = reports.timing_evidence(db, AT.isoformat(), AT.isoformat())
    assert old['status'] == 'UNAVAILABLE' and old['missing_or_invalid'] == 102
    db.close()
