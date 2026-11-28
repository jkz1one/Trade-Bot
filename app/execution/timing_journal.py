"""Bounded diagnostic records committed with existing owner transactions.

Pending data is not durable evidence. A crash leaves an unfinished record or a
missing trace; the native slot/model commitments remain the report denominator.
No callback or caller-supplied SQL runs inside the owner transaction.
"""

from dataclasses import dataclass
import json
import sqlite3
from threading import Lock

MAX_PENDING = 64
MAX_PAYLOAD_BYTES = 65536


@dataclass(eq=False)
class _Record:
    owner: object
    at: str
    payload: str
    version: int = 1
    row_id: int | None = None
    flushing: bool = False


class RuntimeTimings:
    def __init__(self):
        self._pending = {}
        self._lock = Lock()

    @property
    def pending(self):
        with self._lock:
            return bool(self._pending)

    def start(self, at, value):
        payload = json.dumps(value, sort_keys=True)
        if len(payload.encode()) > MAX_PAYLOAD_BYTES:
            return None
        with self._lock:
            if len(self._pending) >= MAX_PENDING:
                return None
            record = _Record(self, at, payload)
            self._pending[record] = None
            return record

    def finish(self, record, value):
        if record is None or record.owner is not self:
            return
        payload = json.dumps(value, sort_keys=True)
        if len(payload.encode()) > MAX_PAYLOAD_BYTES:
            return  # An already stored RUNNING row remains explicit missing evidence.
        with self._lock:
            if record not in self._pending and len(self._pending) >= MAX_PENDING:
                return
            record.payload = payload
            record.version += 1
            self._pending[record] = None

    def flush(self, db):
        """Return acknowledgements to apply only after the outer commit succeeds."""
        with self._lock:
            pending = [(r, r.version, r.row_id, r.at, r.payload)
                       for r in self._pending if not r.flushing]
            for record, *_ in pending:
                record.flushing = True
        if not pending:
            return ()
        try:
            db.execute("SAVEPOINT runtime_timing_flush")
        except BaseException:
            self.rolled_back(pending)
            raise
        try:
            db.execute("CREATE TABLE IF NOT EXISTS execution_runtime_timings("
                       "id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,payload_json TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS runtime_timings_started ON execution_runtime_timings(started_at)")
            acknowledged = []
            for record, version, row_id, at, payload in pending:
                if row_id is None:
                    row_id = db.execute(
                        "INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)",
                        (at, payload)).lastrowid
                elif db.execute("UPDATE execution_runtime_timings SET payload_json=? WHERE id=?",
                                (payload, row_id)).rowcount != 1:
                    raise sqlite3.IntegrityError("Timing row unavailable")
                acknowledged.append((record, version, row_id))
            db.execute("RELEASE runtime_timing_flush")
            return acknowledged
        except sqlite3.Error:
            try:
                db.execute("ROLLBACK TO runtime_timing_flush")
                db.execute("RELEASE runtime_timing_flush")
            finally:
                self.rolled_back(pending)
            return ()  # Diagnostic storage must not roll back the owner's valid work.

    def committed(self, acknowledged):
        with self._lock:
            for record, version, row_id in acknowledged:
                record.row_id = row_id
                record.flushing = False
                if record.version == version:
                    self._pending.pop(record, None)

    def rolled_back(self, acknowledged):
        with self._lock:
            for record, *_ in acknowledged:
                record.flushing = False
