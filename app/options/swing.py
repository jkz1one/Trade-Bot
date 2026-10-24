"""Next-session Swing evidence for the shared PAPER owner, without overnight authority."""

from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from app.options.carry_models import SwingCarryPolicy, SwingCarryTerms
from app.options.degen import DegenBar, DegenScan, _metric
from app.options.governor import _fresh
from app.options.models import (
    Evidence,
    Money,
    Name,
    OptionInstrument,
    OptionRecord,
    Symbol,
    UnderlyingQuote,
)
from app.options.selection import ContractMetadata, ContractReadPlan, OptionInventory, _plan
from app.options.swing_base_models import SwingBaseEvidence, SwingBasePolicy, SwingFamily
from app.options.swing_level_models import (
    LEVEL_FAMILIES,
    LevelKey,
    SwingLevelEvidence,
    SwingLevelPolicy,
)
from app.options.swing_ma_models import MA_FAMILIES, MAPeriod, SwingMAEvidence, SwingMAPolicy
from app.options.swing_target_models import SwingTargetGeometry


class SwingPolicy(OptionRecord):
    version: Literal["swing-next-session-v1"] = "swing-next-session-v1"
    history_source: Name
    catalyst_source: Name
    daily_lookback: int = Field(ge=3, le=260, strict=True)
    daily_base: SwingBasePolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    ma_pullback: SwingMAPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    higher_levels: SwingLevelPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    family_batch: Literal["complete-family-batch-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    minimum_dte: int = Field(ge=1, le=60, strict=True)
    maximum_dte: int = Field(ge=1, le=90, strict=True)
    maximum_chase_fraction: Money = Field(gt=0, le=Decimal(".1"))
    stop_buffer_fraction: Money = Field(gt=0, le=Decimal(".01"))
    catalyst_max_age_seconds: int = Field(gt=0, le=60, strict=True)
    family_priority: tuple[Literal["DEGEN", "SWING"], Literal["DEGEN", "SWING"]]
    holding_policy: Literal["SESSION_CLOSE", "BOUNDED_CARRY_V1"] = "SESSION_CLOSE"
    carry: SwingCarryPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    target_derivation: Literal["original-risk-ladder-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    unfilled_lifecycle: (
        Literal["completed-invalidation-v1", "observed-invalidation-v2", "observed-lifecycle-v3"]
        | None
    ) = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coherent(self):
        if self.family_batch is not None:
            if (
                not any((self.daily_base, self.ma_pullback, self.higher_levels))
                or self.daily_lookback < 56
            ):
                raise ValueError(
                    "Joint Swing requires explicit families and complete daily context"
                )
            if (
                self.daily_base
                and self.ma_pullback
                and (
                    self.daily_base.hourly_source != self.ma_pullback.hourly_source
                    or self.daily_base.hourly_lookback != self.ma_pullback.hourly_lookback
                )
            ):
                raise ValueError("Joint Swing requires one original hourly source and coverage")
        elif (
            sum(p is not None for p in (self.daily_base, self.ma_pullback, self.higher_levels)) > 1
        ):
            raise ValueError("Separate frozen base, MA and level enrollment required")
        if self.higher_levels is not None:
            if self.daily_lookback < 56 or self.target_derivation != "original-risk-ladder-v1":
                raise ValueError(
                    "Higher levels require original targets and complete source periods"
                )
        elif self.ma_pullback is not None:
            if self.daily_lookback < 56 or self.target_derivation != "original-risk-ladder-v1":
                raise ValueError(
                    "MA pullback requires original targets and 56 completed daily bars"
                )
        elif self.daily_base is None:
            if self.daily_lookback > 20:
                raise ValueError("Legacy Swing lookback remains bounded to twenty sessions")
        elif self.daily_lookback < 55 or self.target_derivation != "original-risk-ladder-v1":
            raise ValueError("Daily base requires original targets and available prior daily trend")
        if (
            self.target_derivation is not None
            and self.unfilled_lifecycle != "observed-lifecycle-v3"
        ):
            raise ValueError("Derived Swing targets require original target retirement")
        if (self.holding_policy == "BOUNDED_CARRY_V1") != (self.carry is not None) or (
            self.carry is not None and self.unfilled_lifecycle != "observed-lifecycle-v3"
        ):
            raise ValueError("Carry requires explicit bounds and original target lifecycle")
        if self.minimum_dte > self.maximum_dte or set(self.family_priority) != {"DEGEN", "SWING"}:
            raise ValueError("Ordered DTE bounds and both unique families required")
        return self


class SwingDailyBar(DegenBar):
    # Explicit exchange boundaries, including half days. No guessed 24-hour bar.
    closes_at: datetime

    @property
    def ends_at(self):
        return self.closes_at


class SwingHistory(Evidence):
    symbol: Symbol
    bounds: Literal["regular"] = "regular"
    adjustment: Literal["split"] = "split"
    bars: tuple[SwingDailyBar, ...] = Field(min_length=3, max_length=20)


class SwingBaseHistory(SwingHistory):
    version: Literal["swing-base-daily-v1"]
    bars: tuple[SwingDailyBar, ...] = Field(min_length=55, max_length=260)


class SwingMAHistory(SwingHistory):
    version: Literal["swing-ma-daily-v1"]
    bars: tuple[SwingDailyBar, ...] = Field(min_length=56, max_length=260)


class SwingLevelHistory(SwingHistory):
    version: Literal["swing-level-daily-v1"]
    bars: tuple[SwingDailyBar, ...] = Field(min_length=56, max_length=260)


class SwingHourlyHistory(Evidence):
    version: Literal["swing-base-hourly-v1"] = "swing-base-hourly-v1"
    symbol: Symbol
    timeframe: Literal["1h"] = "1h"
    bounds: Literal["regular"] = "regular"
    adjustment: Literal["split"] = "split"
    bars: tuple[SwingDailyBar, ...] = Field(min_length=54, max_length=260)


class SwingSeed(OptionRecord):
    version: Literal["swing-locked-seed-v1"] = "swing-locked-seed-v1"
    created_at: datetime
    target_session: date
    history: SwingLevelHistory | SwingMAHistory | SwingBaseHistory | SwingHistory
    level_key: LevelKey | None = Field(default=None, exclude_if=lambda v: v is None)
    ma_period: MAPeriod | None = Field(default=None, exclude_if=lambda v: v is None)
    hourly_history: SwingHourlyHistory | None = Field(default=None, exclude_if=lambda v: v is None)
    instrument: OptionInstrument
    first_target: Money | None = Field(default=None, gt=0, exclude_if=lambda v: v is None)
    carry_exit_session: date | None = Field(default=None, exclude_if=lambda v: v is None)
    batch_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", exclude_if=lambda v: v is None
    )
    target_geometry: SwingTargetGeometry | None = Field(
        default=None, exclude_if=lambda v: v is None
    )


