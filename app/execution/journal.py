"""Separate SQLite write-ahead journal; money is stored as decimal JSON strings."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from app.execution import alert_state, economics, restore, runtime_state, supervisor_state
from app.execution.models import Ledger

SCHEMA = "execution-rehearsal-v1"
ALERT_KINDS = {
    "INTERRUPTED_ATTEMPT",
    "ATTEMPT_UNCERTAIN",
    "RECONCILIATION_BLOCKED",
    "INVALID_EVIDENCE",
    "MANUAL_HALT",
    "FIXTURE_READ_FAILED",
    "FIXTURE_BINDING_BLOCKED",
    "MODEL_COST_BOUND_EXCEEDED",
    "RUNTIME_CYCLE_COMPLETED",
}


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
        if not self.path.exists() and restore.authority_path(self.path).exists():
            raise ValueError("RESTORED_EXECUTION_JOURNAL_MISSING")
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
                "execution_operator",
                "execution_commands",
                "execution_alerts",
                "execution_restore_binding",
                "execution_retired_keys",
                "execution_cost_policy",
                "execution_model_calls",
                "execution_judgment_policy",
                "execution_supervisor",
                "execution_alert_delivery",
                "execution_alert_attempts",
                "execution_runtime",
                "execution_runtime_cycles",
                "execution_runtime_resolutions",
                "sqlite_sequence",
            }
            if tables - allowed:
                raise ValueError("Execution rehearsal requires a separate database")
            # Individual statements preserve the surrounding BEGIN IMMEDIATE.
            for sql in (
                "CREATE TABLE IF NOT EXISTS execution_supervisor (id INTEGER PRIMARY KEY CHECK(id=1), policy_json TEXT NOT NULL,status TEXT NOT NULL,owner TEXT,generation INTEGER NOT NULL,heartbeat_at TEXT,result_json TEXT,feed_sequence INTEGER,feed_hash TEXT)",
                "CREATE TABLE IF NOT EXISTS execution_judgment_policy (id INTEGER PRIMARY KEY CHECK(id=1), policy_json TEXT NOT NULL, blocked_reason TEXT)",
                "CREATE TABLE IF NOT EXISTS execution_cost_policy (id INTEGER PRIMARY KEY CHECK(id=1), policy_json TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS execution_model_calls (source_key TEXT PRIMARY KEY, packet_hash TEXT NOT NULL, started_at TEXT NOT NULL, usage_json TEXT, request_id TEXT UNIQUE, decision_hash TEXT, cost TEXT)",
                "CREATE TABLE IF NOT EXISTS execution_retired_keys (key_hash TEXT PRIMARY KEY, retired_at TEXT NOT NULL, generation INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS execution_operator (id INTEGER PRIMARY KEY CHECK(id=1), journal_id TEXT NOT NULL UNIQUE, key_hash TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS execution_commands (command_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS execution_alerts (event_sequence INTEGER PRIMARY KEY REFERENCES execution_events(sequence), acknowledged_at TEXT, actor TEXT, command_id TEXT)",
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
            columns = {r[1] for r in db.execute("PRAGMA table_info(execution_operator)")}
            if "generation" not in columns:
                db.execute(
                    "ALTER TABLE execution_operator ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"
                )
            if "revoked" not in columns:
                db.execute(
                    "ALTER TABLE execution_operator ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0"
                )
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
        db = sqlite3.connect(
            "file:" + quote(str(self.path)) + "?mode=rw", uri=True, timeout=10, isolation_level=None
        )
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            fenced = restore.begin_fenced_write(db, restore.authority_path(self.path))
            yield db
            if fenced:
                restore.advance(db)
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
        cursor = db.execute(
            "INSERT INTO execution_events(occurred_at,kind,client_id,payload) VALUES(?,?,?,?)",
            (at.isoformat(), kind, client_id, json.dumps(payload, sort_keys=True)),
        )
        alert = kind in ALERT_KINDS
        if kind == "RUNTIME_CYCLE_COMPLETED":
            alert = payload["status"] == "INTERRUPTED"
        if kind in {"MODEL_JUDGMENT_INTERRUPTED", "MODEL_JUDGMENT_RECORDED"}:
            alert = kind == "MODEL_JUDGMENT_INTERRUPTED" or payload["result"]["error"] is not None
        if kind == "SUPERVISOR_TICK" and payload["result"]["status"] in {"FAILED", "BLOCKED"}:
            previous = db.execute(
                "SELECT payload FROM execution_events WHERE kind=? AND sequence<? ORDER BY sequence DESC LIMIT 1",
                (kind, cursor.lastrowid),
            ).fetchone()
            alert = previous is None or json.loads(previous[0])["result"] != payload["result"]
        if kind == "POSITION_SUPERVISED" and payload["status"] in {"BLOCKED", "EXIT_REQUIRED"}:
            previous = db.execute(
                "SELECT payload FROM execution_events WHERE kind=? AND sequence<? ORDER BY sequence DESC LIMIT 1",
                (kind, cursor.lastrowid),
            ).fetchone()
            keys = ("status", "exit_reason", "issue", "entry_client_id")
            alert = not previous or any(
                json.loads(previous[0]).get(k) != payload.get(k) for k in keys
            )
        if alert:
            db.execute(
                "INSERT INTO execution_alerts(event_sequence) VALUES(?)", (cursor.lastrowid,)
            )

    @staticmethod
    def revision(db):
        return db.execute("SELECT COALESCE(MAX(sequence),0) FROM execution_events").fetchone()[0]

    def alerts(self, *, after=0, limit=100):
        """Ordered local outbox page; acknowledgment is not delivery or risk resolution."""
        if after < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid alert page")
        with self.read() as db:
            return self._alerts(db, after, limit)

    def enable_restore_fence(self, *, now):
        return restore.enable(self, now=now)

    @staticmethod
    def _alerts(db, after, limit):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_alerts'").fetchone():
            return []
        return [
            dict(r)
            for r in db.execute(
                "SELECT a.*,e.occurred_at,e.kind,e.client_id AS order_client_id,e.payload "
                "FROM execution_alerts a JOIN execution_events e ON e.sequence=a.event_sequence "
                "WHERE a.event_sequence>? ORDER BY a.event_sequence LIMIT ?",
                (after, limit),
            )
        ]

    def report(self, *, now=None):
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
                "revision": self.revision(db),
                "economics": economics.economics_report(db, c, now or datetime.now().astimezone()),
                "supervisor": supervisor_state.report(db, now or datetime.now().astimezone()),
                "runtime": runtime_state.report(db, now or datetime.now().astimezone()),
                "alert_delivery": alert_state.report(db, now or datetime.now().astimezone()),
                "restore_fence": restore.status(db, restore.authority_path(self.path)),
                "alerts": self._alerts(db, 0, 100),
                "unacknowledged_alerts": db.execute(
                    "SELECT COUNT(*) FROM execution_alerts WHERE acknowledged_at IS NULL"
                ).fetchone()[0]
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='execution_alerts'"
                ).fetchone()
                else 0,
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
