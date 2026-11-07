"""Completed SPX structure and confirmation diagnostics, without candidate authority."""

from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal, get_args

from pydantic import Field, ValidationError, model_validator

from app.options.degen import _metric
from app.options.engine import fingerprint
from app.options.models import Money, Name, OptionRecord
from app.options.scope import (
    MARKETS,
    ScopePreflight,
    ScopePreflightInput,
    ScopePreflightPolicy,
    preflight_scope,
)

ScopePattern = Literal[
    "opening_range_break_hold",
    "vwap_reclaim_continuation",
    "trend_pullback_continuation",
    "compression_expansion",
    "failed_reversal_continuation",
    "failed_break_reversal",
    "opening_drive_failure",
    "vwap_rejection_reversal",
    "trap_reversal",
]
PATTERNS = get_args(ScopePattern)
PRICE_PATTERNS = ("opening_range_break_hold", "compression_expansion", "failed_break_reversal", "trap_reversal")
REVERSALS = frozenset(PATTERNS[5:])


class ScopeStructurePolicy(OptionRecord):
    version: Literal["scope-completed-structure-v1"] = "scope-completed-structure-v1"
    preflight: ScopePreflightPolicy
    # Explicit research values. Source baselines are not automatic trading limits.
    first_target_r: Money = Field(ge=1, le=10)
    second_target_r: Money = Field(gt=1, le=20)
    pullback_touch_points: Money = Field(gt=0, le=100)
    pullback_touch_fraction: Money = Field(gt=0, le=Decimal(".1"))
    compression_fraction: Money = Field(gt=0, lt=1)
    confirmation_fraction: Money = Field(ge=0, lt=Decimal(".1"))
    conflict_fraction: Money = Field(gt=0, lt=Decimal(".1"))

    @model_validator(mode="after")
    def ordered(self):
        if (
            self.first_target_r >= self.second_target_r
            or self.confirmation_fraction >= self.conflict_fraction
        ):
            raise ValueError("Ordered targets and confirmation/conflict bounds required")
        return self


class ScopeGeometry(OptionRecord):
    right: Literal["CALL", "PUT"]
    reference: Money = Field(gt=0)
    invalidation: Money = Field(gt=0)
    target_one: Money = Field(gt=0)
    target_two: Money = Field(gt=0)

    @model_validator(mode="after")
    def directional(self):
        sign = 1 if self.right == "CALL" else -1
        if not (
            self.invalidation * sign
            < self.reference * sign
            < self.target_one * sign
            < self.target_two * sign
        ):
            raise ValueError("Strict directional structure required")
        return self


class ScopeObservation(OptionRecord):
    pattern: ScopePattern
    strategy_class: Literal["CONTINUATION", "REVERSAL"]
    right: Literal["CALL", "PUT"]
    status: Literal["WATCHING", "BLOCKED", "DETECTED"]
    geometry: ScopeGeometry | None
    reasons: tuple[Name, ...]


class ScopeStructureScan(OptionRecord):
    version: Literal["scope-completed-structure-v1"] = "scope-completed-structure-v1"
    evaluated_at: datetime
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preflight: ScopePreflight
    completed_through: datetime | None = None
    opening_high: Money | None = None
    opening_low: Money | None = None
    vwap: Money | None = None
    # Fractions, never percentages or model probabilities.
    changes: dict[Literal["SPX", "SPY", "QQQ"], Money] = Field(default_factory=dict)
    observations: tuple[ScopeObservation, ...] = Field(default=(), max_length=18)
    issues: tuple[Name, ...] = ()
    authority: Literal[False] = False
    live_enabled: Literal[False] = False


def structure_payload_hashes(frame):
    """Exact normalized coverage payloads, not provider-authenticity certificates."""
    frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
    histories = {h.symbol: h for h in frame.histories}
    if len(frame.histories) != 3 or set(histories) != set(MARKETS):
        raise ValueError("Exactly one history for SPX, SPY and QQQ required")
    return {
        "technical_structure": fingerprint(
            {"version": "scope-technical-payload-v1", "history": histories["SPX"]}
        ),
        "cross_market_agreement": fingerprint(
            {
                "version": "scope-confirmation-payload-v1",
                "histories": tuple(histories[symbol] for symbol in MARKETS),
            }
        ),
    }