class CatalystEvidence(Evidence):
    symbol: Symbol
    status: Literal["CLEAR", "BLOCKED", "UNKNOWN"]
    valid_through: datetime


class SwingInput(OptionRecord):
    seed: SwingSeed
    metadata: ContractMetadata
    catalyst: CatalystEvidence


class SwingObservation(OptionRecord):
    family: SwingFamily = "SWING_DAILY_BREAKOUT"
    right: Literal["CALL", "PUT"]
    status: Literal["BLOCKED", "WATCHING", "CONFIRMED"]
    reasons: tuple[Name, ...]
    invalidation: Money | None = Field(default=None, gt=0)
    reference: Money | None = Field(default=None, gt=0)


class SwingTerminal(OptionRecord):
    seed_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["INVALIDATED", "TARGET_CONSUMED", "EXPIRED"]
    observed_at: datetime
    triggered_at: datetime
    invalidation: Money | None = Field(default=None, gt=0)
    history_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    first_target: Money | None = Field(default=None, gt=0, exclude_if=lambda v: v is None)
    quote: UnderlyingQuote | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coherent(self):
        invalidated = self.status == "INVALIDATED"
        consumed = self.status == "TARGET_CONSUMED"
        if (
            self.triggered_at > self.observed_at
            or invalidated != (self.invalidation is not None)
            or consumed != (self.first_target is not None)
            or int(self.history_hash is not None) + int(self.quote is not None)
            != int(invalidated or consumed)
            or (self.quote is not None and self.triggered_at != self.quote.source_at)
        ):
            raise ValueError(
                "Dated terminal evidence with exact reason-specific price and observation required"
            )
        return self


class SwingScan(OptionRecord):
    version: Literal["swing-next-session-v1"] = "swing-next-session-v1"
    symbol: Symbol
    evaluated_at: datetime
    completed_through: datetime | None
    higher_timeframe_through: datetime | None
    last_close: Money | None
    seed: SwingSeed
    base_evidence: SwingBaseEvidence | None = Field(default=None, exclude_if=lambda v: v is None)
    level_evidence: SwingLevelEvidence | None = Field(default=None, exclude_if=lambda v: v is None)
    ma_evidence: SwingMAEvidence | None = Field(default=None, exclude_if=lambda v: v is None)
    catalyst: CatalystEvidence
    holding_policy: Literal["SESSION_CLOSE", "BOUNDED_CARRY_V1"] = "SESSION_CLOSE"
    carry_terms: SwingCarryTerms | None = Field(default=None, exclude_if=lambda v: v is None)
    observations: tuple[SwingObservation, ...] = Field(min_length=1, max_length=1)
    issues: tuple[Name, ...] = ()
    terminal: SwingTerminal | None = Field(default=None, exclude_if=lambda v: v is None)


