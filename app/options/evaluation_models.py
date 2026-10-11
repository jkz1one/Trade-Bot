"""Bounded source evidence for descriptive A/B/C replay, with no execution authority."""

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from app.execution.economics import UsageEvidence
from app.options.entry_reasoning import Digest
from app.options.lifecycle import (
    OptionExecutionPolicy,
    OptionIntent,
    OptionLedger,
    OptionObservation,
    OptionReceipt,
)
from app.options.models import Money, Name, OptionLimits, OptionRecord, UnderlyingQuote
from app.robinhood.schedule import XNYSCalendar

Arm = Literal["A", "B", "C"]


class ArmDefinition(OptionRecord):
    arm: Arm
    limits: OptionLimits
    policy: OptionExecutionPolicy
    strategy_hash: Digest


class EvaluationSession(OptionRecord):
    key: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    opens_at: datetime
    closes_at: datetime
    tape_hash: Digest


class EvaluationManifest(OptionRecord):
    version: Literal["option-paired-ledger-v1"] = "option-paired-ledger-v1"
    experiment_id: Name
    declared_at: datetime
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    arms: tuple[ArmDefinition, ArmDefinition, ArmDefinition]
    sessions: tuple[EvaluationSession, ...] = Field(min_length=1, max_length=60)
    allocation_policy: Name
    hurdle_per_session: Money = Field(ge=0)
    minimum_sessions: int = Field(ge=2, le=60, strict=True)

    @model_validator(mode="after")
    def matched(self):
        if [a.arm for a in self.arms] != ["A", "B", "C"] or len(
            {a.limits.population_id for a in self.arms}
        ) != 3:
            raise ValueError("Exactly three distinct simulated A/B/C populations required")
        first = self.arms[0]
        for a in self.arms:
            if a.limits.model_dump(
                exclude={"account_id", "population_id"}
            ) != first.limits.model_dump(
                exclude={"account_id", "population_id"}
            ) or a.policy.model_dump(exclude={"cost_policy"}) != first.policy.model_dump(
                exclude={"cost_policy"}
            ):
                raise ValueError("Capital, risk, calendar and fill assumptions must match")
            if (a.arm == "A") != (a.policy.cost_policy is None):
                raise ValueError("A is deterministic; B/C require frozen model costs")
        calendar = XNYSCalendar()
        previous = self.declared_at
        for s in self.sessions:
            w = calendar.current_window(s.opens_at)
            if (
                w is None
                or (s.key, s.opens_at, s.closes_at) != (w.session_date, w.opens_at, w.closes_at)
                or previous >= s.opens_at
            ):
                raise ValueError("Predeclared ordered complete XNYS sessions required")
            previous = s.closes_at
        return self


class ReplayOrder(OptionRecord):
    intent: OptionIntent
    decision_completed_at: datetime
    attempted_at: datetime | None
    observation: OptionObservation | None


class ReplayCall(OptionRecord):
    source_key: Name
    started_at: datetime
    completed_at: datetime | None
    usage: UsageEvidence | None


class ReplayCycle(OptionRecord):
    key: Name
    frame_hash: Digest
    status: Literal["HOLD", "REJECTED", "ERROR", "OPEN", "HELD", "SKIPPED", "UNKNOWN"]
    model_called: StrictBool
    deadline_missed: StrictBool = False


class ArmSession(OptionRecord):
    arm: Arm
    session_key: Name
    definition_hash: Digest
    tape_hash: Digest
    initial: OptionLedger
    closing: OptionLedger
    closing_complete: StrictBool
    orders: tuple[ReplayOrder, ...] = Field(default=(), max_length=200)
    receipts: tuple[OptionReceipt, ...] = Field(default=(), max_length=200)
    calls: tuple[ReplayCall, ...] = Field(default=(), max_length=100)
    cycles: tuple[ReplayCycle, ...] = Field(default=(), max_length=100)
    data_cost: Money | None = Field(default=None, ge=0)
    host_cost: Money | None = Field(default=None, ge=0)


class BenchmarkSession(OptionRecord):
    session_key: Name
    start: UnderlyingQuote
    end: UnderlyingQuote


class EvaluationBundle(OptionRecord):
    manifest: EvaluationManifest
    evidence: tuple[ArmSession, ...] = Field(max_length=180)
    benchmarks: tuple[BenchmarkSession, ...] = Field(default=(), max_length=60)