def scan_scope_structure(frame, policy, *, now):
    """Recompute coverage, technical patterns and confirmation from current supplied bars."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware Scope structure clock required")
    now = now.astimezone(UTC)
    frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
    policy = ScopeStructurePolicy.model_validate(policy.model_dump(warnings=False))
    preflight = preflight_scope(frame, policy.preflight, now=now)
    base = {
        "evaluated_at": now,
        "input_hash": fingerprint(frame),
        "policy_hash": fingerprint(policy),
        "preflight": preflight,
    }
    if preflight.status != "COVERAGE_COMPLETE":
        return ScopeStructureScan(**base, issues=("SCOPE_PREFLIGHT_BLOCKED",))
    with localcontext(Context(prec=192)):
        try:
            return _scan(frame, policy, base)
        except (ArithmeticError, ValidationError):
            # Bounded decimal output cannot silently truncate an unrepresentable geometry.
            return ScopeStructureScan(**base, issues=("STRUCTURE_NUMERIC_RANGE",))


def _scan(frame, policy, base):
    histories = {h.symbol: h for h in frame.histories}
    evidence = {e.kind: e for e in frame.evidence}
    issues = []
    for kind, digest in structure_payload_hashes(frame).items():
        used = (histories["SPX"],) if kind == "technical_structure" else tuple(histories.values())
        e = evidence[kind]
        if e.payload_hash != digest:
            issues.append(kind.upper() + "_PAYLOAD_MISMATCH")
        if any(e.received_at < h.received_at or e.source_at < h.bars[-1].ends_at for h in used):
            issues.append(kind.upper() + "_PAYLOAD_NOT_YET_KNOWN")
    bars = histories["SPX"].bars
    if len(bars) < 5:
        issues.append("FIVE_COMPLETED_SPX_BARS_REQUIRED")
    price_only = policy.preflight.input_basis is not None
    if not price_only and any(b.volume is None or b.volume <= 0 for b in bars):
        issues.append("COMPLETE_VOLUME_BACKED_SPX_VWAP_REQUIRED")
    if issues:
        return ScopeStructureScan(**base, issues=tuple(issues))
    vwap = None if price_only else sum(((b.high + b.low + b.close) * b.volume for b in bars), Decimal(0)) / (
        3 * sum(b.volume for b in bars)
    )
    high, low = max(b.high for b in bars[:3]), min(b.low for b in bars[:3])
    changes = {s: h.bars[-1].close / h.bars[0].open - 1 for s, h in histories.items()}
    pattern_values = _price_patterns(bars, high, low, policy) if price_only else _patterns(bars, high, low, vwap, policy)
    observations = []
    c = frame.metadata.instrument.contract
    for pattern in PRICE_PATTERNS if price_only else PATTERNS:
        for right, sign in (("CALL", 1), ("PUT", -1)):
            geometry, reasons = None, []
            values = pattern_values.get((pattern, right))
            if values is None:
                reasons.append("COMPLETED_PATTERN_NOT_PRESENT")
                status = "WATCHING"
            else:
                reference, stop, neutral_pending = values
                if price_only:
                    # This variant confirms completed price patterns. Freeze its
                    # risk ladder from the confirmation close, not the already
                    # crossed breakout/reclaim level. Current admission still
                    # checks remaining reward and all intervening known levels.
                    reference = bars[-1].close
                risk = (reference - stop) * sign
                if risk <= 0:
                    reasons.append("INVALID_STRUCTURAL_RISK")
                else:
                    geometry = ScopeGeometry(
                        right=right,
                        reference=reference,
                        invalidation=_metric(stop, ROUND_HALF_EVEN),
                        target_one=_metric(
                            reference + sign * policy.first_target_r * risk,
                            ROUND_FLOOR if sign == 1 else ROUND_CEILING,
                        ),
                        target_two=_metric(
                            reference + sign * policy.second_target_r * risk,
                            ROUND_FLOOR if sign == 1 else ROUND_CEILING,
                        ),
                    )
                if neutral_pending:
                    reasons.append("NEUTRAL_RESET_REQUIRES_FRESH_COMPLETED_CONFIRMATION")
                confirmations = (changes["SPY"] * sign, changes["QQQ"] * sign)
                if any(value < -policy.conflict_fraction for value in confirmations):
                    reasons.append("CONFIRMATION_MARKET_MATERIALLY_CONFLICTS")
                if not any(value > policy.confirmation_fraction for value in confirmations):
                    reasons.append("SPY_OR_QQQ_DIRECTIONAL_CONFIRMATION_REQUIRED")
                if c.right != right:
                    reasons.append("EXACT_CONTRACT_RIGHT_MISMATCH")
                elif geometry is not None and (c.strike - geometry.target_two) * sign > 0:
                    reasons.append("EXACT_STRIKE_BEYOND_SECOND_OBJECTIVE")
                if geometry is not None and (bars[-1].close - geometry.target_two) * sign >= 0:
                    reasons.append("STRUCTURAL_OBJECTIVES_ALREADY_CONSUMED")
                status = "BLOCKED" if reasons else "DETECTED"
            observations.append(
                ScopeObservation(
                    pattern=pattern,
                    right=right,
                    strategy_class="REVERSAL" if pattern in REVERSALS else "CONTINUATION",
                    status=status,
                    geometry=geometry,
                    reasons=tuple(reasons),
                )
            )
    return ScopeStructureScan(
        **base,
        completed_through=bars[-1].ends_at,
        opening_high=high,
        opening_low=low,
        vwap=_metric(vwap, ROUND_HALF_EVEN) if vwap is not None else None,
        changes={s: _metric(v, ROUND_HALF_EVEN) for s, v in changes.items()},
        observations=tuple(observations),
    )


def _price_patterns(bars, opening_high, opening_low, policy):
    """Price-only rules: no fabricated index volume, VWAP or external context."""
    rows = bars[-8:]
    latest, previous = rows[-1], rows[-2]
    close, prev = latest.close, previous.close
    lows, highs = min(b.low for b in rows[-3:]), max(b.high for b in rows[-3:])
    prior_high, prior_low = max(b.high for b in rows[-4:-1]), min(b.low for b in rows[-4:-1])
    values = {}
    for right, sign in (("CALL", 1), ("PUT", -1)):
        boundary = opening_high if sign == 1 else opening_low
        stop = lows if sign == 1 else highs
        if (close - boundary) * sign > 0 and (prev - boundary) * sign >= 0:
            values["opening_range_break_hold", right] = boundary, stop, False
        edge = prior_high if sign == 1 else prior_low
        if (prior_high - prior_low <= (opening_high - opening_low) * policy.compression_fraction
                and (close - edge) * sign > 0):
            values["compression_expansion", right] = close, prior_low if sign == 1 else prior_high, False
        opposite = opening_low if sign == 1 else opening_high
        excursion = previous.low < opposite if sign == 1 else previous.high > opposite
        if excursion and (prev - opposite) * sign <= 0 and (close - opposite) * sign > 0:
            values["failed_break_reversal", right] = opposite, stop, True
        if len(rows) >= 6:
            trapped = rows[-3].low < opposite if sign == 1 else rows[-3].high > opposite
            if (trapped and (rows[-3].close - opposite) * sign <= 0
                    and (prev - opposite) * sign > 0 and (close - prev) * sign > 0):
                for pattern in ("trap_reversal", "failed_break_reversal"):
                    values[pattern, right] = opposite, stop, False
    return values


def _patterns(bars, opening_high, opening_low, vwap, policy):
    """Nine pinned price-derived modules. Other six need contextual payload evaluators."""
    rows = bars[-8:]
    latest, previous = rows[-1], rows[-2]
    close, prev = latest.close, previous.close
    slope = close - rows[-4].close
    last_lows, last_highs = min(b.low for b in rows[-3:]), max(b.high for b in rows[-3:])
    prior_high, prior_low = max(b.high for b in rows[-4:-1]), min(b.low for b in rows[-4:-1])
    touch = max(policy.pullback_touch_points, close * policy.pullback_touch_fraction)
    midpoint = (opening_high + opening_low) / 2
    values = {}

    def add(pattern, right, condition, reference, stop, neutral_pending=False):
        if condition:
            values[pattern, right] = reference, stop, neutral_pending

    add(
        "opening_range_break_hold",
        "CALL",
        close > opening_high and prev >= opening_high,
        opening_high,
        min(vwap, last_lows),
    )
    add(
        "opening_range_break_hold",
        "PUT",
        close < opening_low and prev <= opening_low,
        opening_low,
        max(vwap, last_highs),
    )
    add(
        "vwap_reclaim_continuation",
        "CALL",
        rows[-3].close <= vwap < prev <= close and slope > 0,
        close,
        last_lows,
    )
    add(
        "vwap_reclaim_continuation",
        "PUT",
        rows[-3].close >= vwap > prev >= close and slope < 0,
        close,
        last_highs,
    )
    add(
        "trend_pullback_continuation",
        "CALL",
        slope > 0 and close > vwap and last_lows <= vwap + touch and close > prev,
        close,
        last_lows,
    )
    add(
        "trend_pullback_continuation",
        "PUT",
        slope < 0 and close < vwap and last_highs >= vwap - touch and close < prev,
        close,
        last_highs,
    )
    compression = (
        prior_high - prior_low <= (opening_high - opening_low) * policy.compression_fraction
    )
    add(
        "compression_expansion",
        "CALL",
        compression and latest.high > prior_high and close > prior_high,
        close,
        prior_low,
    )
    add(
        "compression_expansion",
        "PUT",
        compression and latest.low < prior_low and close < prior_low,
        close,
        prior_high,
    )
    add(
        "failed_break_reversal",
        "PUT",
        previous.high > opening_high and prev >= opening_high and close < opening_high,
        opening_high,
        max(b.high for b in rows[-2:]),
        True,
    )
    add(
        "failed_break_reversal",
        "CALL",
        previous.low < opening_low and prev <= opening_low and close > opening_low,
        opening_low,
        min(b.low for b in rows[-2:]),
        True,
    )
    add(
        "opening_drive_failure",
        "PUT",
        max(b.high for b in rows[:3]) >= opening_high
        and close < vwap
        and close < midpoint
        and slope < 0,
        close,
        last_highs,
    )
    add(
        "opening_drive_failure",
        "CALL",
        min(b.low for b in rows[:3]) <= opening_low
        and close > vwap
        and close > midpoint
        and slope > 0,
        close,
        last_lows,
    )
    add(
        "vwap_rejection_reversal",
        "PUT",
        close < vwap and latest.high >= vwap and close < latest.open and slope < 0,
        close,
        latest.high,
    )
    add(
        "vwap_rejection_reversal",
        "CALL",
        close > vwap and latest.low <= vwap and close > latest.open and slope > 0,
        close,
        latest.low,
    )
    if len(rows) >= 6:
        add(
            "failed_reversal_continuation",
            "CALL",
            rows[-4].close > vwap and rows[-3].close < vwap and prev >= vwap and close > prev,
            close,
            last_lows,
        )
        add(
            "failed_reversal_continuation",
            "PUT",
            rows[-4].close < vwap and rows[-3].close > vwap and prev <= vwap and close < prev,
            close,
            last_highs,
        )
        for right, condition, reference, stop in (
            (
                "PUT",
                rows[-3].high > opening_high
                and rows[-3].close >= opening_high
                and prev < opening_high
                and close < prev,
                opening_high,
                last_highs,
            ),
            (
                "CALL",
                rows[-3].low < opening_low
                and rows[-3].close <= opening_low
                and prev > opening_low
                and close > prev,
                opening_low,
                last_lows,
            ),
        ):
            # A separate completed neutral bar and fresh follow-through are mandatory.
            add("trap_reversal", right, condition, reference, stop)
            add("failed_break_reversal", right, condition, reference, stop)
    return values