def seed_issues(seed, policy, calendar, symbols):
    """Check actual exchange sessions, immutable past evidence and exact contract lock."""
    from zoneinfo import ZoneInfo

    from app.options.swing_base import input_issues
    from app.options.swing_targets import target_issues

    issues = list(input_issues(seed, policy, calendar))
    issues.extend(target_issues(seed, policy))
    h, c, cal = seed.history, seed.instrument.contract, calendar.calendar
    target = seed.target_session.isoformat()
    if not cal.is_session(target):
        return ("SWING_TARGET_NOT_EXCHANGE_SESSION",)
    previous = cal.previous_session(target)
    opened = cal.session_open(target).to_pydatetime()
    closed = cal.session_close(previous).to_pydatetime()
    if not closed <= h.source_at <= h.received_at <= seed.created_at < opened:
        issues.append("SWING_SEED_NOT_KNOWN_BEFORE_TARGET_OPEN")
    if (
        h.symbol not in symbols
        or h.source != policy.history_source
        or not h.complete
        or h.entitlement != "REALTIME"
        or len(h.bars) != policy.daily_lookback
    ):
        issues.append("SWING_DAILY_HISTORY_BINDING_OR_COVERAGE")
    if (policy.carry is not None) != (seed.carry_exit_session is not None):
        issues.append("SWING_CARRY_SEED_POLICY_REQUIRED")
    reference = h.bars[-1].high if c.right == "CALL" else h.bars[-1].low
    if policy.unfilled_lifecycle == "observed-lifecycle-v3":
        if seed.first_target is None or (
            seed.first_target <= reference if c.right == "CALL" else seed.first_target >= reference
        ):
            issues.append("SWING_ORIGINAL_FIRST_TARGET_REQUIRED")
    elif seed.first_target is not None:
        issues.append("SWING_FIRST_TARGET_POLICY_REQUIRED")
    expected = previous
    for bar in reversed(h.bars):
        if (
            bar.begins_at != cal.session_open(expected).to_pydatetime()
            or bar.closes_at != cal.session_close(expected).to_pydatetime()
            or bar.closes_at > h.source_at
            or bar.interpolated
            or bar.volume <= 0
        ):
            issues.append("SWING_DAILY_BARS_INCOMPLETE_GAPPED_OR_INTERPOLATED")
            break
        expected = cal.previous_session(expected)
    dte = (c.expiration - seed.target_session).days
    if (
        c.underlying != h.symbol
        or c.root != h.symbol
        or not policy.minimum_dte <= dte <= policy.maximum_dte
        or not cal.is_session(c.expiration.isoformat())
        or c.last_trading_at.astimezone(ZoneInfo("America/New_York")).date() != c.expiration
        or c.last_trading_at <= opened
    ):
        issues.append("SWING_LOCKED_CONTRACT_INELIGIBLE")
    return tuple(issues)


