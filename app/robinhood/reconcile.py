from __future__ import annotations

from decimal import Decimal

from app.robinhood.models import ReconciliationResult, RobinhoodTruth
from app.storage.repository import Repository


def reconcile_truth(repo: Repository, truth: RobinhoodTruth) -> ReconciliationResult:
    reasons: list[str] = []
    local = repo.load_open_position()

    if truth.portfolio.unsupported_value != 0:
        reasons.append("UNSUPPORTED_ASSET_VALUE_PRESENT")
    if len(truth.positions) > 1:
        reasons.append("MULTIPLE_BROKER_POSITIONS")
    if truth.working_orders:
        reasons.append("UNTRACKED_WORKING_ORDERS")

    broker = truth.positions[0] if len(truth.positions) == 1 else None
    if broker is not None and (broker.quantity <= 0 or broker.type != "long"):
        reasons.append("NON_LONG_BROKER_POSITION")

    if local is None and broker is not None:
        reasons.append("BROKER_POSITION_NOT_OWNED_LOCALLY")
    elif local is not None and broker is None:
        reasons.append("LOCAL_POSITION_MISSING_AT_BROKER")
    elif local is not None and broker is not None:
        if local.symbol != broker.symbol:
            reasons.append("POSITION_SYMBOL_MISMATCH")
        if abs(local.quantity - broker.quantity) > Decimal("0.000001"):
            reasons.append("POSITION_QUANTITY_MISMATCH")

    return ReconciliationResult(reconciled=not reasons, reasons=reasons)
