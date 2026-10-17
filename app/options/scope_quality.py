"""Deterministic Scope research quality and known-level path review. No trade authority."""

from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Context, Decimal, localcontext
from fractions import Fraction
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from app.options.degen import _metric
from app.options.engine import fingerprint
from app.options.models import Money, Name, OptionRecord
from app.options.scope import ScopePreflightInput
from app.options.scope_context import (
    ScopeContextInput,
    ScopeContextObservation,
    ScopeContextPolicy,
    ScopeContextScan,
    scan_scope_context,
)

BASE_SCORES = {
    "opening_range_break_hold": 88,
    "vwap_reclaim_continuation": 86,
    "trend_pullback_continuation": 85,
    "compression_expansion": 84,
    "failed_reversal_continuation": 89,
    "failed_break_reversal": 90,
    "opening_drive_failure": 87,
    "vwap_rejection_reversal": 84,
    "trap_reversal": 93,
}
VARIANT_BONUSES = {
    "dealer_level_acceptance": (2, 94),
    "dealer_level_rejection": (2, 95),
    "implied_move_boundary_rejection": (3, 96),
    "exhaustion_confluence_reversal": (5, 98),
    "prior_level_break_retest": (2, 95),
    "prior_level_rejection": (2, 95),
}


class ScopeQualityPolicy(OptionRecord):
    version: Literal["scope-quality-review-v1"] = "scope-quality-review-v1"
    context: ScopeContextPolicy
    observe_score: int = Field(strict=True, ge=80, le=100)
    watching_score: int = Field(strict=True, ge=90, le=100)
    arm_score: int = Field(strict=True, ge=94, le=100)
    convexity_score: int = Field(strict=True, ge=97, le=100)
    minimum_first_target_r: Money = Field(ge=Decimal("1.5"), le=5)
    structural_path: Literal["completed-spx-levels-v1", "completed-spx-plateaus-v2"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def ordered_scores(self):
        if not self.observe_score <= self.watching_score <= self.arm_score <= self.convexity_score:
            raise ValueError("Ordered Scope quality thresholds required")
        return self


class ScopeQualityComponent(OptionRecord):
    name: Name
    points: int = Field(strict=True, ge=-100, le=100)


class ScopePathLevel(OptionRecord):
    kind: Literal[
        "DEALER_NODE",
        "PRIOR_HIGH",
        "PRIOR_LOW",
        "ATM_UPPER",
        "ATM_LOWER",
        "OPENING_HIGH",
        "OPENING_LOW",
        "SESSION_VWAP",
        "PIVOT_HIGH",
        "PIVOT_LOW",
        "PLATEAU_HIGH",
        "PLATEAU_LOW",
    ]
    level: Money = Field(gt=0)
    at_or_before_first_target: bool
    confirmed_at: datetime | None = Field(default=None, exclude_if=lambda value: value is None)
    formation_started_at: datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    formation_ended_at: datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    touches: int | None = Field(
        default=None, strict=True, ge=2, le=94, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def plateau_evidence(self):
        if self.kind.startswith("PLATEAU"):
            if (
                self.touches is None
                or self.formation_started_at is None
                or self.formation_ended_at is None
                or self.confirmed_at is None
                or self.formation_ended_at - self.formation_started_at
                != timedelta(minutes=5 * self.touches)
                or self.confirmed_at - self.formation_ended_at != timedelta(minutes=5)
            ):
                raise ValueError("Confirmed plateau formation evidence required")
        elif any(
            v is not None
            for v in (self.formation_started_at, self.formation_ended_at, self.touches)
        ):
            raise ValueError("Plateau formation evidence belongs only to plateau levels")
        return self


class ScopeQualityObservation(OptionRecord):
    observation: ScopeContextObservation
    base_score: int | None = Field(default=None, ge=0, le=100)
    components: tuple[ScopeQualityComponent, ...] = ()
    score: int | None = Field(default=None, ge=0, le=100)
    grade: Literal[
        "UNSCORED", "BELOW_OBSERVE", "OBSERVE", "WATCH", "ARM_THRESHOLD", "CONVEXITY_THRESHOLD"
    ] = "UNSCORED"
    first_target_r: Money | None = Field(default=None, ge=0)
    potential_obstructions: tuple[ScopePathLevel, ...] = Field(default=(), max_length=208)
    # The known node/range set is not a complete resistance/support map.
    complete_path_proven: Literal[False] = False
    passed: bool = False
    reasons: tuple[Name, ...] = ()


class ScopeQualityScan(OptionRecord):
    version: Literal["scope-quality-review-v1"] = "scope-quality-review-v1"
    evaluated_at: datetime
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    context: ScopeContextScan
    observations: tuple[ScopeQualityObservation, ...] = Field(default=(), max_length=90)
    issues: tuple[Name, ...] = ()
    authority: Literal[False] = False
    live_enabled: Literal[False] = False


def scan_scope_quality(frame, context, policy, *, now):
    frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
    context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
    policy = ScopeQualityPolicy.model_validate(policy.model_dump(warnings=False))
    scan = scan_scope_context(frame, context, policy.context, now=now)
    base = {
        "evaluated_at": scan.evaluated_at,
        "input_hash": fingerprint({"frame": frame, "context": context}),
        "policy_hash": fingerprint(policy),
        "context": scan,
    }
    if scan.issues:
        return ScopeQualityScan(**base, issues=("SCOPE_CONTEXT_BLOCKED",))
    with localcontext(Context(prec=192)):
        try:
            return ScopeQualityScan(
                **base,
                observations=tuple(
                    _review(o, frame, context, policy, scan) for o in scan.observations
                ),
            )
        except (ArithmeticError, ValidationError):
            return ScopeQualityScan(**base, issues=("QUALITY_NUMERIC_RANGE",))


def _review(o, frame, context, policy, scan):
    if o.status != "DETECTED" or o.geometry is None:
        return ScopeQualityObservation(
            observation=o, reasons=o.reasons or ("SCOPE_CONTEXT_NOT_DETECTED",)
        )
    g = o.geometry
    sign = 1 if o.right == "CALL" else -1
    base = BASE_SCORES[o.parent_pattern]
    if o.pattern in VARIANT_BONUSES:
        bonus, ceiling = VARIANT_BONUSES[o.pattern]
        base = min(ceiling, base + bonus)
    components = []

    def add(name, points):
        components.append(ScopeQualityComponent(name=name, points=points))

    confirmations = sum(
        scan.structure.changes[s] * sign > policy.context.structure.confirmation_fraction
        for s in ("SPY", "QQQ")
    )
    add("CROSS_MARKET_CONFIRMATION", 4 if confirmations == 2 else 3)
    aligned = "BULLISH" if sign == 1 else "BEARISH"
    add("OPTIONS_FLOW", 2 if context.flow.state == aligned else 0)
    add("BROAD_MARKET_NEWS", 1 if context.news.state == aligned else 0)
    add("ECONOMIC_EVENTS", 2 if context.events.state == "CLEAR" else -2)
    risk = abs(g.reference - g.invalidation)
    reward = abs(g.target_one - g.reference)
    reasons = []
    # Compare products before formatting. Rounded display values cannot pass a gate.
    if reward < policy.minimum_first_target_r * risk:
        reasons.append("FIRST_TARGET_REWARD_BELOW_MINIMUM")
    add("FIRST_TARGET_REWARD", 2 if reward >= 2 * risk else 0)
    spot = next(h.bars[-1].close for h in frame.histories if h.symbol == "SPX")
    consumed = (
        abs(spot - (scan.structure.opening_high + scan.structure.opening_low) / 2)
        / context.moves.atm_straddle_move
    )
    add("EXPECTED_MOVE_REMAINING", 3 if consumed <= Decimal(".5") else 1)
    add("DEALER_CONTEXT_PRESENT", 1)
    score = max(0, min(100, base + sum(c.points for c in components)))
    grade = next(
        (
            name
            for threshold, name in (
                (policy.convexity_score, "CONVEXITY_THRESHOLD"),
                (policy.arm_score, "ARM_THRESHOLD"),
                (policy.watching_score, "WATCH"),
                (policy.observe_score, "OBSERVE"),
            )
            if score >= threshold
        ),
        "BELOW_OBSERVE",
    )
    if score < policy.arm_score:
        reasons.append("QUALITY_BELOW_ARM_THRESHOLD")
    if (g.target_one - spot) * sign <= 0:
        reasons.append("FIRST_OBJECTIVE_ALREADY_CONSUMED")
    path = _known_path(frame, context, g, policy, spot, scan.evaluated_at)
    if any(p.at_or_before_first_target for p in path):
        reasons.append("KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE")
    return ScopeQualityObservation(
        observation=o,
        base_score=base,
        components=tuple(components),
        score=score,
        grade=grade,
        first_target_r=_metric(reward / risk, ROUND_FLOOR),
        potential_obstructions=path,
        passed=not reasons,
        reasons=tuple(reasons),
    )


def _known_path(frame, context, g, policy, spot, now):
    """Shared level set after bound coverage passes, from an explicit price origin."""
    sign = 1 if g.right == "CALL" else -1
    levels = [("DEALER_NODE", n) for n in context.dealer.nodes]
    levels.extend(
        (
            ("PRIOR_HIGH", context.prior.high),
            ("PRIOR_LOW", context.prior.low),
            ("ATM_UPPER", context.moves.reference_spot + context.moves.atm_straddle_move),
            ("ATM_LOWER", context.moves.reference_spot - context.moves.atm_straddle_move),
        )
    )
    path = tuple(
        ScopePathLevel(
            kind=kind, level=value, at_or_before_first_target=(value - g.target_one) * sign <= 0
        )
        for kind, value in sorted(levels, key=lambda pair: ((pair[1] - spot) * sign, pair[0]))
        if (value - spot) * sign >= 0 and (value - g.target_two) * sign <= 0
    )
    if policy.structural_path is not None:
        path = tuple(
            sorted(
                (
                    *path,
                    *_structural_path(frame, g, sign, spot=spot),
                    *(
                        _plateau_path(frame, g, sign, spot=spot)
                        if policy.structural_path == "completed-spx-plateaus-v2"
                        else ()
                    ),
                ),
                key=lambda p: (
                    (p.level - spot) * sign,
                    p.kind,
                    p.confirmed_at or now,
                ),
            )
        )
    return path


def _structural_path(frame, geometry, sign, *, spot=None):
    """Only called after complete, hash-bound context/structure coverage passes.

    Exact rational comparisons keep displayed VWAP rounding out of every gate.
    A pivot needs both neighbors and is known only when the right bar completes.
    """
    bars = next(h.bars for h in frame.histories if h.symbol == "SPX")
    spot = Fraction(bars[-1].close if spot is None else spot)
    levels = [
        ("OPENING_HIGH", Fraction(max(b.high for b in bars[:3])), bars[2].ends_at),
        ("OPENING_LOW", Fraction(min(b.low for b in bars[:3])), bars[2].ends_at),
        (
            "SESSION_VWAP",
            sum(
                (Fraction(b.high) + Fraction(b.low) + Fraction(b.close)) * Fraction(b.volume)
                for b in bars
            )
            / (3 * sum(Fraction(b.volume) for b in bars)),
            bars[-1].ends_at,
        ),
    ]
    for left, center, right in zip(bars, bars[1:], bars[2:]):
        if center.high > max(left.high, right.high):
            levels.append(("PIVOT_HIGH", Fraction(center.high), right.ends_at))
        if center.low < min(left.low, right.low):
            levels.append(("PIVOT_LOW", Fraction(center.low), right.ends_at))
    return tuple(
        ScopePathLevel(
            kind=kind,
            level=_metric(Decimal(value.numerator) / Decimal(value.denominator), ROUND_FLOOR),
            at_or_before_first_target=(value - Fraction(geometry.target_one)) * sign <= 0,
            confirmed_at=confirmed,
        )
        for kind, value, confirmed in sorted(
            levels, key=lambda p: ((p[1] - spot) * sign, p[0], p[2])
        )
        if (value - spot) * sign >= 0 and (value - Fraction(geometry.target_two)) * sign <= 0
    )


def _plateau_path(frame, geometry, sign, *, spot):
    """Maximal equal-extreme runs, confirmed only by a strictly lower/higher right bar.

    Called only after complete, bound SPX history passes. No tolerance merges nearby
    prices, no session-edge run has a missing neighbor, and no future bar is inferred.
    """
    bars = next(h.bars for h in frame.histories if h.symbol == "SPX")
    levels = []
    for attr, kind, extreme in (("high", "PLATEAU_HIGH", 1), ("low", "PLATEAU_LOW", -1)):
        start = 0
        while start < len(bars):
            value = getattr(bars[start], attr)
            end = start + 1
            while end < len(bars) and getattr(bars[end], attr) == value:
                end += 1
            if (
                end - start >= 2
                and start > 0
                and end < len(bars)
                and (value - getattr(bars[start - 1], attr)) * extreme > 0
                and (value - getattr(bars[end], attr)) * extreme > 0
                and (value - spot) * sign >= 0
                and (value - geometry.target_two) * sign <= 0
            ):
                levels.append(
                    ScopePathLevel(
                        kind=kind,
                        level=value,
                        at_or_before_first_target=(value - geometry.target_one) * sign <= 0,
                        confirmed_at=bars[end].ends_at,
                        formation_started_at=bars[start].begins_at,
                        formation_ended_at=bars[end - 1].ends_at,
                        touches=end - start,
                    )
                )
            start = end
    return tuple(levels)