def scan_swing(item, policy, intraday, history, calendar, symbols, *, now, receive_lag):
    item = SwingInput.model_validate(item.model_dump(warnings=False))
    policy = SwingPolicy.model_validate(policy.model_dump(warnings=False))
    intraday = DegenScan.model_validate(intraday.model_dump(warnings=False))
    with localcontext(Context(prec=192)):
        seed, catalyst = item.seed, item.catalyst
        issues = list(seed_issues(seed, policy, calendar, symbols))
        if seed.created_at > now:
            issues.append("SWING_SEED_FROM_FUTURE")
        window = calendar.current_window(now)
        if window is None or window.session_date != seed.target_session.isoformat():
            issues.append("SWING_WRONG_TARGET_SESSION")
        if (
            intraday.symbol != seed.history.symbol
            or intraday.issues
            or intraday.evaluated_at != now
        ):
            issues.append("SWING_CURRENT_COMPLETED_STRUCTURE_REQUIRED")
        if (
            catalyst.symbol != seed.history.symbol
            or catalyst.source != policy.catalyst_source
            or catalyst.status != "CLEAR"
            or not catalyst.complete
            or catalyst.entitlement != "REALTIME"
            or not _fresh(
                catalyst.source_at,
                catalyst.received_at,
                now,
                policy.catalyst_max_age_seconds,
                receive_lag,
            )
            or window is None
            or catalyst.valid_through < window.closes_at
        ):
            issues.append("SWING_CATALYST_CLEARANCE_REQUIRED")
        carry_terms = None
        if policy.carry is not None:
            from app.options.swing_execution import scan_carry_terms

            carry_terms, carry_issues = scan_carry_terms(seed, policy, catalyst, calendar)
            issues.extend(carry_issues)
        if item.metadata.instrument != seed.instrument:
            issues.append("SWING_CONTRACT_LOCK_CHANGED")
        right = seed.instrument.contract.right
        sign = 1 if right == "CALL" else -1
        daily = seed.history.bars
        reference = daily[-1].high if sign == 1 else daily[-1].low
        stop = (
            daily[-1].low * (1 - policy.stop_buffer_fraction)
            if sign == 1
            else daily[-1].high * (1 + policy.stop_buffer_fraction)
        )
        reasons = list(issues)
        base = ma = level = None
        from app.options.swing_batch import family_policy

        family = family_policy(seed, policy)
        if family.higher_levels is not None:
            from app.options.swing_levels import evaluate_level

            try:
                level = evaluate_level(seed)
                reference, stop = level.reference, level.invalidation
                reasons.extend(level.reasons)
            except (ValueError, ArithmeticError):
                issues.append("SWING_LEVEL_EVIDENCE_UNAVAILABLE")
                reasons.append("SWING_LEVEL_EVIDENCE_UNAVAILABLE")
        elif family.ma_pullback is not None:
            from app.options.swing_ma import evaluate_ma

            try:
                ma = evaluate_ma(seed)
                reference, stop = ma.reference, ma.invalidation
                reasons.extend(ma.reasons)
            except (ValueError, ArithmeticError):
                issues.append("SWING_MA_EVIDENCE_UNAVAILABLE")
                reasons.append("SWING_MA_EVIDENCE_UNAVAILABLE")
        elif family.daily_base is not None:
            from app.options.swing_base import evaluate_base

            try:
                base = evaluate_base(seed)
                reference, stop = base.reference, base.invalidation
                reasons.extend(base.reasons)
            except (ValueError, ArithmeticError):
                issues.append("SWING_BASE_EVIDENCE_UNAVAILABLE")
                reasons.append("SWING_BASE_EVIDENCE_UNAVAILABLE")
        elif any((b.close - a.close) * sign <= 0 for a, b in pairwise(daily)):
            reasons.append("SWING_DAILY_TREND_REQUIRED")
        complete = [
            b for b in history.bars if b.ends_at <= min(now, history.source_at, history.received_at)
        ]
        if len(complete) < 6 or any((b.close - reference) * sign <= 0 for b in complete[-2:]):
            reasons.append("SWING_COMPLETED_BREAK_AND_HOLD_REQUIRED")
        if (
            intraday.last_close is None
            or abs(intraday.last_close / reference - 1) > policy.maximum_chase_fraction
        ):
            reasons.append("SWING_CHASE_LIMIT")
        scan = SwingScan(
            symbol=seed.history.symbol,
            evaluated_at=now,
            completed_through=intraday.completed_through,
            higher_timeframe_through=daily[-1].closes_at,
            last_close=intraday.last_close,
            seed=seed,
            base_evidence=base,
            level_evidence=level,
            ma_evidence=ma,
            catalyst=catalyst,
            holding_policy=policy.holding_policy,
            carry_terms=carry_terms,
            observations=(
                SwingObservation(
                    family=LEVEL_FAMILIES[seed.level_key]
                    if family.higher_levels is not None and seed.level_key in LEVEL_FAMILIES
                    else MA_FAMILIES[seed.ma_period]
                    if family.ma_pullback is not None and seed.ma_period in MA_FAMILIES
                    else "SWING_DAILY_BASE"
                    if family.daily_base is not None
                    else "SWING_DAILY_BREAKOUT",
                    right=right,
                    status="BLOCKED" if issues else "WATCHING" if reasons else "CONFIRMED",
                    reasons=tuple(reasons),
                    invalidation=_metric(stop, ROUND_CEILING if sign == 1 else ROUND_FLOOR),
                    reference=reference,
                ),
            ),
            issues=tuple(issues),
        )
        if policy.unfilled_lifecycle is not None:
            from app.options.swing_lifecycle import apply_terminal, completed_terminal

            return apply_terminal(
                scan,
                completed_terminal(scan, history, intraday, policy, calendar, symbols),
            )
        return scan


def plan_swing_reads(scan, item, selection, limits, *, now):
    """Exactly the prior locked contract; a missing/bad lock never substitutes a chain."""
    if item.metadata.instrument != scan.seed.instrument:
        return ContractReadPlan(
            symbol=scan.symbol,
            evaluated_at=now,
            instruments=(),
            exclusions={},
            issues=("SWING_CONTRACT_LOCK_CHANGED",),
        )
    m = item.metadata
    inventory = OptionInventory(
        request_id="swing-locked-contract",
        symbol=scan.symbol,
        expiration=scan.seed.instrument.contract.expiration,
        contracts=(m,),
        source=m.source,
        source_at=m.source_at,
        received_at=m.received_at,
        entitlement=m.entitlement,
        complete=m.complete,
    )
    with localcontext(Context(prec=192)):
        return _plan(scan, inventory, selection, limits, now, expiration=inventory.expiration)
