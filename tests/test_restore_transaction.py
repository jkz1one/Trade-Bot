"""Transaction-local timing reuse must equal the independent legacy v1 digest."""

import sqlite3

import pytest

from app.execution import restore, restore_transaction as tracked
from tests.test_execution_restore import context, fenced  # noqa: F401
from tests.test_restore_encoding import legacy_digest


@pytest.fixture
def journal(fenced):
    journal = fenced[0].journal
    with journal.write() as db:
        db.execute('CREATE TABLE execution_runtime_timings('
                   'id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,payload_json TEXT NOT NULL)')
        db.executemany('INSERT INTO execution_runtime_timings VALUES(?,?,?)',
                       [(i, 'time', f'payload-{i}-é') for i in range(300)])
    return journal


def verified(journal):
    with journal.read(verify_restore=True) as db:
        expected = legacy_digest(db)
        assert db.execute('SELECT state_hash FROM authority.restore_authority').fetchone()[0] == expected


@pytest.mark.parametrize('sql', [
    "UPDATE execution_runtime_timings SET payload_json='updated' WHERE id=12",
    "INSERT INTO execution_runtime_timings VALUES(800,'later','new')",
    'DELETE FROM execution_runtime_timings WHERE id=256',
    'DELETE FROM execution_runtime_timings',
    'UPDATE execution_runtime_timings SET id=id+500',
    'UPDATE OR REPLACE execution_runtime_timings SET id=22 WHERE id=21',
    "INSERT OR REPLACE INTO execution_runtime_timings VALUES(12,'replaced','new')",
    "INSERT INTO execution_runtime_timings VALUES(12,'upsert','new') ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json",
    "INSERT OR IGNORE INTO execution_runtime_timings VALUES(12,'ignored','new')",
])
def test_actual_mutations_keep_canonical_hash_and_skip_second_full_timing_read(journal, sql):
    statements = []
    with journal.write() as db:
        assert db._restore_snapshot.valid and not db._restore_snapshot.recording
        db.execute(sql)
        expected = legacy_digest(db)
        db.set_trace_callback(statements.append)
        assert restore._digest(db) == expected
        assert not any('SELECT * FROM main."execution_runtime_timings"' in s for s in statements)
    verified(journal)


def test_cached_statements_savepoints_and_indirect_trigger_mutations(journal):
    with journal.write() as db:
        db.execute('CREATE TRIGGER execution_mutate AFTER UPDATE OF halt_reason ON execution_control '
                   "BEGIN UPDATE execution_runtime_timings SET payload_json=NEW.halt_reason WHERE id=21; END")
    with journal.write() as db:
        statement = 'UPDATE execution_runtime_timings SET payload_json=? WHERE id=12'
        for value in ('first', 'second'):
            db.execute(statement, (value,))
        db.execute('SAVEPOINT test')
        db.execute('DELETE FROM execution_runtime_timings WHERE id=14')
        db.execute('ROLLBACK TO test')
        db.execute('RELEASE test')
        db.executemany(statement, [('third',), ('fourth',)])
        db.execute("UPDATE execution_control SET halt_reason='trigger'")
        assert {12, 14, 21} <= db._restore_snapshot.changed
        assert db._restore_snapshot.valid
        assert restore._digest(db) == legacy_digest(db)
    verified(journal)


@pytest.mark.parametrize('operation', ['authorizer', 'blob', 'function', 'schema', 'pragma', 'unique'])
def test_bypass_and_schema_changes_fall_back_to_full_scan(journal, operation):
    with journal.write() as db:
        if operation == 'authorizer':
            db.set_authorizer(None)
            db.execute("UPDATE execution_runtime_timings SET payload_json='changed'")
        elif operation == 'blob':
            with db.blobopen('execution_runtime_timings', 'payload_json', 2) as blob:
                blob.write(b'changed')
        elif operation == 'function':
            db.create_function('new_function', 0, lambda: 'new')
            db.execute('UPDATE execution_runtime_timings SET payload_json=new_function() WHERE id=2')
        elif operation == 'schema':
            db.execute('ALTER TABLE execution_runtime_timings ADD COLUMN more TEXT')
        elif operation == 'pragma':
            db.execute('PRAGMA recursive_triggers=OFF')
        else:
            db.execute('CREATE UNIQUE INDEX unique_payload ON execution_runtime_timings(payload_json)')
            # REPLACE deletes another rowid without DELETE triggers by default.
            db.execute("INSERT OR REPLACE INTO execution_runtime_timings VALUES(999,'time','payload-2-é')")
        statements = []
        db.set_trace_callback(statements.append)
        assert restore._digest(db) == legacy_digest(db)
        assert any('SELECT * FROM main."execution_runtime_timings"' in s for s in statements)
    verified(journal)


