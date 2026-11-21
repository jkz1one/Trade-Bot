"""Reviewed abandonment of interrupted fixture cycles; never replay or risk release."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from app.domain.models import MarketPacket, TradeDecision
from app.execution import economics
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits, JudgmentResult
from app.execution.models import TERMINAL, Ledger, Observation, Snapshot


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def resolve_cycle(engine, db, command, now):
    """Caller authenticates/reviews, owns runtime lease and a fenced transaction."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_restore_binding'"
    ).fetchone() or not any(row[1] == "authority" for row in db.execute("PRAGMA database_list")):
        raise ExecutionBlocked("CYCLE_VERIFIED_AUTHORITY_REQUIRED")
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_runtime'").fetchone():
        raise ExecutionBlocked("PAPER_RUNTIME_NOT_ENROLLED")
    runtime = db.execute("SELECT * FROM execution_runtime WHERE id=1").fetchone()
    if runtime is None:
        raise ExecutionBlocked("PAPER_RUNTIME_NOT_ENROLLED")
    if runtime["status"] not in {"STOPPED", "FAILED"}:
        raise ExecutionBlocked("PAPER_RUNTIME_NOT_STOPPED")
    control = engine._control(db)
    policy = json.loads(runtime["policy_json"])
    if policy["engine"] != json.loads(control["config_json"]):
        raise ExecutionBlocked("RUNTIME_CONFIGURATION_CHANGED")
    cycle = db.execute(
        "SELECT * FROM execution_runtime_cycles WHERE slot=?", (command.cycle_slot,)
    ).fetchone()
    if cycle is None:
        raise ExecutionBlocked("PAPER_CYCLE_NOT_FOUND")
    if cycle["status"] != "INTERRUPTED":
        raise ExecutionBlocked("PAPER_CYCLE_NOT_INTERRUPTED")
    if not control["halted"]:
        raise ExecutionBlocked("CYCLE_RESOLUTION_REQUIRES_HALT")
    if (
        cycle["completed_at"] is None
        or now < datetime.fromisoformat(cycle["completed_at"])
        or now < datetime.fromisoformat(cycle["started_at"])
    ):
        raise ExecutionBlocked("CYCLE_RESOLUTION_TIME_REGRESSION")
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_runtime_resolutions'"
    ).fetchone()
    if (
        exists
        and db.execute(
            "SELECT 1 FROM execution_runtime_resolutions WHERE slot=?", (command.cycle_slot,)
        ).fetchone()
    ):
        raise ExecutionBlocked("PAPER_CYCLE_ALREADY_RESOLVED")
    if db.execute("SELECT 1 FROM execution_runtime_cycles WHERE status='CLAIMED'").fetchone():
        raise ExecutionBlocked("PAPER_CLAIM_REQUIRES_STARTUP_REVIEW")
    if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
        raise ExecutionBlocked("ORDER_ALREADY_IN_FLIGHT")
    if not control["snapshot_json"] or json.loads(control["issues_json"]):
        raise ExecutionBlocked("RECONCILIATION_REQUIRED")
    snapshot = Snapshot.model_validate_json(control["snapshot_json"])
    if snapshot.account_id != engine.limits.account_id:
        raise ExecutionBlocked("EXECUTION_ACCOUNT_MISMATCH")
    if not engine._fresh(snapshot, now, engine.settings.quote_max_age_seconds):
        raise ExecutionBlocked("STALE_EXECUTION_SNAPSHOT")
    state = Ledger.model_validate_json(control["ledger_json"])
    if state.position and (
        state.management is None
        or state.management.supervision_issue
        or any(
            t is None or not 0 <= (now - t).total_seconds() <= engine.settings.quote_max_age_seconds
            for t in (state.management.last_supervised_at, state.management.last_quote_at)
        )
    ):
        raise ExecutionBlocked("FRESH_POSITION_SUPERVISION_REQUIRED")
    costs = economics.summary(db)
    if costs["unknown_calls"]:
        raise ExecutionBlocked("EXECUTION_MODEL_COST_UNKNOWN")
    if costs.get("judgment_blocked") or costs.get("calls_exceeding_bound"):
        raise ExecutionBlocked("EXECUTION_MODEL_EVIDENCE_VIOLATION")
    call = db.execute(
        "SELECT * FROM execution_model_calls WHERE source_key=?", (command.cycle_slot,)
    ).fetchone()
    model_evidence = None
    if policy["agent"] == "openai":
        judgment = db.execute(
            "SELECT policy_json FROM execution_judgment_policy WHERE id=1"
        ).fetchone()
        if (
            not judgment
            or json.loads(judgment[0]) != policy["judgment"]
            or costs["status"] == "UNCONFIGURED"
            or _hash(costs["policy"]) != policy["judgment"]["cost_policy_hash"]
        ):
            raise ExecutionBlocked("JUDGMENT_CONFIGURATION_CHANGED")
        if call:
            recorded = db.execute(
                "SELECT payload FROM execution_events WHERE kind='MODEL_JUDGMENT_RECORDED' AND json_extract(payload,'$.source_key')=? ORDER BY sequence DESC LIMIT 1",
                (command.cycle_slot,),
            ).fetchone()
            if (
                not recorded
                or not call["usage_json"]
                or call["cost"] is None
                or not call["decision_hash"]
            ):
                raise ExecutionBlocked("EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED")
            result = JudgmentResult.model_validate(json.loads(recorded[0])["result"]).model_dump(
                mode="json"
            )
            limits = JudgmentLimits.model_validate(policy["judgment"]["limits"])
            usage = economics.UsageEvidence.model_validate_json(call["usage_json"])
            decision = TradeDecision.model_validate(result["decision"])
            amount = (
                Decimal(usage.input_tokens) * Decimal(costs["policy"]["input_per_million"])
                + Decimal(usage.output_tokens) * Decimal(costs["policy"]["output_per_million"])
            ) / 1_000_000
            if (
                result["usage"] != json.loads(call["usage_json"])
                or usage.request_id != call["request_id"]
                or usage.model != costs["policy"]["model"]
                or economics._hash(decision) != call["decision_hash"]
                or amount != Decimal(call["cost"])
                or result["counted_input_tokens"] != usage.input_tokens
                or usage.input_tokens > limits.max_input_tokens
                or usage.output_tokens > limits.max_output_tokens
                or (
                    cycle["decision_json"] is not None
                    and economics._hash(TradeDecision.model_validate_json(cycle["decision_json"]))
                    != call["decision_hash"]
                )
                or call["packet_hash"]
                != economics._hash(MarketPacket.model_validate_json(cycle["packet_json"]))
            ):
                raise ExecutionBlocked("EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED")
            model_evidence = {
                "source_key": call["source_key"],
                "request_id": call["request_id"],
                "cost": call["cost"],
                "decision_hash": call["decision_hash"],
            }
    elif (
        policy["agent"] != "stub-hold"
        or call is not None
        or (
            cycle["decision_json"] is not None
            and TradeDecision.model_validate_json(cycle["decision_json"]).action.value != "HOLD"
        )
    ):
        raise ExecutionBlocked("CYCLE_AGENT_EVIDENCE_MISMATCH")
    if policy["agent"] == "openai" and call is None and cycle["decision_json"] is not None:
        raise ExecutionBlocked("EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED")
    order = db.execute(
        "SELECT * FROM execution_orders WHERE source_key=?", (command.cycle_slot,)
    ).fetchone()
    if order:
        if policy["agent"] != "openai" or call is None:
            raise ExecutionBlocked("EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED")
        if order["status"] not in TERMINAL or order["active_lock"] is not None:
            raise ExecutionBlocked("CYCLE_ORDER_NOT_TERMINAL")
        if order["attempted_at"]:
            observed = (
                Observation.model_validate_json(order["observation_json"])
                if order["observation_json"]
                else None
            )
            current = next(
                (item for item in snapshot.orders if item.client_id == order["client_id"]), None
            )
            if (
                observed is None
                or current is None
                or observed != current
                or current.status != order["status"]
                or current.order_id != order["order_id"]
            ):
                raise ExecutionBlocked("CYCLE_TERMINAL_EVIDENCE_REQUIRED")
    # Preserve original cycle, model receipt, order, reservations, alert ACK and halt.
    # The explicit resolution only removes this interruption's scheduling blocker.
    evidence = {
        "snapshot_id": snapshot.snapshot_id,
        "account_id": snapshot.account_id,
        "ledger_hash": _hash(state.model_dump(mode="json")),
        "model": model_evidence,
        "client_id": order["client_id"] if order else None,
        "order_status": order["status"] if order else None,
    }
    fingerprint = _hash(dict(cycle))
    db.execute(
        "CREATE TABLE IF NOT EXISTS execution_runtime_resolutions(slot TEXT PRIMARY KEY REFERENCES execution_runtime_cycles(slot),resolved_at TEXT NOT NULL,command_id TEXT NOT NULL UNIQUE,cycle_hash TEXT NOT NULL,evidence_json TEXT NOT NULL)"
    )
    db.execute(
        "INSERT INTO execution_runtime_resolutions VALUES(?,?,?,?,?)",
        (
            command.cycle_slot,
            now.isoformat(),
            command.command_id,
            fingerprint,
            json.dumps(evidence, sort_keys=True),
        ),
    )
    engine.journal.event(
        db,
        now,
        "PAPER_CYCLE_RESOLVED",
        {
            "slot": command.cycle_slot,
            "command_id": command.command_id,
            "cycle_hash": fingerprint,
            "evidence": evidence,
            "replay_allowed": False,
            "halt_retained": True,
        },
    )
