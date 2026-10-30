"""Bound Scope context variants and risk diagnostics. No admission or account authority."""

from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from typing import Literal, get_args

from pydantic import Field, ValidationError, model_validator

from app.options.engine import fingerprint
from app.options.governor import _fresh
from app.options.models import Evidence, Money, Name, OptionRecord
from app.options.scope_structure import (
    ScopeObservation,
    ScopePattern,
    ScopeStructurePolicy,
    ScopeStructureScan,
    scan_scope_structure,
)

ContextPattern = Literal[
    "prior_level_break_retest",
    "prior_level_rejection",
    "dealer_level_acceptance",
    "dealer_level_rejection",
    "implied_move_boundary_rejection",
    "exhaustion_confluence_reversal",
]
CONTEXT_PATTERNS = get_args(ContextPattern)


class ScopeDealerContext(Evidence):
    symbol: Literal["SPX"] = "SPX"
    nodes: tuple[Money, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def bounded_nodes(self):
        if any(n <= 0 for n in self.nodes) or len(set(self.nodes)) != len(self.nodes):
            raise ValueError("Positive unique observed dealer nodes required")
        return self


class ScopeMoveContext(Evidence):
    symbol: Literal["SPX"] = "SPX"
    expiration: date
    reference_spot: Money = Field(gt=0)
    atm_straddle_move: Money = Field(gt=0)
    iv_derived_move: Money = Field(gt=0)

    @model_validator(mode="after")
    def positive_boundary(self):
        if self.reference_spot <= self.atm_straddle_move:
            raise ValueError("Positive lower expected-move boundary required")
        return self


class ScopeBiasContext(Evidence):
    kind: Literal["options_flow", "broad_market_news"]
    scope: Literal["SPX_SPXW", "BROAD_MARKET"]
    state: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
    valid_through: datetime

    @model_validator(mode="after")
    def correct_scope(self):
        expected = "SPX_SPXW" if self.kind == "options_flow" else "BROAD_MARKET"
        if self.scope != expected:
            raise ValueError("Flow/news universe must match the declared evidence kind")
        return self


class ScopeEventContext(Evidence):
    scope: Literal["US_MACRO"]
    state: Literal["CLEAR", "ELEVATED", "HIGH_IMPACT_WINDOW", "UNKNOWN"]
    valid_through: datetime


class ScopePriorContext(Evidence):
    symbol: Literal["SPX"] = "SPX"
    session_date: date
    closed_at: datetime
    high: Money = Field(gt=0)
    low: Money = Field(gt=0)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.low > self.high:
            raise ValueError("Ordered observed prior-session range required")
        return self


class ScopeContextInput(OptionRecord):
    # This date is part of the reviewed calendar input, not a weekday inference.
    previous_session: date
    dealer: ScopeDealerContext | None
    moves: ScopeMoveContext | None
    flow: ScopeBiasContext | None
    news: ScopeBiasContext | None
    events: ScopeEventContext | None
    prior: ScopePriorContext | None


class ScopeContextPolicy(OptionRecord):
    version: Literal["scope-context-review-v1"] = "scope-context-review-v1"
    structure: ScopeStructurePolicy
    prior_source: Name
    prior_max_age_seconds: int = Field(gt=0, le=7 * 86400, strict=True)
    dealer_proximity_points: Money = Field(gt=0, le=100)
    dealer_proximity_fraction: Money = Field(gt=0, le=Decimal(".1"))
    boundary_proximity_points: Money = Field(gt=0, le=100)
    boundary_proximity_fraction: Money = Field(gt=0, le=Decimal(".1"))
    prior_proximity_points: Money = Field(gt=0, le=100)
    prior_proximity_fraction: Money = Field(gt=0, le=Decimal(".1"))
    max_expected_move_consumed_fraction: Money = Field(gt=0, le=1)


class ScopeContextObservation(ScopeObservation):
    pattern: ScopePattern | ContextPattern
    parent_pattern: ScopePattern
    matched_level: Money | None = Field(default=None, gt=0)
    notes: tuple[Name, ...] = ()


class ScopeContextScan(OptionRecord):
    version: Literal["scope-context-review-v1"] = "scope-context-review-v1"
    evaluated_at: datetime
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    structure: ScopeStructureScan
    observations: tuple[ScopeContextObservation, ...] = Field(default=(), max_length=90)
    unmatched_context_patterns: tuple[ContextPattern, ...] = CONTEXT_PATTERNS
    issues: tuple[Name, ...] = ()
    authority: Literal[False] = False
    live_enabled: Literal[False] = False


def context_payload_hashes(context):
    """Bind typed current payloads to the five corresponding preflight attestations."""
    context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
    return {
        kind: fingerprint({"version": "scope-context-payload-v1", "kind": kind, "payload": p})
        for kind, p in (
            ("dealer_structure", context.dealer),
            ("options_analytics", context.moves),
            ("options_flow", context.flow),
            ("broad_market_news", context.news),
            ("economic_events", context.events),
        )
        if p is not None
    }


def scan_scope_context(frame, context, policy, *, now):
    from app.options.scope import ScopePreflightInput

    frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
    context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
    policy = ScopeContextPolicy.model_validate(policy.model_dump(warnings=False))
    structure = scan_scope_structure(frame, policy.structure, now=now)
    base = {
        "evaluated_at": structure.evaluated_at,
        "input_hash": fingerprint({"frame": frame, "context": context}),
        "policy_hash": fingerprint(policy),
        "structure": structure,
    }
    if structure.issues:
        return ScopeContextScan(**base, issues=("SCOPE_STRUCTURE_BLOCKED",))
    if policy.structure.preflight.input_basis is not None:
        if any(getattr(context, key) is not None for key in ("dealer", "moves", "flow", "news", "events", "prior")):
            return ScopeContextScan(**base, issues=("PRICE_OPTIONS_CONTEXT_MUST_BE_ABSENT",))
        return ScopeContextScan(**base, observations=tuple(
            ScopeContextObservation(**o.model_dump(), parent_pattern=o.pattern,
                                    notes=("ROBINHOOD_PRICE_OPTIONS_ONLY",))
            for o in structure.observations
        ))
    with localcontext(Context(prec=192)):
        try:
            return _scan(frame, context, policy, base)
        except (ArithmeticError, ValidationError):
            return ScopeContextScan(**base, issues=("CONTEXT_NUMERIC_RANGE",))


def _scan(frame, context, policy, base):
    from zoneinfo import ZoneInfo

    now = base["evaluated_at"]
    evidence = {e.kind: e for e in frame.evidence}
    hashes = context_payload_hashes(context)
    issues = []
    for kind, payload in (
        ("dealer_structure", context.dealer),
        ("options_analytics", context.moves),
        ("options_flow", context.flow),
        ("broad_market_news", context.news),
        ("economic_events", context.events),
    ):
        if payload is None:
            issues.append(kind.upper() + "_PAYLOAD_MISSING")
            continue
        e = evidence[kind]
        if e.payload_hash != hashes[kind] or any(
            getattr(e, field) != getattr(payload, field)
            for field in ("source", "source_at", "received_at", "complete", "entitlement")
        ):
            issues.append(kind.upper() + "_PAYLOAD_BINDING_MISMATCH")
        if kind in {"options_flow", "broad_market_news"} and payload.kind != kind:
            issues.append(kind.upper() + "_KIND_MISMATCH")
        if kind in {"options_flow", "broad_market_news", "economic_events"} and (
            payload.state == "UNKNOWN" or payload.valid_through <= now
        ):
            issues.append(kind.upper() + "_STATE_UNKNOWN_OR_EXPIRED")
    if context.moves is not None and context.moves.expiration != frame.session.session_date:
        issues.append("EXPECTED_MOVE_EXPIRY_MISMATCH")
    prior = context.prior
    if prior is None:
        issues.append("PRIOR_SESSION_PAYLOAD_MISSING")
    elif (
        prior.source != policy.prior_source
        or not prior.complete
        or prior.entitlement != "REALTIME"
        or not _fresh(
            prior.source_at,
            prior.received_at,
            now,
            policy.prior_max_age_seconds,
            policy.structure.preflight.max_receive_lag_seconds,
        )
        or prior.session_date != context.previous_session
        or prior.closed_at.astimezone(ZoneInfo("America/New_York")).date() != prior.session_date
        or context.previous_session >= frame.session.session_date
        or not prior.closed_at <= prior.source_at <= prior.received_at < frame.session.opens_at
    ):
        issues.append("PRIOR_SESSION_BINDING_COVERAGE_OR_CHRONOLOGY")
    if issues:
        return ScopeContextScan(**base, issues=tuple(issues))

    structure = base["structure"]
    spx = next(h for h in frame.histories if h.symbol == "SPX")
    spot = spx.bars[-1].close
    consumed = (
        abs(spot - (structure.opening_high + structure.opening_low) / 2)
        / context.moves.atm_straddle_move
    )
    observations = []
    for original in structure.observations:
        variants = [(original.pattern, None)]
        if original.status == "DETECTED":
            entry = original.geometry.reference
            reversal = original.strategy_class == "REVERSAL"
            nearest = min(context.dealer.nodes, key=lambda n: (abs(n - entry), n))
            at_dealer = abs(nearest - entry) <= max(
                policy.dealer_proximity_points, spot * policy.dealer_proximity_fraction
            )
            boundary = (
                context.moves.reference_spot
                + (1 if original.right == "PUT" else -1) * context.moves.atm_straddle_move
            )
            at_boundary = reversal and abs(entry - boundary) <= max(
                policy.boundary_proximity_points, spot * policy.boundary_proximity_fraction
            )
            if at_dealer:
                variants.append(
                    ("dealer_level_rejection" if reversal else "dealer_level_acceptance", nearest)
                )
            if at_boundary:
                variants.append(("implied_move_boundary_rejection", boundary))
            if at_dealer and at_boundary:
                variants.append(("exhaustion_confluence_reversal", boundary))
            level = prior.high if original.right == "PUT" else prior.low
            if abs(entry - level) <= max(
                policy.prior_proximity_points, spot * policy.prior_proximity_fraction
            ):
                variants.append(
                    ("prior_level_rejection" if reversal else "prior_level_break_retest", level)
                )
        for pattern, level in variants:
            reasons, notes = list(original.reasons), []
            if original.status == "DETECTED":
                opposing = "BEARISH" if original.right == "CALL" else "BULLISH"
                if context.flow.state == opposing:
                    reasons.append("OPTIONS_FLOW_OPPOSES_DIRECTION")
                if context.news.state == opposing:
                    reasons.append("BROAD_MARKET_NEWS_OPPOSES_DIRECTION")
                if context.events.state == "HIGH_IMPACT_WINDOW":
                    reasons.append("HIGH_IMPACT_EVENT_WINDOW")
                elif context.events.state == "ELEVATED":
                    notes.append("ELEVATED_EVENT_RISK_REQUIRES_QUALITY_REVIEW")
                if consumed > policy.max_expected_move_consumed_fraction:
                    reasons.append("EXPECTED_MOVE_ALREADY_CONSUMED")
            observations.append(
                ScopeContextObservation(
                    pattern=pattern,
                    parent_pattern=original.pattern,
                    strategy_class=original.strategy_class,
                    right=original.right,
                    status="BLOCKED"
                    if reasons and original.status == "DETECTED"
                    else original.status,
                    geometry=original.geometry,
                    reasons=tuple(reasons),
                    matched_level=level,
                    notes=tuple(notes),
                )
            )
    matched = {o.pattern for o in observations}
    return ScopeContextScan(
        **base,
        observations=tuple(observations),
        unmatched_context_patterns=tuple(p for p in CONTEXT_PATTERNS if p not in matched),
    )