def test_noop_timing_schema_setup_preserves_reuse(journal):
    with journal.write() as db:
        db.execute('CREATE INDEX runtime_timings_started ON execution_runtime_timings(started_at)')
    with journal.write() as db:
        db.execute('CREATE TABLE IF NOT EXISTS execution_runtime_timings('
                   'id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,payload_json TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS runtime_timings_started ON execution_runtime_timings(started_at)')
        db.execute("INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES('later','new')")
        assert restore._digest(db) == legacy_digest(db)
        assert db._restore_snapshot.valid
    verified(journal)


@pytest.mark.parametrize('bound', ['MAX_BYTES', 'MAX_ROWS', 'MAX_CHANGED'])
def test_overflow_falls_back_and_retention_is_bounded(journal, monkeypatch, bound):
    monkeypatch.setattr(tracked, bound, 1)
    with journal.write() as db:
        db.execute("UPDATE execution_runtime_timings SET payload_json='new' WHERE id IN(1,2)")
        assert restore._digest(db) == legacy_digest(db)
        assert not db._restore_snapshot.valid
        assert db._restore_snapshot.size == 0 and not db._restore_snapshot.original
    verified(journal)


def test_rollback_releases_snapshot_and_next_write_checks_all_rows(journal):
    with pytest.raises(RuntimeError):
        with journal.write() as db:
            saved = db._restore_snapshot
            db.execute("UPDATE execution_runtime_timings SET payload_json='rollback'")
            raise RuntimeError('abort')
    assert not saved.valid and not saved.original
    verified(journal)
    with sqlite3.connect(journal.path) as other:
        other.execute("UPDATE execution_runtime_timings SET payload_json='untracked tamper' WHERE id=1")
    with pytest.raises(ValueError, match='RESTORED_OR_CHANGED_EXECUTION_JOURNAL'):
        with journal.write():
            pytest.fail('Tampered committed rows reused')


def test_other_writer_cannot_change_timing_rows_during_reuse(journal):
    with journal.write() as db:
        with sqlite3.connect(journal.path, timeout=0) as other:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute("UPDATE execution_runtime_timings SET payload_json='racing' WHERE id=1")
        assert restore._digest(db) == legacy_digest(db)
    verified(journal)


def test_unusual_unique_constraint_never_uses_row_tracking(journal):
    with journal.write() as db:
        db.execute('CREATE UNIQUE INDEX unique_payload ON execution_runtime_timings(payload_json)')
    with journal.write() as db:
        assert not db._restore_snapshot.valid
        db.execute("INSERT OR REPLACE INTO execution_runtime_timings VALUES(999,'time','payload-2-é')")
        assert restore._digest(db) == legacy_digest(db)
    verified(journal)


def test_unmodified_old_read_connections_keep_full_verification(journal):
    with journal.read(verify_restore=True) as db:
        assert not isinstance(db, tracked.FencedConnection)
        assert restore._digest(db) == legacy_digest(db)
    with journal.write() as db:
        saved = db._restore_snapshot
        assert saved.original
    assert not saved.original and not saved.valid


def test_foreign_key_cascade_and_failed_statement_effects_are_reread(journal):
    with journal.write() as db:
        db.execute('DROP TABLE execution_runtime_timings')
        db.execute('CREATE TABLE execution_timing_parent(id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE execution_runtime_timings('
                   'id INTEGER PRIMARY KEY REFERENCES execution_timing_parent(id) ON UPDATE CASCADE ON DELETE CASCADE,'
                   'started_at TEXT NOT NULL,payload_json TEXT NOT NULL)')
        db.executemany('INSERT INTO execution_timing_parent VALUES(?)', [(i,) for i in range(300)])
        db.executemany('INSERT INTO execution_runtime_timings VALUES(?,?,?)',
                       [(i, 'time', 'original') for i in range(300)])
    with journal.write() as db:
        db.execute('UPDATE execution_timing_parent SET id=900 WHERE id=1')
        db.execute('DELETE FROM execution_timing_parent WHERE id=2')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE execution_runtime_timings SET payload_json=CASE WHEN id=14 THEN NULL ELSE 'new' END")
        assert {1, 2, 900} <= db._restore_snapshot.changed
        assert restore._digest(db) == legacy_digest(db)
        assert db._restore_snapshot.valid
    verified(journal)


@pytest.mark.parametrize('end', ['COMMIT', 'ROLLBACK'])
def test_explicit_transaction_end_cannot_reuse_snapshot_after_rebegin(journal, end):
    with journal.write() as db:
        db.execute(end)
        db.execute('BEGIN IMMEDIATE')
        assert not db._restore_snapshot.valid
        db.execute("UPDATE execution_runtime_timings SET payload_json='after rebegin' WHERE id=1")
        assert restore._digest(db) == legacy_digest(db)
    verified(journal)
