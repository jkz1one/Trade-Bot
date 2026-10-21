"""Tool-less position plans and pure review. No mutation, reservation or dispatch."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.options.degen import DegenScan
from app.options.engine import clock, fingerprint
from app.options.entry_reasoning import MAX_PACKET_BYTES, Digest
from app.options.governor import admit_option
from app.options.lifecycle import OptionExecutionPolicy, OptionIntent, OptionPosition
from app.options.models import (
    Money,
    Name,
    OptionAccount,
    OptionAdmission,
    OptionHolding,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    OptionRecord,
    PositiveCount,
    SessionWindow,
    UnderlyingQuote,
)
from app.options.protection import assess_position
from app.options.scope_context import ScopeContextScan
from app.options.scope_position import ScopePositionContext
from app.options.swing import SwingScan


class PositionReasoningPolicy(OptionRecord):
    version: Literal["option-position-reasoning-v1"] = "option-position-reasoning-v1"
    scope_carry: Literal["shared-scope-carry-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    swing_carry: Literal["bounded-swing-carry-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    scope_management: Literal["scope-fixed-position-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    cadence_seconds: Literal[300] = 300
    max_lease_seconds: int = Field(gt=0, le=30, strict=True)

    @model_validator(mode="after")
    def matching_context(self):
        paired = self.scope_management is not None and self.swing_carry is not None
        if paired != (self.scope_carry is not None):
            raise ValueError("Combined Scope/carry management requires explicit enrollment")
        return self


def _account_ready(account, position, limits, now):
    holding = OptionHolding.model_validate(
        {k: v for k, v in position.model_dump().items() if k in OptionHolding.model_fields}
    )
    return (
        account.account_id == limits.account_id
        and account.population_id == limits.population_id
        and account.position == holding
        and account.complete
        and account.reconciled
        and account.budgets_known
        and not account.working_orders
        and not account.unsupported_exposure
        and not account.entry_halted
        and not account.entry_blockers
        and timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=limits.account_max_age_seconds)
    )


class CarryPositionContext(OptionRecord):
    original_scan: SwingScan
    overnight_coverage: Literal["NOT_CONTINUOUSLY_OBSERVED"] = "NOT_CONTINUOUSLY_OBSERVED"


class PositionPacket(OptionRecord):
    """Trusted snapshot of one owned position; revision is owned by the future coordinator."""

    version: Literal["option-position-packet-v1"] = "option-position-packet-v1"
    mode: Literal["PAPER"] = "PAPER"
    decision_id: Digest
    cycle_key: Name
    model_configuration_hash: Digest
    as_of: datetime
    valid_until: datetime
    position_revision: PositiveCount
    position: OptionPosition
    entry: OptionIntent
    carry_context: CarryPositionContext | None = Field(default=None, exclude_if=lambda v: v is None)
    account: OptionAccount
    quote: OptionQuote
    underlying: UnderlyingQuote
    scope_context: ScopePositionContext | None = Field(default=None, exclude_if=lambda v: v is None)
    scan: DegenScan | ScopeContextScan
    session: SessionWindow
    limits: OptionLimits
    execution_policy: OptionExecutionPolicy
    policy: PositionReasoningPolicy
    evidence_ids: tuple[Digest, Digest, Digest, Digest, Digest, Digest]

    @model_validator(mode="after")
    def preflight(self):
        p, e, s = self.position, self.entry, self.scan
        if self.policy.scope_carry != self.execution_policy.scope_carry:
            raise ValueError("Matching combined owner and management packet required")
        if p.swing_carry != e.swing_carry or (p.swing_carry is not None) != (
            self.carry_context is not None
        ):
            raise ValueError("Carry position and original entry/context must match")
        if p.swing_carry is not None:
            original = self.carry_context.original_scan
            if (
                self.policy.swing_carry != p.swing_carry.version
                or self.execution_policy.swing_carry != p.swing_carry.version
                or original.carry_terms != p.swing_carry
                or fingerprint(original.seed) != p.swing_carry.seed_hash
                or original.seed.instrument != e.instrument
                or not any(s.opens_at <= self.as_of < s.closes_at for s in p.swing_carry.sessions)
            ):
                raise ValueError("Frozen original Swing context and current carry session required")
        scope = e.entry_lineage is not None and e.entry_lineage.family == "SCOPE"
        if scope != (self.scope_context is not None) or scope != isinstance(s, ScopeContextScan):
            raise ValueError("Scope ownership requires its own exact context")
        if scope:
            from app.options.scope_execution import lineage

            c = self.scope_context
            o = c.original
            if (
                self.policy.scope_management != "scope-fixed-position-v1"
                or self.execution_policy.scope_arbitration != "shared-scope-entry-v1"
                or self.carry_context is not None
                or c.scan != s
                or c.current.frame.quote != self.quote
                or c.current.underlying != self.underlying
                or e.entry_lineage != lineage(o.model_dump(mode="json"))
                or o.binding.account_id != self.limits.account_id
                or o.binding.population_id != self.limits.population_id
                or o.instrument != e.instrument
                or o.geometry.invalidation != e.original_underlying_invalidation
                or o.admission.quantity != e.quantity
                or o.management.target_exit_schedule != e.target_exit_schedule
                or o.management.entry_premium_protection != e.entry_premium_protection
                or o.entry_time_protection != e.entry_time_protection
                or any(
                    getattr(p, name) != getattr(e, name)
                    for name in (
                        "target_exit_schedule",
                        "entry_premium_protection",
                        "entry_time_protection",
                    )
                )
            ):
                raise ValueError("Scope management must preserve original native protection")
        context_ready = (
            s.evaluated_at == self.as_of and not s.issues
            if scope
            else (
                s.symbol == p.contract.underlying
                and s.evaluated_at == self.as_of
                and not s.issues
                and s.completed_through is not None
                and s.higher_timeframe_through is not None
                and s.higher_timeframe_through <= s.completed_through <= self.as_of
                and self.as_of - s.completed_through < timedelta(seconds=300)
                and self.as_of - s.higher_timeframe_through < timedelta(seconds=900)
                and s.last_close is not None
            )
        )
        end_slot = (int(self.as_of.timestamp()) // 300 + 1) * 300
        if (
            self.cycle_key != "position:" + str(int(self.as_of.timestamp()) // 300)
            or not self.as_of < self.valid_until
            or self.valid_until > self.as_of + timedelta(seconds=self.policy.max_lease_seconds)
            or self.valid_until.timestamp() > end_slot
            or self.valid_until
            > min(
                p.exit_at,
                p.contract.last_trading_at
                - timedelta(seconds=self.execution_policy.expiry_guard_seconds),
            )
        ):
            raise ValueError(
                "Position packet must retain its original slot and protection deadline"
            )
        if (
            e.side != "BUY"
            or e.client_id != p.entry_client_id
            or e.instrument != self.quote.instrument
            or e.instrument.contract != p.contract
            or e.original_underlying_invalidation != p.original_underlying_invalidation
            or e.entry_protection != p.entry_protection
            or e.exit_at != p.exit_at
            or p.quantity > e.quantity
            or e.prepared_at > self.as_of
            or not context_ready
            or p.supervision_issue is not None
            or not _account_ready(self.account, p, self.limits, self.as_of)
        ):
            raise ValueError("Exact healthy owned position, entry and completed context required")
        assessed = assess_position(
            p, self.quote, self.underlying, self.limits, self.execution_policy, now=self.as_of
        )
        close = admit_option(
            OptionProposal(
                action="CLOSE", contract=p.contract, thesis="Position reasoning preflight"
            ),
            self.quote,
            None,
            self.account,
            self.limits,
            self.session,
            now=self.as_of,
        )
        if assessed.exit_reason or assessed.supervision_issue or close.outcome != "APPROVED":
            raise ValueError("Mandatory protection and market/account readiness precede reasoning")
        if self.evidence_ids != tuple(
            fingerprint(x) for x in (p, e, self.account, self.quote, self.underlying, s)
        ):
            raise ValueError("Exact position, entry, account, quote and scan references required")
        if len(self.model_dump_json().encode()) > MAX_PACKET_BYTES:
            raise ValueError("Position packet capacity exceeded")
        return self


class PositionPlan(OptionRecord):
    version: Literal["option-position-plan-v1"] = "option-position-plan-v1"
    decision_id: Digest
    packet_hash: Digest
    entry_client_id: Name
    position_revision: PositiveCount
    action: Literal["MAINTAIN", "EXIT_ALL", "TIGHTEN"]
    underlying_invalidation: Money | None = Field(default=None, gt=0)
    evidence_ids: tuple[Digest, ...] = Field(min_length=1, max_length=8)
    thesis: str = Field(min_length=1, max_length=500)
    change_since_entry: str = Field(min_length=1, max_length=500)
    uncertainty: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def coherent(self):
        if (self.action == "TIGHTEN") != (self.underlying_invalidation is not None):
            raise ValueError("Only TIGHTEN carries one underlying invalidation price")
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(
            not x.strip() for x in (self.thesis, self.change_since_entry, self.uncertainty)
        ):
            raise ValueError("Unique references and nonblank bounded reasoning required")
        return self


class PositionReview(OptionRecord):
    execution_authority: Literal[False] = False
    outcome: Literal["MAINTAIN", "REJECTED", "ELIGIBLE", "MANDATORY_EXIT"]
    reasons: tuple[Name, ...]
    packet_hash: Digest
    plan: PositionPlan
    proposal: OptionProposal | None = None
    admission: OptionAdmission | None = None
    tightened_invalidation: Money | None = None


def review_position_plan(
    packet, plan, *, position, position_revision, account, quote, underlying, now
):
    """Fresh post-cost review only. Caller must enforce durable revision consumption.

    An ELIGIBLE result cannot act, settle costs or clear a protection latch. Repeated
    pure calls do not consume anything. No model call or provider read occurs here.
    """
    now = clock(now)
    packet = PositionPacket.model_validate(packet.model_dump(warnings=False))
    plan = PositionPlan.model_validate(plan.model_dump(warnings=False))
    digest = fingerprint(packet)

    def result(outcome, *reasons, **values):
        return PositionReview(
            outcome=outcome, reasons=reasons, packet_hash=digest, plan=plan, **values
        )

    if (
        plan.packet_hash != digest
        or plan.decision_id != packet.decision_id
        or plan.entry_client_id != packet.position.entry_client_id
        or plan.position_revision != packet.position_revision
    ):
        return result("REJECTED", "POSITION_PLAN_BINDING_MISMATCH")
    if not set(plan.evidence_ids) <= set(packet.evidence_ids) or not {
        packet.evidence_ids[0],
        packet.evidence_ids[5],
    } <= set(plan.evidence_ids):
        return result("REJECTED", "POSITION_AND_CONTEXT_REFERENCES_REQUIRED")
    position = (
        OptionPosition.model_validate(position.model_dump(warnings=False))
        if position is not None
        else None
    )
    if (
        position is None
        or type(position_revision) is not int
        or position_revision != packet.position_revision
        or position.entry_client_id != packet.position.entry_client_id
        or position.contract != packet.position.contract
    ):
        return result("REJECTED", "POSITION_REVISION_CHANGED")
    quote = (
        OptionQuote.model_validate(quote.model_dump(warnings=False)) if quote is not None else None
    )
    underlying = (
        UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
        if underlying is not None
        else None
    )
    assessed = assess_position(
        position, quote, underlying, packet.limits, packet.execution_policy, now=now
    )
    if assessed.exit_reason:
        return result("MANDATORY_EXIT", assessed.exit_reason)
    if position != packet.position:
        return result("REJECTED", "POSITION_STATE_CHANGED")
    if not packet.as_of <= now < packet.valid_until:
        return result("REJECTED", "ORIGINAL_POSITION_DEADLINE_EXPIRED")
    account = OptionAccount.model_validate(account.model_dump(warnings=False))
    if not _account_ready(account, position, packet.limits, now):
        return result("REJECTED", "POSITION_ACCOUNT_BLOCKED")
    if assessed.supervision_issue:
        return result("REJECTED", assessed.supervision_issue)
    if (
        quote.instrument != packet.quote.instrument
        or account.captured_at < packet.account.captured_at
        or quote.source_at < packet.quote.source_at
        or quote.received_at < packet.quote.received_at
        or underlying.source_at < packet.underlying.source_at
        or underlying.received_at < packet.underlying.received_at
    ):
        return result("REJECTED", "POSITION_EVIDENCE_IDENTITY_OR_TIME_REGRESSION")
    if plan.action == "MAINTAIN":
        return result("MAINTAIN", "MODEL_MAINTAIN_NO_AUTHORITY")
    if plan.action == "TIGHTEN":
        price, stop = plan.underlying_invalidation, position.tightened_underlying_invalidation
        if (position.contract.right == "CALL" and not stop < price < underlying.bid) or (
            position.contract.right == "PUT" and not underlying.ask < price < stop
        ):
            return result("REJECTED", "INVALIDATION_MUST_TIGHTEN_WITHOUT_CROSSING")
        return result("ELIGIBLE", "OFFLINE_TIGHTEN_VALIDATED", tightened_invalidation=price)
    proposal = OptionProposal(action="CLOSE", contract=position.contract, thesis=plan.thesis)
    admission = admit_option(proposal, quote, None, account, packet.limits, packet.session, now=now)
    if admission.outcome != "APPROVED":
        return result("REJECTED", *admission.reasons)
    if admission.quantity != position.quantity:
        return result("REJECTED", "EXIT_ALL_EXECUTABLE_SIZE_REQUIRED")
    admission = admission.model_copy(
        update={"valid_until": min(admission.valid_until, packet.valid_until)}
    )
    return result("ELIGIBLE", "OFFLINE_EXIT_ALL_VALIDATED", proposal=proposal, admission=admission)
