"""Offline entry-plan contract and deterministic review; never execution authority."""

from datetime import datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.options.degen import DegenScan
from app.options.engine import clock, fingerprint
from app.options.governor import admit_option
from app.options.models import (
    Money,
    Name,
    OptionAccount,
    OptionAdmission,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    OptionRecord,
    SessionWindow,
    UnderlyingQuote,
)
from app.options.selection import DegenCandidate

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MAX_PACKET_BYTES = 256 * 1024


class EntryReasoningPolicy(OptionRecord):
    version: Literal["option-entry-reasoning-v1"] = "option-entry-reasoning-v1"
    max_horizon_seconds: int = Field(gt=0, le=21600, strict=True)
    max_target_fraction: Money = Field(gt=0, le=Decimal(".1"))
    max_trigger_fraction: Money = Field(gt=0, le=Decimal(".1"))
    minimum_reward_risk: Money = Field(gt=0, le=100)


class EntryOpportunity(OptionRecord):
    candidate: DegenCandidate
    scan: DegenScan
    quote: OptionQuote
    underlying: UnderlyingQuote
    session: SessionWindow
    evidence_ids: tuple[Digest, Digest, Digest]

    @model_validator(mode="after")
    def references(self):
        if self.evidence_ids != tuple(
            fingerprint(x) for x in (self.scan, self.quote, self.underlying)
        ):
            raise ValueError("Evidence IDs must name the exact supplied scan and quotes")
        return self


