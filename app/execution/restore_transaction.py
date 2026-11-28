"""Reuse verified timing rows only inside one locked restore-fence transaction.

Every writer still verifies every committed row. Connection-local TEMP triggers
track the timing rows changed before the second v1 digest. Unknown operations
fall back to the original full scan; no checkpoint or trust survives a commit.
"""

import json
import sqlite3
import sys
from uuid import uuid4

TABLE = 'execution_runtime_timings'
MAX_BYTES = 160 * 1024 * 1024
MAX_ROWS = 40000
MAX_CHANGED = 4096


class TimingSnapshot:
    def __init__(self):
        self.recording = True
        self.valid = True
        self.definition = None
        self.schema_version = None
        self.original = {}
        self.changed = set()
        self.size = 0

    def invalidate(self):
        self.valid = False
        self.original.clear()
        self.changed.clear()
        self.size = 0

    def select(self, db, definition):
        if not self.valid or not self.recording:
            return False
        columns = [tuple(row) for row in db.execute(f'PRAGMA main.table_xinfo({TABLE})')]
        # A rowid alias is the sole unique key. REPLACE may omit DELETE triggers;
        # its INSERT/UPDATE still identifies the replaced row with this schema.
        expected = [(0, 'id', 'INTEGER', 0, None, 1, 0),
                    (1, 'started_at', 'TEXT', 1, None, 0, 0),
                    (2, 'payload_json', 'TEXT', 1, None, 0, 0)]
        if columns != expected or any(row[2] for row in db.execute(f'PRAGMA main.index_list({TABLE})')):
            self.invalidate()
            return False
        self.definition = definition
        self.schema_version = db.execute('PRAGMA main.schema_version').fetchone()[0]
        return True

    def add(self, batch, encoded):
        if not self.valid:
            return
        for row, value in zip(batch, encoded, strict=True):
            if type(row[0]) is not int or row[0] in self.original:
                self.invalidate()
                return
            # Encoded bytes usually share the existing row cache; count their
            # complete size anyway, including a conservative mapping allowance.
            self.size += sys.getsizeof(value) + sys.getsizeof(row[0]) + 128
            if self.size > MAX_BYTES or len(self.original) >= MAX_ROWS:
                self.invalidate()
                return
            self.original[row[0]] = value

    def changed_row(self, old, new):
        if not self.valid:
            return
        try:
            for identity in (old, new):
                if identity is not None:
                    if type(identity) is not int:
                        raise ValueError('INTEGER_TIMING_ID_REQUIRED')
                    self.changed.add(identity)
            if len(self.changed) > MAX_CHANGED:
                self.invalidate()
        except BaseException:
            self.invalidate()
            raise

    def authorize(self, action, first, second, database, source):
        # DML effects are tracked at execution time by TEMP triggers, including
        # cached statements and indirect trigger/foreign-key effects. This
        # compile-time callback only invalidates on unsupported operations.
        safe = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE}
        if action not in safe:
            # Existing timing flushes prepare these no-op IF NOT EXISTS DDLs.
            # New indexes change schema, not row contents; the full schema is
            # always hashed again, and unique-index creation disables replay.
            harmless = (action == sqlite3.SQLITE_CREATE_TABLE and first == TABLE
                        or action == sqlite3.SQLITE_CREATE_INDEX
                        or action == sqlite3.SQLITE_PRAGMA and first == 'schema_version'
                        and second is None)
            if not harmless:
                self.invalidate()
        return sqlite3.SQLITE_OK

    def arm(self, db):
        self.recording = False
        if not self.valid or self.definition is None or not db.in_transaction:
            self.invalidate()
            return
        name = 'restore_timing_' + uuid4().hex
        sqlite3.Connection.create_function(db, name, 2, self.changed_row)
        for operation, arguments in (
            ('INSERT', 'NULL,NEW.id'), ('UPDATE', 'OLD.id,NEW.id'), ('DELETE', 'OLD.id,NULL')
        ):
            db.execute(f'CREATE TEMP TRIGGER "{name}_{operation}" AFTER {operation} '
                       f'ON main.{TABLE} BEGIN SELECT "{name}"({arguments}); END')
        sqlite3.Connection.set_authorizer(db, self.authorize)

    def rows(self, db, definition):
        if self.recording or not self.valid or not db.in_transaction or definition != self.definition:
            return None
        # A new UNIQUE index would allow REPLACE to delete a different rowid.
        # Any actual schema change disables reuse, even if this table's CREATE
        # text is unchanged. The callback rejects schema_version assignments.
        if db.execute('PRAGMA main.schema_version').fetchone()[0] != self.schema_version:
            self.invalidate()
            return None
        rows = self.original.copy()
        for identity in self.changed:
            row = db.execute(f'SELECT * FROM main.{TABLE} WHERE id=?', (identity,)).fetchone()
            if row is None:
                rows.pop(identity, None)
            else:
                rows[identity] = json.dumps(list(row), separators=(',', ':')).encode() + b'\n'
        return list(rows.values())


class FencedConnection(sqlite3.Connection):
    """Invalidate on APIs that can bypass SQL row triggers or end the lock."""

    _restore_snapshot = None

    def _invalidate_snapshot(self):
        if self._restore_snapshot is not None:
            self._restore_snapshot.invalidate()

    def __setattr__(self, name, value):
        if name in {'isolation_level', 'autocommit', 'row_factory', 'text_factory'}:
            self._invalidate_snapshot()
        super().__setattr__(name, value)

    def commit(self):
        self._invalidate_snapshot()
        return super().commit()

    def rollback(self):
        self._invalidate_snapshot()
        return super().rollback()

    def close(self):
        self._invalidate_snapshot()
        try:
            return super().close()
        finally:
            self._restore_snapshot = None

    def executescript(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().executescript(*args, **kwargs)

    def blobopen(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().blobopen(*args, **kwargs)

    def deserialize(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().deserialize(*args, **kwargs)

    def set_authorizer(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().set_authorizer(*args, **kwargs)

    def create_function(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().create_function(*args, **kwargs)

    def create_aggregate(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().create_aggregate(*args, **kwargs)

    def create_window_function(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().create_window_function(*args, **kwargs)

    def enable_load_extension(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().enable_load_extension(*args, **kwargs)

    def load_extension(self, *args, **kwargs):
        self._invalidate_snapshot()
        return super().load_extension(*args, **kwargs)
