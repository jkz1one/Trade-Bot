"""Stored whole-trade floor previews from native cash flows; no execution authority."""

import json
from decimal import ROUND_CEILING, Decimal

from app.options.engine import exact, fingerprint
from app.options.governor import _tick_price
from app.options.lifecycle import TERMINAL, OptionIntent, OptionLedger, OptionVenueSnapshot
from app.options.models import OptionLimits
from app.options.position_outcome import native_position_outcome


@exact
def native_trade_floor(db, entry_client_id, population_id):
    """Preview source 0/10/25% floors, never infer a target touch or a future fill.

    All inputs come from one native snapshot. READY means current arithmetic is
    available, not an enrolled protection policy, current quote or net outcome.
    """
    evidence = native_position_outcome(db, entry_client_id, population_id)
    control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
    config = json.loads(control["config_json"])
    limits = OptionLimits.model_validate(config["limits"])
    ledger = OptionLedger.model_validate_json(control["ledger_json"])
    snapshot = OptionVenueSnapshot.model_validate_json(control["snapshot_json"])
    row = db.execute(
        "SELECT * FROM execution_orders WHERE client_id=?", (entry_client_id,)
    ).fetchone()
    entry = OptionIntent.model_validate_json(row["intent_json"])
    p = ledger.position
    owned = p is not None and p.entry_client_id == entry_client_id
    reasons = set(evidence["reasons"]) - {"POSITION_NOT_VERIFIABLY_CLOSED"}
    if not owned:
        reasons.add("EXACT_ENTRY_NOT_CURRENTLY_OWNED")
    else:
        if p.target_exit_schedule != entry.target_exit_schedule:
            raise ValueError("Trade floor frozen target schedule mismatch")
        if (
            evidence["entry_quantity"] - evidence["exit_quantity"] != p.quantity
            or evidence["settlement_quantity"]
        ):
            raise ValueError("Trade floor remaining ownership mismatch")
    if row["status"] != "FILLED" or evidence["entry_quantity"] != entry.quantity:
        reasons.add("COMPLETE_ORIGINAL_ENTRY_REQUIRED")
    if any(o["order_status"] not in TERMINAL for o in evidence["orders"]):
        reasons.add("UNRESOLVED_POSITION_ORDER")
    remaining = p.quantity if owned else 0
    # At most one charged filled order per remaining whole contract. This does not
    # assume the entire runner exits in one order or reuse fees already paid.
    reserve = remaining * (limits.exit_fee_per_contract + limits.exit_fee_per_order)
    stage = p.target_exit_stage if owned and p.target_exit_schedule is not None else None
    floors = []
    if not reasons:
        original = Decimal(evidence["entry_premium"])
        sales = Decimal(evidence["exit_premium"])
        costs = Decimal(evidence["execution_fees"]) + Decimal(evidence["known_model_cost"])
        for number, fraction in enumerate((Decimal(0), Decimal(".10"), Decimal(".25")), 1):
            protected = original * fraction
            required = max(Decimal(0), original + protected + costs + reserve - sales)
            price = _tick_price(
                required / (remaining * p.contract.multiplier), p.contract, ROUND_CEILING
            )
            floors.append(
                {
                    "reference_stage": number,
                    "protected_return_fraction": str(fraction),
                    "protected_profit": str(protected),
                    "required_remaining_gross_proceeds": str(required),
                    "minimum_exit_fill_price": str(price),
                    "covered_by_recorded_sales": required == 0,
                }
            )
    last_event = db.execute(
        "SELECT sequence,occurred_at FROM execution_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    return {
        "version": "native-target-floor-preview-v1",
        "status": "READY" if not reasons else "INCOMPLETE",
        "population_id": population_id,
        "entry_client_id": entry_client_id,
        "snapshot_id": snapshot.snapshot_id,
        "account_snapshot_at": snapshot.captured_at.isoformat(),
        "revision": last_event["sequence"],
        "last_event_at": last_event["occurred_at"],
        "configuration_hash": fingerprint(config),
        "evidence_hash": fingerprint(evidence),
        "evidence": evidence,
        "remaining_quantity": remaining,
        "reserved_future_exit_fees": str(reserve),
        "exit_fee_assumption": "one-filled-order-per-remaining-contract-v1",
        "stored_target_stage": stage,
        "reference_floors": floors,
        "reached_target_floor": floors[stage - 1] if floors and stage else None,
        "reasons": sorted(reasons),
        "execution_authority": False,
        "execution_ready": False,
        "live_enabled": False,
        "data_host_costs_included": False,
        "note": "Stored arithmetic only; fill-price thresholds before data/host costs, "
        "not current bids, realized returns or guarantees. Future model charges raise required proceeds.",
    }