class EntryPacket(OptionRecord):
    """Created by trusted software from admitted evidence, never from model output."""

    version: Literal["option-entry-packet-v1"] = "option-entry-packet-v1"
    mode: Literal["PAPER"] = "PAPER"
    decision_id: Digest
    cycle_key: Name
    model_configuration_hash: Digest
    as_of: datetime
    valid_until: datetime
    account: OptionAccount
    limits: OptionLimits
    policy: EntryReasoningPolicy
    opportunities: tuple[EntryOpportunity, ...] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def preflight(self):
        if (
            self.cycle_key != "degen:" + str(int(self.as_of.timestamp()) // 300)
            or not self.as_of < self.valid_until
            or self.valid_until.timestamp() > (int(self.as_of.timestamp()) // 300 + 1) * 300
        ):
            raise ValueError("Packet must expire within its original five-minute opportunity")
        ids = [o.candidate.candidate_id for o in self.opportunities]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate entry candidates")
        for o in self.opportunities:
            c, s = o.candidate, o.scan
            setup = [
                x
                for x in s.observations
                if x.family == c.family and x.right == c.instrument.contract.right
            ]
            if (
                s.issues
                or s.evaluated_at != self.as_of
                or s.completed_through is None
                or s.higher_timeframe_through is None
                or not s.higher_timeframe_through <= s.completed_through <= self.as_of
                or s.last_close is None
                or len(setup) != 1
                or setup[0].status != "CONFIRMED"
                or setup[0].invalidation != c.proposal.underlying_invalidation
                or c.symbol != s.symbol
                or c.symbol != c.instrument.contract.underlying
                or c.instrument != o.quote.instrument
                or c.proposal.contract != c.instrument.contract
                or c.proposal.action != "OPEN_LONG"
                or c.candidate_id
                != fingerprint(
                    {"scan": s, "instrument": c.instrument, "family": c.family, "quote": o.quote}
                )
            ):
                raise ValueError("Exact confirmed setup, candidate and evidence binding required")
            actual = admit_option(
                c.proposal,
                o.quote,
                o.underlying,
                self.account,
                self.limits,
                o.session,
                now=self.as_of,
            )
            if (
                actual != c.admission
                or actual.outcome != "APPROVED"
                or actual.valid_until is None
                or self.valid_until > actual.valid_until
            ):
                raise ValueError("Reproducible admission and original expiry required")
        if len(self.model_dump_json().encode()) > MAX_PACKET_BYTES:
            raise ValueError("Entry packet capacity exceeded")
        return self


class EntryPlan(OptionRecord):
    """Strict model output. All prices refer to the underlying, never option premium."""

    version: Literal["option-entry-plan-v1"] = "option-entry-plan-v1"
    decision_id: Digest
    packet_hash: Digest
    action: Literal["HOLD", "ENTER"]
    candidate_id: Digest | None = None
    condition: Literal["NOW", "ABOVE", "BELOW"] | None = None
    underlying_trigger: Money | None = Field(default=None, gt=0)
    underlying_invalidation: Money | None = Field(default=None, gt=0)
    underlying_target: Money | None = Field(default=None, gt=0)
    horizon_seconds: int | None = Field(default=None, gt=0, le=21600, strict=True)
    evidence_ids: tuple[Digest, ...] = Field(min_length=1, max_length=8)
    thesis: str = Field(min_length=1, max_length=500)
    uncertainty: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def coherent(self):
        if not self.thesis.strip() or not self.uncertainty.strip():
            raise ValueError("Nonblank thesis and uncertainty required")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Duplicate evidence references")
        terms = (
            self.candidate_id,
            self.condition,
            self.underlying_invalidation,
            self.underlying_target,
            self.horizon_seconds,
        )
        if self.action == "HOLD":
            if any(x is not None for x in (*terms, self.underlying_trigger)):
                raise ValueError("HOLD cannot carry entry terms")
        elif any(x is None for x in terms) or (
            (self.condition == "NOW") != (self.underlying_trigger is None)
        ):
            raise ValueError("ENTER requires complete coherent underlying terms")
        return self


class EntryReview(OptionRecord):
    execution_authority: Literal[False] = False
    outcome: Literal["HOLD", "REJECTED", "ELIGIBLE"]
    reasons: tuple[Name, ...]
    packet_hash: Digest
    plan: EntryPlan
    proposal: OptionProposal | None = None
    admission: OptionAdmission | None = None
    exit_by: datetime | None = None


def review_entry_plan(packet, plan, *, quote, underlying, account, now):
    """Pure review after cost settlement using fresh caller-owned account/quotes.

    ELIGIBLE is not an order approval for dispatch. A future durable coordinator
    must retain the complete review/target/horizon and independently re-admit.
    No receipt, model call, reservation, journal mutation or recovery occurs here.
    """
    now = clock(now)
    packet = EntryPacket.model_validate(packet.model_dump(warnings=False))
    plan = EntryPlan.model_validate(plan.model_dump(warnings=False))
    digest = fingerprint(packet)

    def result(outcome, *reasons, **values):
        return EntryReview(
            outcome=outcome, reasons=reasons, packet_hash=digest, plan=plan, **values
        )

    if plan.packet_hash != digest or plan.decision_id != packet.decision_id:
        return result("REJECTED", "PLAN_PACKET_MISMATCH")
    known = {fingerprint(packet.account)}
    for o in packet.opportunities:
        known.update(o.evidence_ids)
    if not set(plan.evidence_ids) <= known:
        return result("REJECTED", "UNKNOWN_EVIDENCE_REFERENCE")
    if not packet.as_of <= now < packet.valid_until:
        return result("REJECTED", "ORIGINAL_PLAN_DEADLINE_EXPIRED")
    if plan.action == "HOLD":
        return result("HOLD", "MODEL_HOLD")
    opportunity = next(
        (o for o in packet.opportunities if o.candidate.candidate_id == plan.candidate_id), None
    )
    if opportunity is None:
        return result("REJECTED", "UNKNOWN_CANDIDATE")
    if not set(opportunity.evidence_ids) <= set(plan.evidence_ids):
        return result("REJECTED", "SELECTED_EVIDENCE_REQUIRED")
    quote = OptionQuote.model_validate(quote.model_dump(warnings=False))
    underlying = UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
    account = OptionAccount.model_validate(account.model_dump(warnings=False))
    if (
        quote.instrument != opportunity.quote.instrument
        or account.captured_at < packet.account.captured_at
        or quote.source_at < opportunity.quote.source_at
        or underlying.source_at < opportunity.underlying.source_at
    ):
        return result("REJECTED", "EVIDENCE_IDENTITY_OR_TIME_REGRESSION")
    with localcontext(Context(prec=192)):
        return _review(packet, plan, opportunity, quote, underlying, account, now, result)


def _review(packet, plan, o, quote, underlying, account, now, result):
    c, p = o.candidate, packet.policy
    stop, target = plan.underlying_invalidation, plan.underlying_target
    assert stop is not None and target is not None and plan.horizon_seconds is not None
    call = c.instrument.contract.right == "CALL"
    original = c.proposal.underlying_invalidation
    assert original is not None
    if (call and stop < original) or (not call and stop > original):
        return result("REJECTED", "INVALIDATION_WIDENS_SETUP")
    anchor = o.underlying.ask if call else o.underlying.bid
    if abs(target - anchor) > anchor * p.max_target_fraction:
        return result("REJECTED", "TARGET_OUTSIDE_FROZEN_ENVELOPE")
    exit_by = packet.as_of + timedelta(seconds=plan.horizon_seconds)
    if (
        plan.horizon_seconds > p.max_horizon_seconds
        or exit_by <= now
        or exit_by > min(o.session.entry_cutoff_at, c.instrument.contract.last_trading_at)
    ):
        return result("REJECTED", "HORIZON_OUTSIDE_FROZEN_ENVELOPE")
    entry = underlying.ask if call else underlying.bid
    risk, reward = (entry - stop, target - entry) if call else (stop - entry, entry - target)
    if risk <= 0 or reward <= 0 or reward < risk * p.minimum_reward_risk:
        return result("REJECTED", "INVALID_TARGET_RISK_GEOMETRY")
    trigger = plan.underlying_trigger
    if trigger is not None and abs(trigger - anchor) > anchor * p.max_trigger_fraction:
        return result("REJECTED", "TRIGGER_OUTSIDE_FROZEN_ENVELOPE")
    # Fresh admission checks source, entitlement, executable sizes and all money.
    ceiling = c.admission
    limits = packet.limits.model_copy(
        update={
            "max_contracts": min(packet.limits.max_contracts, ceiling.quantity),
            "max_entry_debit": min(packet.limits.max_entry_debit, ceiling.entry_debit),
            "max_full_premium_loss": min(
                packet.limits.max_full_premium_loss, ceiling.full_premium_loss
            ),
        }
    )
    proposal = OptionProposal(
        action="OPEN_LONG",
        contract=c.instrument.contract,
        underlying_invalidation=stop,
        max_entry_debit=ceiling.entry_debit,
        thesis=plan.thesis,
    )
    admission = admit_option(proposal, quote, underlying, account, limits, o.session, now=now)
    if admission.outcome != "APPROVED":
        return result("REJECTED", *admission.reasons)
    if admission.limit_price > ceiling.limit_price:
        return result("REJECTED", "ORIGINAL_PRICE_CEILING_EXCEEDED")
    if (plan.condition == "ABOVE" and underlying.bid < trigger) or (
        plan.condition == "BELOW" and underlying.ask > trigger
    ):
        return result("HOLD", "ENTRY_CONDITION_UNMET")
    admission = admission.model_copy(
        update={
            "valid_until": min(admission.valid_until, packet.valid_until, exit_by),
        }
    )
    return result(
        "ELIGIBLE",
        "OFFLINE_PLAN_VALIDATED",
        proposal=proposal,
        admission=admission,
        exit_by=exit_by,
    )
