"""Separate SQLite write-ahead journal; money is stored as decimal JSON strings."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from app.execution.models import Ledger

SCHEMA = "execution-rehearsal-v1"


class ExecutionJournal:
    def __init__(self, path: str | Path, config: dict | None = None):
        self.path = Path(path).expanduser().resolve()
        self.writable = config is not None
        if config is None:
            with self.read() as db:
                row = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
                if row is None or json.loads(row[0]).get("schema") != SCHEMA:
                    raise ValueError("Not an execution rehearsal database")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.touch(mode=0o600, exist_ok=False)
        except FileExistsError:
            pass
        with self.write() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            allowed = {
                "execution_control",
                "execution_orders",
                "execution_fills",
                "execution_events",
                "execution_snapshots",
                "execution_fixture_binding",
                "sqlite_sequence",
            }
            if tables - allowed:
                raise ValueError("Execution rehearsal requires a separate database")
            # Individual statements preserve the surrounding BEGIN IMMEDIATE.
            for sql in (
                "CREATE TABLE IF NOT EXISTS execution_fixture_binding (id INTEGER PRIMARY KEY CHECK(id=1), venue_id TEXT NOT NULL, account_id TEXT NOT NULL)",
                (
                    "CREATE TABLE IF NOT EXISTS execution_control (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "config_json TEXT NOT NULL, ledger_json TEXT NOT NULL, halted INTEGER NOT NULL, "
                    "halt_reason TEXT, snapshot_json TEXT, issues_json TEXT NOT NULL)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS execution_orders (client_id TEXT PRIMARY KEY, "
                    "source_key TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL, intent_json TEXT NOT NULL, "
                    "approval_json TEXT NOT NULL, status TEXT NOT NULL, active_lock INTEGER UNIQUE, "
                    "order_id TEXT UNIQUE, attempted_at TEXT, observation_json TEXT)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS execution_fills (fill_id TEXT PRIMARY KEY, "
                    "client_id TEXT NOT NULL REFERENCES execution_orders(client_id), payload TEXT NOT NULL)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS execution_snapshots (snapshot_id TEXT PRIMARY KEY, "
                    "payload TEXT NOT NULL)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS execution_events (sequence INTEGER PRIMARY KEY, "
                    "occurred_at TEXT NOT NULL, kind TEXT NOT NULL, client_id TEXT, payload TEXT NOT NULL)"
                ),
            ):
                db.execute(sql)
            frozen = json.dumps({"schema": SCHEMA, **config}, sort_keys=True)
            control = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
            if control is not None:
                if control[0] != frozen:
                    raise ValueError("Execution rehearsal configuration is immutable")
            else:
                ledger = Ledger(cash=config["capital"], high_watermark=config["capital"])
                db.execute(
                    "INSERT INTO execution_control VALUES(1,?,?,0,NULL,NULL,'[]')",
                    (frozen, ledger.model_dump_json()),
                )
        self.path.chmod(0o600)

    @contextmanager
    def write(self):
        if not self.writable:
            raise ValueError("Journal was opened read-only")
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def read(self):
        db = sqlite3.connect("file:" + quote(str(self.path)) + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            yield db
        finally:
            db.close()

    @staticmethod
    def event(db, at, kind, payload, client_id=None):
        db.execute(
            "INSERT INTO execution_events(occurred_at,kind,client_id,payload) VALUES(?,?,?,?)",
            (at.isoformat(), kind, client_id, json.dumps(payload, sort_keys=True)),
        )

    def report(self):
        with self.read() as db:
            c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
            orders = db.execute("SELECT * FROM execution_orders ORDER BY rowid").fetchall()
            binding = None
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='execution_fixture_binding'"
            ).fetchone():
                binding = db.execute(
                    "SELECT venue_id,account_id FROM execution_fixture_binding WHERE id=1"
                ).fetchone()
            return {
                "mode": "EXECUTION_REHEARSAL",
                "network_calls": False,
                "live_enabled": False,
                "config": json.loads(c["config_json"]),
                "fixture_binding": dict(binding) if binding else None,
                "halted": bool(c["halted"]),
                "halt_reason": c["halt_reason"],
                "issues": json.loads(c["issues_json"]),
                "ledger": json.loads(c["ledger_json"]),
                "orders": [
                    {
                        "intent": json.loads(o["intent_json"]),
                        "status": o["status"],
                        "order_id": o["order_id"],
                        "attempted_at": o["attempted_at"],
                        "active": o["active_lock"] is not None,
                        "observation": json.loads(o["observation_json"])
                        if o["observation_json"]
                        else None,
                    }
                    for o in orders
                ],
                "fills": [
                    json.loads(r[0])
                    for r in db.execute("SELECT payload FROM execution_fills ORDER BY rowid")
                ],
                "events": [
                    {
                        "sequence": r["sequence"],
                        "occurred_at": r["occurred_at"],
                        "kind": r["kind"],
                        "client_id": r["client_id"],
                        "payload": json.loads(r["payload"]),
                    }
                    for r in db.execute(
                        "SELECT * FROM execution_events ORDER BY sequence DESC LIMIT 100"
                    )
                ],
            }
