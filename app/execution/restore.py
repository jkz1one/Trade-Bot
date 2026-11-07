"""Local rollback detection using an independently retained SQLite authority file.

This detects a journal-only restore while the current authority file survives.
It cannot detect rollback of both files or hostile access to their filesystem.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import quote

AUTHORITY_SCHEMA = "execution-restore-authority-v1"


def authority_path(path):
    return Path(str(path) + ".authority.db")


def _binding(db):
    if not db.execute(
        "SELECT 1 FROM main.sqlite_master WHERE name='execution_restore_binding'"
    ).fetchone():
        return None
    return db.execute("SELECT * FROM main.execution_restore_binding WHERE id=1").fetchone()


def _digest(db):
    """Hash complete logical state, including schema, receipts, keys and audit rows."""
    digest = hashlib.sha256()
    for row in db.execute(
        "SELECT type,name,sql FROM main.sqlite_master WHERE name GLOB 'execution_*' "
        "AND type IN ('table','trigger','index') ORDER BY type,name"
    ):
        digest.update(json.dumps(list(row), separators=(",", ":")).encode())
        if row[0] == "table":
            # Schema-derived names, escaped as identifiers, never supplied SQL.
            name = row[1].replace('"', '""')
            values = sorted(
                json.dumps(list(r), separators=(",", ":"))
                for r in db.execute(f'SELECT * FROM main."{name}"')
            )
            for value in values:
                digest.update(value.encode())
                digest.update(b"\n")
    return digest.hexdigest()


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
    generation = _binding(db)["generation"]
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
