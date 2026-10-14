"""Frozen Scope debit envelope; native sizing remains in the common governor."""

from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.options.models import Money, OptionRecord


class ScopeAdmissionPolicy(OptionRecord):
    version: Literal["scope-owned-admission-review-v1"] = "scope-owned-admission-review-v1"
    max_entry_debit: Money = Field(gt=0, le=500)


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
