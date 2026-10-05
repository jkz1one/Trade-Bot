"""Stored SHADOW projections. No broker, agent, credentials or database bootstrap."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.domain.models import MarketPacket, RiskDecision, TradeDecision
from app.metrics.shadow import shadow_history_report
from app.metrics.shadow_outcomes import forward_outcomes_report
from app.storage.models import DecisionCycleRow, ShadowForwardOutcomeRow
from app.storage.repository import Repository


def read_only_engine(db_url):
    url = make_url(db_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("The observer requires a file-backed SHADOW SQLite database")
    path = Path(url.database).expanduser().resolve()

    def connect():
        connection = sqlite3.connect(
            "file:" + quote(str(path)) + "?mode=ro", uri=True, timeout=2, check_same_thread=False
        )
        connection.execute("PRAGMA query_only=ON")
        return connection

    return path, create_engine("sqlite://", creator=connect, poolclass=NullPool)


def age_seconds(stamp, now):
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (now - stamp).total_seconds()


class PageRepository(Repository):
    def __init__(self, factory, before):
        super().__init__(factory)
        self.before = before

    def recent_cycles(self, limit=100):
        with self.session_factory() as session:
            query = select(DecisionCycleRow).order_by(DecisionCycleRow.id.desc()).limit(limit)
            if self.before is not None:
                query = query.where(DecisionCycleRow.id < self.before)
            return list(session.scalars(query))

    def shadow_forward_outcomes(self, limit=100):
        ids = [row.id for row in self.recent_cycles(limit)]
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(ShadowForwardOutcomeRow)
                    .where(
                        ShadowForwardOutcomeRow.source_cycle_id.in_(ids),
                    )
                    .order_by(
                        ShadowForwardOutcomeRow.source_cycle_id.desc(),
                        ShadowForwardOutcomeRow.horizon_minutes,
                    )
                )
            )


def stored_snapshot(path, engine, *, benchmark_symbol, now, limit=25, before=None):
    if not path.is_file():
        return {"status": "EMPTY", "reason": "DATABASE_NOT_CREATED", "network_calls": False}
    with engine.connect() as connection:
        # All report queries see one committed snapshot, even if the worker commits mid-read.
        connection.exec_driver_sql("BEGIN")
        required = {
            "decision_cycles",
            "model_usage",
            "shadow_cycle_evidence",
            "shadow_schedule_slots",
            "shadow_service_state",
            "shadow_forward_outcomes",
        }
        tables = set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).scalars()
        )
        if not required.issubset(tables):
            return {"status": "UNAVAILABLE", "reason": "SCHEMA_NOT_READY", "network_calls": False}
        factory = sessionmaker(bind=connection, expire_on_commit=False)
        repo = Repository(factory)
        page = PageRepository(factory, before)
        service = repo.shadow_service_state()
        heartbeat_age = age_seconds(service["heartbeat_at"], now) if service else None
        healthy = bool(service and service["status"] == "RUNNING" and 0 <= heartbeat_age <= 90)
        if service and service["last_result"]:
            service["last_result"] = {
                key: value
                for key, value in service["last_result"].items()
                if key
                in {
                    "status",
                    "reason",
                    "exit_code",
                    "slot_key",
                    "cycle_id",
                    "error_class",
                    "prior_exit_code",
                }
            }
        latest_rows = repo.recent_cycles(1)
        latest = None
        if latest_rows:
            row = latest_rows[0]
            packet = MarketPacket.model_validate_json(row.packet_json).model_dump(mode="json")
            execution = json.loads(row.execution_json)
            account = packet["account"]
            position = account.get("position")
            evidence = repo.shadow_cycle_evidence(row.id)
            if evidence["reconciliation"] is not None:
                evidence["reconciliation"] = {
                    key: evidence["reconciliation"].get(key) for key in ("reconciled", "reasons")
                }
            latest = {
                "cycle_id": row.id,
                "as_of": packet["as_of"],
                "age_seconds": age_seconds(packet["as_of"], now),
                "model": row.model_identifier,
                "prompt_version": row.prompt_version,
                "latency_ms": row.latency_ms,
                "regime": packet.get("regime"),
                "session_context": packet.get("session_context"),
                "decision": TradeDecision.model_validate_json(row.decision_json).model_dump(
                    mode="json"
                ),
                "risk": RiskDecision.model_validate_json(row.risk_json).model_dump(mode="json"),
                # Broker review may include account identifiers. Only publish its completion state.
                "execution": {
                    "status": execution["status"],
                    "review_completed": execution.get("broker_review") is not None,
                    "agent_error": execution.get("agent_error"),
                    "review_error": execution.get("review_error"),
                    "session_blocked": execution.get("session_blocked", False),
                },
                "evidence": evidence,
                "account": {key: account.get(key) for key in ("equity", "cash", "buying_power")},
                "position": (
                    {
                        key: position.get(key)
                        for key in ("symbol", "quantity", "entry_price", "current_price")
                    }
                    if position
                    else None
                ),
            }
        history = shadow_history_report(page, benchmark_symbol, limit + 1)
        has_older = history["cycle_count"] > limit
        if has_older:
            history = shadow_history_report(page, benchmark_symbol, limit)
        cycles = history["cycles"]
        outcomes = forward_outcomes_report(page, limit)
        # Detailed quote payloads are for offline audits; the observer needs only marks and reasons.
        outcomes["outcomes"] = [
            {
                "source_cycle_id": item["source_cycle_id"],
                "horizon_minutes": item["horizon_minutes"],
                "status": item["status"],
                "reason": item["reason"],
                "due_at": item["due_at"],
                "measurement_cycle_id": item["measurement_cycle_id"],
                "kind": item["baseline"].get("kind"),
                "symbol": item["baseline"].get("symbol"),
                "result": (
                    {
                        key: value
                        for key, value in item["result"].items()
                        if key
                        in {"after_model_cost_return_fraction", "after_model_cost_excess_fraction"}
                    }
                    if item["result"]
                    else None
                ),
            }
            for item in outcomes["outcomes"]
        ]
        slots = [
            {
                "slot_key": item.slot_key,
                "status": item.status,
                "scheduled_for": item.scheduled_for.isoformat(),
                "cycle_id": item.cycle_id,
                "exit_code": item.exit_code,
                "error_class": item.error_class,
            }
            for item in repo.shadow_schedule_slots(10)
        ]
        active = repo.active_shadow_slot()
        return {
            "status": "OK" if latest else "EMPTY",
            "mode": "SHADOW",
            "network_calls": False,
            "observed_at": now.isoformat(),
            "service": service,
            "worker_healthy": healthy,
            "heartbeat_age_seconds": heartbeat_age,
            "active_slot": active.slot_key if active else None,
            "latest": latest,
            "history": history,
            "outcomes": outcomes,
            "slots": slots,
            "page": {
                "limit": limit,
                "before": before,
                "has_older": has_older,
                "next_before": min(c["cycle_id"] for c in cycles) if has_older else None,
            },
            "strategy_pnl": None,
            "economic_pnl": None,
        }
