"""Source-bound Scope management plans from owned admission; no execution authority."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import fingerprint
from app.options.lifecycle import EntryPremiumProtection, TargetExitSchedule, TargetExitStep
from app.options.models import Count, Money, Name, OptionAdmission, OptionRecord
from app.options.scope_contract import ScopeContractObservation, ScopeContractScan
from app.options.scope_structure import ScopeGeometry

SOURCE_ESTIMATES = {
    "RESPONSIVE": Decimal(".35"),
    "BALANCED": Decimal(".45"),
    "CONVEXITY": Decimal(".60"),
}
ALLOCATIONS = {1: (0, 1, 0, 0), 2: (1, 0, 0, 1), 3: (1, 1, 0, 1), 4: (1, 1, 1, 1)}
MISSING_THIRD = "SCOPE_THIRD_TARGET_UNSPECIFIED"


class ScopeManagementPolicy(OptionRecord):
    version: Literal["scope-management-plan-v1", "scope-management-plan-v2"] = (
        "scope-management-plan-v1"
    )
    # Explicit enrollment values, bounded by source estimates and then by the owner.
    responsive_loss_fraction: Money = Field(gt=0, le=Decimal(".35"))
    balanced_loss_fraction: Money = Field(gt=0, le=Decimal(".45"))
    convexity_loss_fraction: Money = Field(gt=0, le=Decimal(".60"))

    def fraction(self, profile):
        return getattr(self, profile.lower() + "_loss_fraction")


def _schedule(geometry, quantity, version="scope-management-plan-v1"):
    if quantity == 4:
        return None
    allocation = ALLOCATIONS[quantity]
    if version == "scope-management-plan-v2":
        return TargetExitSchedule(
            version="frozen-target-milestones-v2",
            entry_quantity=quantity,
            steps=(
                TargetExitStep(
                    underlying_price=geometry.target_one,
                    quantity=allocation[0],
                    tighten_to_entry="fill-weighted-underlying-v1",
                ),
                TargetExitStep(
                    underlying_price=geometry.target_two,
                    quantity=allocation[1],
                    tighten_underlying_to=geometry.target_one,
                ),
            ),
        )
    return TargetExitSchedule(
        entry_quantity=quantity,
        steps=tuple(
            TargetExitStep(underlying_price=price, quantity=count)
            for price, count in zip(
                (geometry.target_one, geometry.target_two), allocation[:2], strict=True
            )
            if count
        ),
    )


class ScopeManagementReview(OptionRecord):
    version: Literal["scope-management-plan-v1", "scope-management-plan-v2"] = (
        "scope-management-plan-v1"
    )
    reference_commit: Literal["f9eaf2c1b5d13dca287ee7138126883065b00395"] = (
        "f9eaf2c1b5d13dca287ee7138126883065b00395"
    )
    evaluated_at: datetime
    valid_until: datetime
    contract_id: Name
    admission_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_scan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_observation: ScopeContractObservation
    geometry: ScopeGeometry
    policy: ScopeManagementPolicy
    owner_maximum_loss_fraction: Money = Field(gt=0, lt=1)
    source_estimated_premium_stop_fraction: Money = Field(gt=0, lt=1)
    entry_premium_protection: EntryPremiumProtection
    admitted_quantity: int = Field(strict=True, ge=1, le=4)
    scale_profile: Literal["BALANCED"] = "BALANCED"
    # T1, T2, T3, runner. Keep unavailable T3 distinct from the runner.
    source_allocation: tuple[Count, Count, Count, Count]
    target_exit_schedule: TargetExitSchedule | None
    passed: bool
    reasons: tuple[Literal["SCOPE_THIRD_TARGET_UNSPECIFIED"], ...]
    native_execution_ready: Literal[False] = False
    authority: Literal[False] = False
    live_enabled: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        observation = self.contract_observation
        if (
            not observation.passed
            or observation.reasons
            or observation.profile not in {"RESPONSIVE", "BALANCED"}
            or observation.right != self.geometry.right
        ):
            raise ValueError(
                "Eligible exact Scope contract profile required; convexity remains blocked"
            )
        fraction = min(self.owner_maximum_loss_fraction, self.policy.fraction(observation.profile))
        expected_reasons = (MISSING_THIRD,) if self.admitted_quantity == 4 else ()
        if (
            self.valid_until <= self.evaluated_at
            or self.version != self.policy.version
            or self.source_estimated_premium_stop_fraction != SOURCE_ESTIMATES[observation.profile]
            or self.entry_premium_protection.maximum_loss_fraction != fraction
            or self.source_allocation != ALLOCATIONS[self.admitted_quantity]
            or self.target_exit_schedule
            != _schedule(self.geometry, self.admitted_quantity, self.version)
            or self.reasons != expected_reasons
            or self.passed != (not expected_reasons)
        ):
            raise ValueError(
                "Scope management must retain exact source allocations and tighter protection"
            )
        return self


def review_scope_management(admission, geometry, choice, scan, policy, owner_fraction):
    """Called only after the owned book refreshes arming, contract and common admission."""
    admission = OptionAdmission.model_validate(admission.model_dump(warnings=False))
    geometry = ScopeGeometry.model_validate(geometry)
    scan = ScopeContractScan.model_validate(scan)
    policy = ScopeManagementPolicy.model_validate(policy.model_dump(warnings=False))
    observations = [
        o for o in scan.observations if all(getattr(o, k) == v for k, v in choice.items())
    ]
    if (
        admission.outcome != "APPROVED"
        or admission.action != "OPEN_LONG"
        or admission.valid_until is None
        or scan.issues
        or scan.evaluated_at != admission.approved_at
        or len(observations) != 1
    ):
        raise ValueError("Fresh owned Scope admission and selected contract review required")
    observation = observations[0]
    if not observation.passed or observation.profile not in {"RESPONSIVE", "BALANCED"}:
        raise ValueError("Eligible exact Scope profile required")
    quantity = admission.quantity
    if quantity not in ALLOCATIONS:
        raise ValueError("Scope quantity must come from the bounded owned admission")
    reasons = (MISSING_THIRD,) if quantity == 4 else ()
    return ScopeManagementReview(
        version=policy.version,
        evaluated_at=admission.approved_at,
        valid_until=admission.valid_until,
        contract_id=admission.contract_id,
        admission_hash=fingerprint(admission),
        contract_scan_hash=fingerprint(scan),
        contract_observation=observation,
        geometry=geometry,
        policy=policy,
        owner_maximum_loss_fraction=owner_fraction,
        source_estimated_premium_stop_fraction=SOURCE_ESTIMATES[observation.profile],
        entry_premium_protection=EntryPremiumProtection(
            maximum_loss_fraction=min(owner_fraction, policy.fraction(observation.profile))
        ),
        admitted_quantity=quantity,
        source_allocation=ALLOCATIONS[quantity],
        target_exit_schedule=_schedule(geometry, quantity, policy.version),
        passed=not reasons,
        reasons=reasons,
    )
