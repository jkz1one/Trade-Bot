"""Frozen Scope debit envelope; native sizing remains in the common governor."""

from decimal import ROUND_FLOOR, Context, Decimal, localcontext
from typing import Literal

from pydantic import Field

from app.options.degen import _metric
from app.options.models import Money, Name, OptionRecord
from app.options.scope_quality import ScopePathLevel, _known_path
from app.options.scope_structure import ScopeGeometry


class ScopeAdmissionPolicy(OptionRecord):
    version: Literal["scope-owned-admission-review-v1"] = "scope-owned-admission-review-v1"
    max_entry_debit: Money = Field(gt=0, le=500)


class ScopeEntryPathReview(OptionRecord):
    version: Literal["scope-current-entry-path-v1"] = "scope-current-entry-path-v1"
    geometry: ScopeGeometry
    reference: Money = Field(gt=0)
    minimum_first_target_r: Money = Field(ge=Decimal("1.5"), le=5)
    first_target_r: Money = Field(ge=0)
    potential_obstructions: tuple[ScopePathLevel, ...] = Field(max_length=208)
    complete_path_proven: Literal[False] = False
    passed: bool
    reasons: tuple[Name, ...]
    authority: Literal[False] = False
    live_enabled: Literal[False] = False


def _review_entry_path(frame, context, geometry, policy, underlying, *, now):
    """Only after fresh armed coverage and common-governor quote/stop validation.

    The conservative directional quote side is a geometry reference, not an SPX
    fill or an option-return estimate. No caller-provided path verdict is accepted.
    """
    g = ScopeGeometry.model_validate(geometry)
    sign = 1 if g.right == "CALL" else -1
    spot = underlying.ask if sign == 1 else underlying.bid
    with localcontext(Context(prec=192)):
        risk = (spot - g.invalidation) * sign
        reward = (g.target_one - spot) * sign
        if risk <= 0 or reward <= 0:
            raise ValueError("Current Scope reference must be between locked stop and target")
        path = _known_path(frame, context, g, policy, spot, now)
        reasons = []
        if reward < policy.minimum_first_target_r * risk:
            reasons.append("SCOPE_CURRENT_FIRST_TARGET_R_TOO_LOW")
        if any(p.at_or_before_first_target for p in path):
            reasons.append("SCOPE_CURRENT_KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE")
        return ScopeEntryPathReview(
            geometry=g,
            reference=spot,
            minimum_first_target_r=policy.minimum_first_target_r,
            first_target_r=_metric(reward / risk, ROUND_FLOOR),
            potential_obstructions=path,
            passed=not reasons,
            reasons=tuple(reasons),
        )


def scope_quantity_cap(ask):
    """Approved V2 ask-price ceilings; the common governor may size lower."""
    if not isinstance(ask, Decimal) or not ask.is_finite() or not Decimal(".2") <= ask <= 5:
        raise ValueError("Scope sizing requires an executable ask from .20 through 5.00")
    for ceiling, quantity in (("1.25", 4), ("1.65", 3), ("2.50", 2), ("5", 1)):
        if ask <= Decimal(ceiling):
            return quantity
    raise AssertionError("Validated Scope ask must belong to a quantity tier")


def reject_unlinked_scope_entry(db, proposal):
    """An enrolled research book cannot route entries around its missing native linkage.

    Check at both preparation and dispatch. HOLD and owned closes must remain
    available, including recovery from a legacy/inconsistent journal state.
    """
    from app.execution.engine import ExecutionBlocked

    if proposal.action != "OPEN_LONG":
        return
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_option_scope_watch_policy'"
    ).fetchone():
        # Fail closed even for an incomplete/malformed enrollment table. Current
        # enrollment is transactional, so an empty table is not an opt-out.
        raise ExecutionBlocked("SCOPE_NATIVE_EXECUTION_NOT_ENROLLED")
