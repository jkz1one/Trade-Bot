"""Next-session Swing evidence for the shared PAPER owner, without overnight authority."""

from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from app.options.degen import DegenBar, DegenScan, _metric
from app.options.governor import _fresh
from app.options.models import Evidence, Money, Name, OptionInstrument, OptionRecord, Symbol
from app.options.selection import ContractMetadata, ContractReadPlan, OptionInventory, _plan


class SwingPolicy(OptionRecord):
    version: Literal["swing-next-session-v1"] = "swing-next-session-v1"
    history_source: Name
    catalyst_source: Name
    daily_lookback: int = Field(ge=3, le=20, strict=True)
    minimum_dte: int = Field(ge=1, le=60, strict=True)
    maximum_dte: int = Field(ge=1, le=90, strict=True)
    maximum_chase_fraction: Money = Field(gt=0, le=Decimal(".1"))
    stop_buffer_fraction: Money = Field(gt=0, le=Decimal(".01"))
    catalyst_max_age_seconds: int = Field(gt=0, le=60, strict=True)
    family_priority: tuple[Literal["DEGEN", "SWING"], Literal["DEGEN", "SWING"]]
    holding_policy: Literal["SESSION_CLOSE"] = "SESSION_CLOSE"
    unfilled_lifecycle: Literal["completed-invalidation-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def coherent(self):
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


class SwingSeed(OptionRecord):
    version: Literal["swing-locked-seed-v1"] = "swing-locked-seed-v1"
    created_at: datetime
    target_session: date
    history: SwingHistory
    instrument: OptionInstrument


class CatalystEvidence(Evidence):
    symbol: Symbol
    status: Literal["CLEAR", "BLOCKED", "UNKNOWN"]
    valid_through: datetime


class SwingInput(OptionRecord):
    seed: SwingSeed
    metadata: ContractMetadata
    catalyst: CatalystEvidence


class SwingObservation(OptionRecord):
    family: Literal["SWING_DAILY_BREAKOUT"] = "SWING_DAILY_BREAKOUT"
    right: Literal["CALL", "PUT"]
    status: Literal["BLOCKED", "WATCHING", "CONFIRMED"]
    reasons: tuple[Name, ...]
    invalidation: Money | None = Field(default=None, gt=0)
    reference: Money | None = Field(default=None, gt=0)


class SwingTerminal(OptionRecord):
    seed_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["INVALIDATED", "EXPIRED"]
    observed_at: datetime
    triggered_at: datetime
    invalidation: Money | None = Field(default=None, gt=0)
    history_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        invalidated = self.status == "INVALIDATED"
        if (
            self.triggered_at > self.observed_at
            or invalidated != (self.invalidation is not None)
            or invalidated != (self.history_hash is not None)
        ):
            raise ValueError("Dated terminal evidence with exact invalidation history required")
        return self


class SwingScan(OptionRecord):
    version: Literal["swing-next-session-v1"] = "swing-next-session-v1"
    symbol: Symbol
    evaluated_at: datetime
    completed_through: datetime | None
    higher_timeframe_through: datetime | None
    last_close: Money | None
    seed: SwingSeed
    catalyst: CatalystEvidence
    holding_policy: Literal["SESSION_CLOSE"] = "SESSION_CLOSE"
    observations: tuple[SwingObservation, ...] = Field(min_length=1, max_length=1)
    issues: tuple[Name, ...] = ()
    terminal: SwingTerminal | None = Field(default=None, exclude_if=lambda v: v is None)


def seed_issues(seed, policy, calendar, symbols):
    """Check actual exchange sessions, immutable past evidence and exact contract lock."""
    from zoneinfo import ZoneInfo

    issues = []
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
        if any((b.close - a.close) * sign <= 0 for a, b in pairwise(daily)):
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
            catalyst=catalyst,
            observations=(
                SwingObservation(
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
            from app.options.swing_lifecycle import apply_terminal, completed_invalidation

            return apply_terminal(
                scan,
                completed_invalidation(scan, history, intraday, policy, calendar, symbols),
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
