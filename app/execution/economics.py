"""Opt-in offline model receipts and Decimal economics; never an API caller.

Usage/decision evidence is supplied by trusted local orchestration. This is not
proof of provider billing, nor integration with the deployed SHADOW population.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from app.domain.models import TradeDecision
from app.execution.models import ZERO, Contract, Ledger, Snapshot


class CostPolicy(Contract):
    model: str = Field(default="gpt-6-luna", min_length=1, max_length=128)
    input_per_million: Decimal = Field(default=Decimal(".10"), ge=0)
    output_per_million: Decimal = Field(default=Decimal(".50"), ge=0)
    total_budget: Decimal = Field(gt=0)
    daily_budget: Decimal = Field(gt=0)
    max_call_cost: Decimal = Field(default=Decimal(".01"), gt=0)

    @model_validator(mode="after")
    def bounded(self):
        if self.max_call_cost > min(self.total_budget, self.daily_budget):
            raise ValueError("Per-call cost reservation must fit both budgets")
        return self

    @field_validator("model")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A model identity is required")
        return value


class UsageEvidence(Contract):
    request_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    input_tokens: int = Field(gt=0, le=1_000_000_000, strict=True)
    output_tokens: int = Field(ge=0, le=1_000_000_000, strict=True)

    @field_validator("request_id", "model")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Usage identities cannot be blank")
        return value


def _hash(model):
    return hashlib.sha256(
        json.dumps(model.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()


def summary(db, now=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_cost_policy'").fetchone():
        return {"status": "UNCONFIGURED", "known_cost": "0", "unknown_calls": 0, "daily_cost": {}}
    row = db.execute("SELECT policy_json FROM execution_cost_policy WHERE id=1").fetchone()
    if not row:
        return {"status": "UNCONFIGURED", "known_cost": "0", "unknown_calls": 0, "daily_cost": {}}
    policy = CostPolicy.model_validate_json(row[0])
    total, unknown, daily, exceeded = ZERO, 0, {}, 0
    for call in db.execute("SELECT * FROM execution_model_calls"):
        if call["cost"] is None:
            unknown += 1
        else:
            amount = Decimal(call["cost"])
            exceeded += amount > policy.max_call_cost
            total += amount
            day = (
                datetime.fromisoformat(call["started_at"])
                .astimezone(ZoneInfo("America/New_York"))
                .date()
                .isoformat()
            )
            daily[day] = daily.get(day, ZERO) + amount
    blocked, judgment_policy = None, None
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_judgment_policy'").fetchone():
        judgment = db.execute(
            "SELECT policy_json,blocked_reason FROM execution_judgment_policy WHERE id=1"
        ).fetchone()
        judgment_policy = json.loads(judgment[0]) if judgment else None
        blocked = judgment[1] if judgment else None
    return {
        "status": "INCOMPLETE" if unknown else "COMPLETE",
        "policy": policy.model_dump(mode="json"),
        "known_cost": str(total),
        "unknown_calls": unknown,
        "calls_exceeding_bound": exceeded,
        "daily_cost": {k: str(v) for k, v in daily.items()},
        "judgment_blocked": blocked,
        "judgment_policy": judgment_policy,
    }


def entry_reasons(db, source_key, decision, packet, now):
    costs = summary(db)
    if costs["status"] == "UNCONFIGURED":
        return [], costs
    reasons = []
    policy = CostPolicy.model_validate(costs["policy"])
    if costs["unknown_calls"]:
        reasons.append("EXECUTION_MODEL_COST_UNKNOWN")
    if costs.get("judgment_blocked"):
        reasons.append("EXECUTION_MODEL_EVIDENCE_VIOLATION")
    if costs["calls_exceeding_bound"]:
        reasons.append("EXECUTION_MODEL_COST_BOUND_EXCEEDED")
    day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if Decimal(costs["known_cost"]) >= policy.total_budget:
        reasons.append("EXECUTION_MODEL_TOTAL_BUDGET")
    if Decimal(costs["daily_cost"].get(day, "0")) >= policy.daily_budget:
        reasons.append("EXECUTION_MODEL_DAILY_BUDGET")
    call = db.execute(
        "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
    ).fetchone()
    if not call or not call["usage_json"] or call["decision_hash"] != _hash(decision):
        reasons.append("EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED")
    if costs.get("judgment_policy"):
        record = db.execute(
            "SELECT payload FROM execution_events WHERE kind='MODEL_JUDGMENT_RECORDED' AND json_extract(payload,'$.source_key')=? ORDER BY sequence DESC LIMIT 1",
            (source_key,),
        ).fetchone()
        evidence = json.loads(record[0])["result"] if record else None
        if (
            not evidence
            or evidence["error"] is not None
            or not call
            or evidence["usage"] != json.loads(call["usage_json"] or "null")
            or _hash(TradeDecision.model_validate(evidence["decision"])) != _hash(decision)
        ):
            reasons.append("EXECUTION_BOUNDED_JUDGMENT_EVIDENCE_REQUIRED")
    # Dispatch can use refreshed market data; original packet lineage is checked
    # during admission, while immutable decision/cost evidence remains required.
    return reasons, costs


class CostAccounting:
    def __init__(self, engine, policy: CostPolicy):
        from app.execution.engine import ExecutionEngine

        if type(engine) is not ExecutionEngine:
            raise ValueError("Only the offline execution engine is supported")
        self.engine = engine
        self.policy = CostPolicy.model_validate(policy.model_dump())
        with engine.journal.write() as db:
            engine._control(db)
            row = db.execute("SELECT policy_json FROM execution_cost_policy WHERE id=1").fetchone()
            frozen = self.policy.model_dump_json()
            if row:
                if row[0] != frozen:
                    raise ValueError("Model cost policy is immutable")
            else:
                if db.execute("SELECT 1 FROM execution_orders").fetchone():
                    raise ValueError("Cost accounting requires enrollment before order preparation")
                db.execute("INSERT INTO execution_cost_policy VALUES(1,?)", (frozen,))
                engine.journal.event(
                    db,
                    datetime.now().astimezone(),
                    "MODEL_COST_POLICY_ENROLLED",
                    self.policy.model_dump(mode="json"),
                )

    def _policy(self, db):
        from app.execution.engine import ExecutionBlocked

        row = db.execute("SELECT policy_json FROM execution_cost_policy WHERE id=1").fetchone()
        if row is None or row[0] != self.policy.model_dump_json():
            raise ExecutionBlocked("EXECUTION_COST_CONFIGURATION_CHANGED")

    def begin(self, source_key, packet, *, now, expected_revision=None):
        """Commit before a future external model invocation. Never automatically retry."""
        from app.execution.engine import ExecutionBlocked, _clock

        _clock(now)
        if not source_key.strip() or len(source_key) > 128:
            raise ValueError("A bounded stable model source key is required")
        engine = self.engine
        packet = engine._validated_packet(packet)
        fingerprint = _hash(packet)
        with engine.journal.write() as db:
            control = engine._control(db)
            self._policy(db)
            old = db.execute(
                "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
            ).fetchone()
            if old:
                if old["packet_hash"] != fingerprint:
                    raise ValueError("MODEL_SOURCE_CONTENT_CONFLICT")
                return {"status": "EXISTING", "source_key": source_key, "invoke_model": False}
            if expected_revision is not None and engine.journal.revision(db) != expected_revision:
                raise ExecutionBlocked("MODEL_ACCOUNT_REVIEW_CHANGED")
            engine._ready(control, now)
            if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
                raise ExecutionBlocked("ORDER_ALREADY_IN_FLIGHT")
            if engine.calendar.current_window(now) is None:
                raise ExecutionBlocked("MARKET_CLOSED")
            engine._market_values(packet)
            stamps = [packet.as_of, *(c.quote.timestamp for c in packet.candidates)]
            if any(
                t.tzinfo is None
                or not 0 <= (now - t).total_seconds() <= engine.settings.quote_max_age_seconds
                for t in stamps
            ):
                raise ExecutionBlocked("INVALID_MODEL_PACKET_TIME")
            costs = summary(db)
            if costs.get("judgment_policy") and expected_revision is None:
                raise ExecutionBlocked("JUDGMENT_ACCOUNT_REVIEW_REQUIRED")
            day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if costs["unknown_calls"]:
                raise ExecutionBlocked("EXECUTION_MODEL_COST_UNKNOWN")
            if costs.get("judgment_blocked"):
                raise ExecutionBlocked("EXECUTION_MODEL_EVIDENCE_VIOLATION")
            if costs["calls_exceeding_bound"]:
                raise ExecutionBlocked("EXECUTION_MODEL_COST_BOUND_EXCEEDED")
            if (
                Decimal(costs["known_cost"]) + self.policy.max_call_cost > self.policy.total_budget
                or Decimal(costs["daily_cost"].get(day, "0")) + self.policy.max_call_cost
                > self.policy.daily_budget
            ):
                raise ExecutionBlocked("EXECUTION_MODEL_COST_BUDGET")
            db.execute(
                "INSERT INTO execution_model_calls(source_key,packet_hash,started_at) VALUES(?,?,?)",
                (source_key, fingerprint, now.isoformat()),
            )
            engine.journal.event(
                db,
                now,
                "MODEL_ATTEMPT_STARTED",
                {"source_key": source_key, "packet_hash": fingerprint},
            )
            return {"status": "STARTED", "source_key": source_key, "invoke_model": True}

    def settle(self, source_key, usage: UsageEvidence, decision: TradeDecision, *, now):
        with self.engine.journal.write() as db:
            return self._settle(db, source_key, usage, decision, now=now)

    def _settle(self, db, source_key, usage, decision, *, now):
        from app.execution.engine import _clock

        _clock(now)
        usage = UsageEvidence.model_validate(usage.model_dump())
        decision = TradeDecision.model_validate(decision.model_dump())
        if usage.model != self.policy.model:
            raise ValueError("MODEL_USAGE_IDENTITY_MISMATCH")
        amount = (
            Decimal(usage.input_tokens) * self.policy.input_per_million
            + Decimal(usage.output_tokens) * self.policy.output_per_million
        ) / Decimal(1_000_000)
        self.engine._control(db)
        self._policy(db)
        row = db.execute(
            "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
        ).fetchone()
        if not row or now < datetime.fromisoformat(row["started_at"]):
            raise ValueError("MODEL_RECEIPT_REQUIRED")
        if row["usage_json"]:
            if row["usage_json"] != usage.model_dump_json() or row["decision_hash"] != _hash(
                decision
            ):
                raise ValueError("MODEL_USAGE_CONTENT_CONFLICT")
            return amount
        db.execute(
            "UPDATE execution_model_calls SET usage_json=?,request_id=?,decision_hash=?,cost=? WHERE source_key=?",
            (
                usage.model_dump_json(),
                usage.request_id,
                _hash(decision),
                str(amount),
                source_key,
            ),
        )
        self.engine.journal.event(
            db,
            now,
            "MODEL_USAGE_SETTLED",
            {
                "source_key": source_key,
                "usage": usage.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "estimated_cost": str(amount),
            },
        )
        if amount > self.policy.max_call_cost:
            self.engine.journal.event(
                db,
                now,
                "MODEL_COST_BOUND_EXCEEDED",
                {"source_key": source_key, "actual_estimated_cost": str(amount)},
            )
        return amount


def economics_report(db, control, now):
    costs = summary(db)
    state = Ledger.model_validate_json(control["ledger_json"])
    equity = state.cash + (state.position.market_value if state.position else ZERO)
    complete = costs["status"] == "COMPLETE"
    maximum_age = int(json.loads(control["config_json"])["risk_settings"]["quote_max_age_seconds"])
    if (
        json.loads(control["issues_json"])
        or not control["snapshot_json"]
        or (
            not 0
            <= (
                now - Snapshot.model_validate_json(control["snapshot_json"]).captured_at
            ).total_seconds()
            <= maximum_age
        )
    ):
        complete = False
    if state.position:
        management = state.management
        complete = (
            complete
            and management is not None
            and management.supervision_issue is None
            and all(
                t is not None
                and 0
                <= (now - t).total_seconds()
                <= int(json.loads(control["config_json"])["risk_settings"]["quote_max_age_seconds"])
                for t in (management.last_supervised_at, management.last_quote_at)
            )
        )
    capital = Decimal(json.loads(control["config_json"])["capital"])
    net = equity - Decimal(costs["known_cost"]) if complete else None
    return {
        **costs,
        "trading_equity": str(equity),
        "net_equity": str(net) if net is not None else None,
        "net_return": str(net / capital - 1) if net is not None else None,
        "note": "Configured standard-rate estimate; costs do not debit brokerage cash. Unknown usage/stale position marks suppress net economics. No SPY pairing, corporate actions, taxes, hosting or setup costs in this isolated engine.",
    }
