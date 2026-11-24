"""Local rollback detection using an independently retained SQLite authority file.

This detects a journal-only restore while the current authority file survives.
It cannot detect rollback of both files or hostile access to their filesystem.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import uuid
from collections import OrderedDict
from itertools import chain, count, islice
from json.encoder import encode_basestring_ascii
from pathlib import Path
from threading import Lock
from urllib.parse import quote

from app.execution.restore_rows import RowEncodings

AUTHORITY_SCHEMA = "execution-restore-authority-v1"


# Handles are process-local, never recycled, and start outside the JSON grammar.
# They stand only for exact text/delimiter pairs found in the bounded encoding cache.
_handles = count(1)


class _TextEncodingCache:
    """Reuse exact JSON tokens during repeated full-journal scans.

    Evict the most recently used entry: a scan longer than the cache otherwise
    evicts every old row just before it is needed again. Entries remain bounded
    and every hit still compares the entire original string and delimiter.
    """

    def __init__(self, max_bytes=192 * 1024 * 1024, max_entries=32768):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.size = 0
        self.values = OrderedDict()
        self.lock = Lock()
        self.recent_long = [None] * 16
        self.scope = None

    def select_authority(self, authority_id):
        # MRU must not pin an unrelated account's history. Display copies with
        # the same restore binding can reuse encodings; another account starts
        # cold. The identifier only selects a cache, never grants trust.
        with self.lock:
            if self.scope != authority_id:
                self.values.clear()
                self.recent_long = [None] * 16
                self.size = 0
                self.scope = authority_id

    def encode(self, value, delimiter):
        return self.tokens(value, delimiter)[0]

    def tokens(self, value, delimiter):
        # SQLite returns a new string for each row. When a long cell repeats,
        # exact equality lets the dict reuse its original key's computed hash.
        key = (value, delimiter)
        slot = len(value) % len(self.recent_long) if len(value) > 4096 else None
        with self.lock:
            if slot is not None:
                recent = self.recent_long[slot]
                if recent is not None and recent == key:
                    key = recent
            entry = self.values.get(key)
            if entry is not None:
                self.values.move_to_end(key)
                if slot is not None:
                    self.recent_long[slot] = next(reversed(self.values))
                return entry[0]
        token = encode_basestring_ascii(value).encode("ascii") + delimiter
        comparison = (b"@" + str(next(_handles)).encode("ascii") + delimiter
                      if len(token) > 128 else token)
        pair = (token, comparison)
        weight = sys.getsizeof(key) + sys.getsizeof(value) + sys.getsizeof(token) + sys.getsizeof(pair)
        if comparison is not token:
            weight += sys.getsizeof(comparison)
        if weight <= self.max_bytes and self.max_entries > 0:
            with self.lock:
                if key in self.values:
                    self.values.move_to_end(key)
                    return self.values[key][0]
                while self.values and (
                    self.size + weight > self.max_bytes or len(self.values) >= self.max_entries
                ):
                    # MRU preserves most of an overflowing sequential scan;
                    # LRU turns the next scan into an all-miss encoding pass.
                    evicted, (_, old_weight) = self.values.popitem(last=True)
                    if len(evicted[0]) > 4096:
                        old_slot = len(evicted[0]) % len(self.recent_long)
                        if self.recent_long[old_slot] is evicted:
                            self.recent_long[old_slot] = None
                    self.size -= old_weight
                self.values[key] = (pair, weight)
                if slot is not None:
                    self.recent_long[slot] = key
                self.size += weight
        return pair


# Keep the combined encoding budget at 192 MiB. Large tables retain canonical
# row batches without a second full copy of each original string.
_TEXT_ENCODINGS = _TextEncodingCache(max_bytes=32 * 1024 * 1024)
_ROW_ENCODINGS = RowEncodings()


def _select_authority(authority_id):
    _TEXT_ENCODINGS.select_authority(authority_id)
    if _ROW_ENCODINGS is not None:
        _ROW_ENCODINGS.select_authority(authority_id)


def _row_tokens(row, comparison=None):
    # Each token includes its trailing comma or bracket. Delimiters cannot be
    # part of an unquoted scalar, so tuple order equals canonical row-byte order,
    # including prefix cases such as [1], [10] and [1,0], [10,0].
    tokens = []
    if comparison is not None:
        comparison.extend(b"[")
    last = len(row) - 1
    for index, value in enumerate(row):
        delimiter = b"]" if index == last else b","
        if type(value) is str:
            token, reference = _TEXT_ENCODINGS.tokens(value, delimiter)
        elif type(value) is int:
            token = str(value).encode("ascii") + delimiter
        elif value is None:
            token = b"null" + delimiter
        else:
            # Keep v1 spelling of floats (including signed zero), and the
            # original rejection of unsupported SQLite blob values.
            token = json.dumps(value, separators=(",", ":")).encode("ascii") + delimiter
        tokens.append(token)
        if comparison is not None:
            comparison.extend(reference if type(value) is str else token)
    if comparison is not None:
        comparison.extend(b"\n")
    return tuple(tokens)


def authority_path(path):
    return Path(str(path) + ".authority.db")


def _binding(db):
    if not db.execute(
        "SELECT 1 FROM main.sqlite_master WHERE name='execution_restore_binding'"
    ).fetchone():
        return None
    return db.execute("SELECT * FROM main.execution_restore_binding WHERE id=1").fetchone()


# A prefix consists of the exact schema and rows read during the last full
# scan and the corresponding v1 SHA state. Other callers can still scan
# concurrently. A miss, an eviction or a different SQLite row order simply
# computes the canonical sorted v1 stream again.
_PREFIX_BYTES = 4 * 1024 * 1024
_PREFIX_ITEMS = 256
_prefix_lock = Lock()
_prefixes = ()


def _digest(db):
    global _prefixes
    if not _prefix_lock.acquire(blocking=False):
        # A simultaneous reader can compare with the last immutable prefix.
        # Only the lock holder publishes a replacement.
        return _scan(db, _prefixes, _PREFIX_BYTES, retain=False)[0]
    try:
        digest, prefixes = _scan(db, _prefixes, _PREFIX_BYTES)
        _prefixes = prefixes
        return digest
    finally:
        _prefix_lock.release()


def _scan(db, previous, budget, *, retain=True):
    digest = hashlib.sha256()
    prefixes = []
    matching = True
    schema = db.execute(
        "SELECT type,name,sql FROM main.sqlite_master WHERE name GLOB 'execution_*' "
        "AND type IN ('table','trigger','index') ORDER BY type,name"
    )
    for index, row in enumerate(schema):
        definition = json.dumps(list(row), separators=(",", ":")).encode()
        budget -= len(definition)
        may_compare = retain or (matching and index < len(previous))
        comparison = bytearray() if may_compare and budget > 0 and index < _PREFIX_ITEMS else None
        rows = []
        batched = False
        if row[0] == "table":
            name = row[1].replace('"', '""')
            cursor = iter(db.execute(f'SELECT * FROM main."{name}"'))
            first = tuple(islice(cursor, 256))
            batched = len(first) == 256 and _ROW_ENCODINGS is not None
            if batched:
                if comparison is not None:
                    comparison.extend(b'ROW-BATCH-SHA256:')
                batch = first
                batch_index = 0
                while batch:
                    key, encoded = _ROW_ENCODINGS.encode(batch, slot=(row[1], batch_index))
                    rows.extend(encoded)
                    if comparison is not None:
                        comparison.extend(key)
                        if len(comparison) > budget:
                            comparison = None
                            budget = 0
                    batch = tuple(islice(cursor, 256))
                    batch_index += 1
            else:
                for item in chain(first, cursor):
                    rows.append(_row_tokens(item, comparison))
                    if comparison is not None and len(comparison) > budget:
                        comparison = None
                        budget = 0
        if (matching and comparison is not None and index < len(previous)
                and previous[index][:2] == (definition, comparison)):
            digest = previous[index][2].copy()
        else:
            matching = False
            digest.update(definition)
            rows.sort()
            for tokens in rows:
                if batched:
                    digest.update(tokens)
                else:
                    digest.update(b"[")
                    for token in tokens:
                        digest.update(token)
                    digest.update(b"\n")
        if comparison is not None:
            budget -= len(comparison)
            if retain:
                prefixes.append((definition, bytes(comparison), digest.copy()))
    return digest.hexdigest(), tuple(prefixes)


def _attach(db, path, *, writable):
    mode = "rw" if writable else "ro"
    db.execute("ATTACH DATABASE ? AS authority", ("file:" + quote(str(path)) + "?mode=" + mode,))


def _check(db):
    binding = _binding(db)
    if not binding:
        raise ValueError("RESTORE_FENCE_BINDING_MISSING")
    tables = {
        r[0] for r in db.execute("SELECT name FROM authority.sqlite_master WHERE type='table'")
    }
    if tables != {"restore_authority"}:
        raise ValueError("RESTORE_AUTHORITY_SCHEMA_INVALID")
    row = db.execute("SELECT * FROM authority.restore_authority WHERE id=1").fetchone()
    if (
        not row
        or row["schema"] != AUTHORITY_SCHEMA
        or row["authority_id"] != binding["authority_id"]
    ):
        raise ValueError("RESTORE_AUTHORITY_BINDING_MISMATCH")
    _select_authority(binding["authority_id"])
    if row["generation"] != binding["generation"] or row["state_hash"] != _digest(db):
        raise ValueError("RESTORED_OR_CHANGED_EXECUTION_JOURNAL")
    return binding


def begin_fenced_write(db, path):
    """Attach before BEGIN; lock/check both files before yielding any mutation."""
    required = _binding(db) is not None or path.exists()
    if not required:
        db.execute("BEGIN IMMEDIATE")
        return False
    if not path.is_file():
        raise ValueError("RESTORE_AUTHORITY_MISSING")
    _attach(db, path, writable=True)
    for schema in ("main", "authority"):
        # Reject, rather than change, unsupported persistent journal modes.
        if db.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0] != "delete":
            raise ValueError("RESTORE_FENCE_REQUIRES_DELETE_JOURNAL")
        db.execute(f"PRAGMA {schema}.synchronous=FULL")
    db.execute("BEGIN IMMEDIATE")
    _check(db)
    return True


def advance(db):
    db.execute("UPDATE main.execution_restore_binding SET generation=generation+1 WHERE id=1")
    binding = _binding(db)
    generation = binding["generation"]
    _select_authority(binding["authority_id"])
    db.execute(
        "UPDATE authority.restore_authority SET generation=?,state_hash=? WHERE id=1",
        (generation, _digest(db)),
    )


def status(db, path):
    required = _binding(db) is not None or path.exists()
    if not required:
        return {"status": "UNFENCED"}
    try:
        if not path.is_file():
            raise ValueError("RESTORE_AUTHORITY_MISSING")
        _attach(db, path, writable=False)
        for schema in ("main", "authority"):
            if db.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0] != "delete":
                raise ValueError("RESTORE_FENCE_REQUIRES_DELETE_JOURNAL")
        binding = _check(db)
        return {
            "status": "VERIFIED",
            "authority_id": binding["authority_id"],
            "generation": binding["generation"],
        }
    except (ValueError, sqlite3.Error) as exc:
        return {"status": "BLOCKED", "reason": str(exc)}


def enable(journal, *, now):
    """Explicit trusted local provisioning. Never adopt/overwrite a sidecar."""
    if not journal.writable:
        raise ValueError("Journal was opened read-only")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Execution clock must be timezone-aware")
    path = authority_path(journal.path)
    with journal.read() as db:
        existing = status(db, path)
    if existing["status"] == "VERIFIED":
        return existing
    if existing["status"] != "UNFENCED":
        raise ValueError(existing["reason"])
    # An exclusive empty reservation may remain after failed provisioning. Never
    # guess whether a failed commit succeeded or silently replace such a file.
    path.touch(mode=0o600, exist_ok=False)
    path.chmod(0o600)
    db = sqlite3.connect(
        "file:" + quote(str(journal.path)) + "?mode=rw", uri=True, isolation_level=None, timeout=10
    )
    db.row_factory = sqlite3.Row
    try:
        _attach(db, path, writable=True)
        for schema in ("main", "authority"):
            if db.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0] != "delete":
                raise ValueError("RESTORE_FENCE_REQUIRES_DELETE_JOURNAL")
            db.execute(f"PRAGMA {schema}.synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        if _binding(db) is not None:
            raise ValueError("RESTORE_FENCE_ALREADY_BOUND")
        identifier = str(uuid.uuid4())
        db.execute(
            "CREATE TABLE main.execution_restore_binding (id INTEGER PRIMARY KEY CHECK(id=1), authority_id TEXT NOT NULL, generation INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO main.execution_restore_binding VALUES(1,?,0)", (identifier,))
        db.execute(
            "CREATE TABLE authority.restore_authority (id INTEGER PRIMARY KEY CHECK(id=1), schema TEXT NOT NULL, authority_id TEXT NOT NULL, generation INTEGER NOT NULL, state_hash TEXT NOT NULL)"
        )
        journal.event(db, now, "RESTORE_FENCE_ENABLED", {"authority_id": identifier})
        _select_authority(identifier)
        db.execute(
            "INSERT INTO authority.restore_authority VALUES(1,?,?,0,?)",
            (AUTHORITY_SCHEMA, identifier, _digest(db)),
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return {"status": "VERIFIED", "authority_id": identifier, "generation": 0}
