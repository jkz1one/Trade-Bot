"""Diagnostic coalescing preserves owner commits, restore fences and missing evidence."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.execution import restore
from app.execution.timing_journal import MAX_PENDING, RuntimeTimings
from app.options import runtime_timing as timing
from app.options.engine import OptionJournal
from test_option_execution import NOW, owned
from test_paper_session_report import module as reports


def runtime(engine):
    return SimpleNamespace(c=SimpleNamespace(now=lambda: NOW, engine=engine),
                           _bound=lambda db: {'generation': 1})


def records(journal):
    with journal.read(verify_restore=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_runtime_timings'").fetchone():
            return []
        return [json.loads(row[0]) for row in db.execute(
            'SELECT payload_json FROM execution_runtime_timings ORDER BY id')]


def generation(journal):
    with journal.read(verify_restore=True) as db:
        return db.execute('SELECT generation FROM execution_restore_binding').fetchone()[0]


def test_trace_uses_only_existing_fenced_commits_and_close_flush(tmp_path):
    with owned(tmp_path) as (engine, _, _):
        journal = engine.journal
        before = generation(journal)
        with timing.root(runtime(engine), 'TICK'):
            assert records(journal) == []
            assert generation(journal) == before  # Starting a trace is read-only.
            with journal.write():
                pass
            assert records(journal)[0]['status'] == 'RUNNING'
        assert generation(journal) == before + 1
        assert records(journal)[0]['status'] == 'RUNNING'
        observer = OptionJournal(journal.path)
        observer.flush_timings()
        assert generation(journal) == before + 1
    assert generation(journal) == before + 2
    assert records(journal)[0]['status'] == 'COMPLETE'
    with journal.read() as db:
        report = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
    assert report['measured'] == 1 and report['trace_start_write'] is None
    assert report['trace_storage'] == {'COALESCED': 1}
    assert report['trace_start_prepare']['samples'] == 1


@pytest.mark.parametrize('rollback', ['body', 'fence'])
def test_failed_transaction_keeps_diagnostics_pending_for_retry(tmp_path, monkeypatch, rollback):
    with owned(tmp_path) as (engine, _, _):
        journal = engine.journal
        with timing.root(runtime(engine), 'TICK'):
            pass
        before = generation(journal)
        with monkeypatch.context() as patch:
            if rollback == 'fence':
                def fail(_):
                    raise ValueError('failed authority update')
                patch.setattr(restore, 'advance', fail)
            with pytest.raises(ValueError):
                with journal.write() as db:
                    db.execute("UPDATE execution_control SET halt_reason='must roll back'")
                    if rollback == 'body':
                        raise ValueError('failed owner transaction')
        assert records(journal) == [] and generation(journal) == before
        assert journal.runtime_timings.pending
        with journal.write() as db:
            assert db.execute('SELECT halt_reason FROM execution_control').fetchone()[0] != 'must roll back'
        assert len(records(journal)) == 1 and not journal.runtime_timings.pending


def test_finish_during_commit_retries_update_without_duplicate_rows():
    queue = RuntimeTimings()
    db = sqlite3.connect(':memory:')
    record = queue.start('now', {'status': 'RUNNING'})
    db.execute('BEGIN')
    acknowledged = queue.flush(db)
    assert not queue.flush(db)  # Another writer cannot claim the same pending insert.
    queue.finish(record, {'status': 'COMPLETE'})
    db.commit()
    queue.committed(acknowledged)
    assert queue.pending
    db.execute('BEGIN')
    acknowledged = queue.flush(db)
    db.commit()
    queue.committed(acknowledged)
    assert not queue.pending
    assert db.execute('SELECT payload_json FROM execution_runtime_timings').fetchall() == [('{"status": "COMPLETE"}',)]
    db.close()


def test_failed_diagnostic_savepoint_preserves_valid_owner_change(tmp_path):
    with owned(tmp_path) as (engine, _, _):
        journal = engine.journal
        with timing.root(runtime(engine), 'TICK'):
            pass
        journal.flush_timings()
        with journal.write() as db:
            db.execute("CREATE TRIGGER reject_timing BEFORE INSERT ON execution_runtime_timings "
                       "BEGIN SELECT RAISE(ABORT,'no diagnostic space'); END")
        with timing.root(runtime(engine), 'TICK'):
            pass
        with journal.write() as db:
            db.execute("UPDATE execution_control SET halt_reason='valid owner change'")
        assert len(records(journal)) == 1 and journal.runtime_timings.pending
        with journal.read(verify_restore=True) as db:
            assert db.execute('SELECT halt_reason FROM execution_control').fetchone()[0] == 'valid owner change'
        with journal.write() as db:
            db.execute('DROP TRIGGER reject_timing')
        journal.flush_timings()
        assert len(records(journal)) == 2 and not journal.runtime_timings.pending


def test_queue_is_bounded_and_cannot_adopt_another_owners_record():
    queue, other = RuntimeTimings(), RuntimeTimings()
    assert queue.start('now', {'payload': 'x' * 65536}) is None
    for i in range(MAX_PENDING):
        assert queue.start('now', {'id': i}) is not None
    assert queue.start('now', {}) is None
    record = other.start('now', {'owner': 'other'})
    queue.finish(record, {'owner': 'wrong'})
    assert json.loads(record.payload) == {'owner': 'other'}


@pytest.mark.parametrize('error,status', [(ValueError, 'FAILED'), (asyncio.CancelledError, 'INTERRUPTED')])
def test_owner_close_persists_failure_without_changing_the_exception(tmp_path, error, status):
    failure = error('original failure')
    with pytest.raises(error) as observed:
        with owned(tmp_path) as (engine, _, _):
            journal = engine.journal
            with timing.root(runtime(engine), 'TICK'):
                raise failure
    assert observed.value is failure
    assert records(journal)[0]['status'] == status


@pytest.mark.parametrize('damage', [
    {'trace_start_prepare_seconds': float('nan')},
    {'trace_storage': 'UNKNOWN'},
    {'trace_start_write_seconds': 0},
])
def test_report_rejects_invalid_coalesced_timing_without_dropping_record(tmp_path, damage):
    with owned(tmp_path) as (engine, _, _):
        journal = engine.journal
        with timing.root(runtime(engine), 'TICK'):
            pass
        journal.flush_timings()
        original, = records(journal)
        with journal.write() as db:
            db.execute('UPDATE execution_runtime_timings SET payload_json=?',
                       (json.dumps({**original, **damage}),))
        with journal.read() as db:
            report = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
        assert report['records'] == report['missing_or_invalid'] == 1
        assert report['measured'] == 0


@pytest.mark.parametrize('committed_start', [False, True])
def test_unflushed_trace_never_counts_as_completed_native_work(tmp_path, committed_start):
    with owned(tmp_path) as (engine, _, _):
        journal = engine.journal
        with journal.write() as db:
            db.execute('CREATE TABLE execution_option_runtime_slots(slot INTEGER,status TEXT,started_at TEXT)')
            db.execute("INSERT INTO execution_option_runtime_slots VALUES(1,'STARTED',?)", (NOW.isoformat(),))
        with timing.root(runtime(engine), 'CYCLE', slot=1):
            if committed_start:
                with journal.write():
                    pass
        with journal.read() as db:
            report = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
        assert report['measured'] == 0
        assert report['coverage']['cycles']['without_matched_trace'] == 1
        assert report['records'] == report['missing_or_invalid'] == int(committed_start)


@pytest.mark.parametrize('repeat', [False, True])
def test_coalesced_trace_cannot_bypass_restore_before_quote_fill(tmp_path, monkeypatch, repeat):
    from test_mixed_entry import owner
    from test_mixed_runtime import send
    from test_mixed_selection import stock_frame
    from test_option_runtime import enable, policy, step
    from app.mixed import quote_fills
    from app.options.runtime import OptionRuntime

    with owner(tmp_path, monkeypatch, mode='HOLD') as (c, venue, _, _):
        r = OptionRuntime(c, policy(tmp_path, mixed_inputs='mixed-runtime-inputs-v1',
                                  simulated_fills='mixed-quote-fills-v1'), create=True)
        enable(r)
        send(r, stock_frame(), kind='CYCLE')
        if repeat:
            asyncio.run(step(r))
        fills = []
        monkeypatch.setattr(quote_fills, 'apply_quote_fills', lambda *args: fills.append(True))
        with sqlite3.connect(c.engine.journal.path) as db:
            db.execute("UPDATE execution_control SET halt_reason='tampered'")
        with pytest.raises(ValueError, match='RESTORED_OR_CHANGED_EXECUTION_JOURNAL'):
            asyncio.run(r.tick())
        assert not fills and venue.submit_count == 0
