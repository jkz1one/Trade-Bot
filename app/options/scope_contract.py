"""Exact-contract Scope research eligibility, without sizing or execution authority."""

from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import fingerprint
from app.options.models import Money, Name, OptionRecord
from app.options.scope import ScopePreflightInput
from app.options.scope_context import ScopeContextInput
from app.options.scope_quality import ScopeQualityPolicy, ScopeQualityScan, scan_scope_quality


class ScopeContractPolicy(OptionRecord):
    version: Literal["scope-contract-profile-v1"] = "scope-contract-profile-v1"
    quality: ScopeQualityPolicy
    minimum_ask: Money = Field(ge=Decimal(".2"), le=5)
    cheap_ceiling: Money = Field(ge=Decimal(".2"), le=5)
    medium_ceiling: Money = Field(ge=Decimal(".2"), le=5)
    maximum_ask: Money = Field(ge=Decimal(".2"), le=5)
    maximum_spread_fraction: Money = Field(gt=0, le=Decimal(".15"))
    minimum_volume: int = Field(strict=True, ge=0, le=1_000_000_000)
    minimum_open_interest: int = Field(strict=True, ge=0, le=1_000_000_000)

    @model_validator(mode="after")
    def ordered_prices(self):
        if not self.minimum_ask <= self.cheap_ceiling <= self.medium_ceiling <= self.maximum_ask:
            raise ValueError("Ordered Scope contract price tiers required")
        return self


class ScopeContractObservation(OptionRecord):
    pattern: Name
    parent_pattern: Name
    right: Literal["CALL", "PUT"]
    profile: Literal["RESPONSIVE", "BALANCED", "CONVEXITY"] | None = None
    target_abs_delta: Money | None = None
    passed: bool = False
    reasons: tuple[Name, ...] = ()


class ScopeContractScan(OptionRecord):
    version: Literal["scope-contract-profile-v1"] = "scope-contract-profile-v1"
    evaluated_at: datetime
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality: ScopeQualityScan
    observations: tuple[ScopeContractObservation, ...] = Field(default=(), max_length=90)
    issues: tuple[Name, ...] = ()
    authority: Literal[False] = False
    live_enabled: Literal[False] = False


def scan_scope_contract(frame, context, policy, *, now):
    """Recompute exact supplied contract gates; never trust a caller's score/profile."""
    frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
    context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
    policy = ScopeContractPolicy.model_validate(policy.model_dump(warnings=False))
    quality = scan_scope_quality(frame, context, policy.quality, now=now)
    base = {
        "evaluated_at": quality.evaluated_at,
        "input_hash": fingerprint({"frame": frame, "context": context}),
        "policy_hash": fingerprint(policy),
        "quality": quality,
    }
    if quality.issues:
        return ScopeContractScan(**base, issues=("SCOPE_QUALITY_BLOCKED",))
    metadata, quote = frame.metadata, frame.quote
    common = []
    if metadata.greek_provenance != "OBSERVED" or metadata.delta is None or metadata.delta == 0:
        common.append("OBSERVED_NONZERO_DELTA_REQUIRED")
    if metadata.volume is None or metadata.volume < policy.minimum_volume:
        common.append("CONTRACT_VOLUME_UNAVAILABLE_OR_LOW")
    if metadata.open_interest is None or metadata.open_interest < policy.minimum_open_interest:
        common.append("CONTRACT_OPEN_INTEREST_UNAVAILABLE_OR_LOW")
    if not policy.minimum_ask <= quote.ask <= policy.maximum_ask:
        common.append("CONTRACT_ASK_OUTSIDE_POLICY")
    with localcontext(Context(prec=192)):
        # Compare exact products; no rounded spread can rescue a boundary breach.
        if (quote.ask - quote.bid) * 2 > policy.maximum_spread_fraction * (quote.ask + quote.bid):
            common.append("CONTRACT_SPREAD_TOO_WIDE")
        observations = []
        for reviewed in quality.observations:
            o = reviewed.observation
            reasons = list(common)
            profile = None
            if o.right != metadata.instrument.contract.right:
                reasons.append("CONTRACT_DIRECTION_MISMATCH")
            if not reviewed.passed:
                reasons.append("SCOPE_QUALITY_BLOCKED")
            if not reasons:
                delta = abs(metadata.delta)
                g = o.geometry
                beyond_first = (
                    metadata.instrument.contract.strike > g.target_one
                    if o.right == "CALL"
                    else metadata.instrument.contract.strike < g.target_one
                )
                if (o.strategy_class == "REVERSAL" and delta >= Decimal(".35")) or delta >= Decimal(
                    ".48"
                ):
                    profile = "RESPONSIVE"
                elif (
                    quote.ask <= policy.cheap_ceiling
                    and reviewed.score >= policy.quality.convexity_score
                    and (beyond_first or delta < Decimal(".25"))
                ):
                    profile = "CONVEXITY"
                elif quote.ask <= policy.medium_ceiling:
                    profile = "BALANCED"
                else:
                    profile = "RESPONSIVE"
                if profile == "CONVEXITY" and not reviewed.complete_path_proven:
                    reasons.append("CONVEXITY_COMPLETE_PATH_UNPROVEN")
            observations.append(
                ScopeContractObservation(
                    pattern=o.pattern,
                    parent_pattern=o.parent_pattern,
                    right=o.right,
                    profile=profile,
                    target_abs_delta={
                        "RESPONSIVE": ".50",
                        "BALANCED": ".32",
                        "CONVEXITY": ".18",
                    }.get(profile),
                    passed=not reasons,
                    reasons=tuple(reasons),
                )
            )
    return ScopeContractScan(**base, observations=tuple(observations))
