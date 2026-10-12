"""Bounded source evidence for descriptive A/B/C replay, with no execution authority."""

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from app.execution.economics import UsageEvidence
from app.options.attribution import DecisionAttribution
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

Arm = Literal["A", "B", "C", "D"]


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


class UnderlyingBaselinePolicy(OptionRecord):
    """Independent long-share comparator following A's approved CALL opportunities."""

    version: Literal["eligible-long-underlying-v1"] = "eligible-long-underlying-v1"
    account_id: Name
    population_id: Name
    tick_size: Money = Field(gt=0)
    max_shares: int = Field(ge=1, le=1_000_000, strict=True)
    entry_fee_per_share: Money = Field(ge=0)
    exit_fee_per_share: Money = Field(ge=0)
    entry_fee_per_order: Money = Field(ge=0)
    exit_fee_per_order: Money = Field(ge=0)
    data_cost_per_session: Money | None = Field(default=None, ge=0)
    host_cost_per_session: Money | None = Field(default=None, ge=0)


class UnderlyingSettlement(OptionRecord):
    receipt_id: Name
    occurred_at: datetime
    amount: Money = Field(gt=0)


class EvaluationManifest(OptionRecord):
    version: Literal["option-paired-ledger-v1"] = "option-paired-ledger-v1"
    experiment_id: Name
    declared_at: datetime
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    arms: tuple[ArmDefinition, ...] = Field(min_length=3, max_length=4)
    sessions: tuple[EvaluationSession, ...] = Field(min_length=1, max_length=60)
    underlying_baseline: UnderlyingBaselinePolicy | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    allocation_policy: Name
    hurdle_per_session: Money = Field(ge=0)
    minimum_sessions: int = Field(ge=2, le=60, strict=True)

    @model_validator(mode="after")
    def matched(self):
        if [a.arm for a in self.arms] not in (["A", "B", "C"], ["A", "B", "C", "D"]) or len(
            {a.limits.population_id for a in self.arms}
        ) != len(self.arms):
            raise ValueError("Distinct ordered simulated A/B/C or A/B/C/D populations required")
        if self.underlying_baseline and any(
            self.underlying_baseline.account_id == a.limits.account_id
            or self.underlying_baseline.population_id == a.limits.population_id
            for a in self.arms
        ):
            raise ValueError("Underlying baseline requires its own account and population")
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
                raise ValueError("A is deterministic; B/C/D require frozen model costs")
        if (
            len(self.arms) == 4
            and self.arms[2].policy.cost_policy != self.arms[3].policy.cost_policy
        ):
            raise ValueError("C/D require matching entry model cost policy")
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
    origin: Literal["UNATTRIBUTED", "DETERMINISTIC", "MODEL", "PROTECTIVE", "POSITION_MODEL"] = (
        "UNATTRIBUTED"
    )
    entry_client_id: Name | None = None
    intent: OptionIntent
    decision_completed_at: datetime
    attempted_at: datetime | None
    observation: OptionObservation | None


class ReplayCall(OptionRecord):
    role: Literal["ENTRY", "MANAGEMENT"] = "ENTRY"
    source_key: Name
    started_at: datetime
    completed_at: datetime | None
    usage: UsageEvidence | None


class ReplayCycle(OptionRecord):
    attribution: DecisionAttribution | None = None
    key: Name
    frame_hash: Digest
    status: Literal[
        "HOLD",
        "REJECTED",
        "ERROR",
        "OPEN",
        "HELD",
        "SKIPPED",
        "UNKNOWN",
        "MAINTAIN",
        "TIGHTENED",
        "MANDATORY_EXIT",
    ]
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
    evidence: tuple[ArmSession, ...] = Field(max_length=240)
    benchmarks: tuple[BenchmarkSession, ...] = Field(default=(), max_length=60)
    underlying_settlements: tuple[UnderlyingSettlement, ...] = Field(
        default=(), max_length=180, exclude_if=lambda v: not v
    )

    @model_validator(mode="after")
    def settlements_enrolled(self):
        receipts = self.underlying_settlements
        if receipts and self.manifest.underlying_baseline is None:
            raise ValueError("Underlying settlement requires enrolled baseline")
        if len({r.receipt_id for r in receipts}) != len(receipts) or any(
            not any(
                a.closes_at < r.occurred_at <= b.opens_at
                for a, b in zip(self.manifest.sessions, self.manifest.sessions[1:])
            )
            for r in receipts
        ):
            raise ValueError("Unique between-session underlying settlement receipts required")
        return self
