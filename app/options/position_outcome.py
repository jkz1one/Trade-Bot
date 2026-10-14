"""Stored native position cash flows and model costs. No watch linkage or trade authority."""

import json
from decimal import Decimal

from app.options.attribution import decision_attribution, order_attribution
from app.options.engine import exact
from app.options.lifecycle import (
    TERMINAL,
    OptionExecutionPolicy,
    OptionIntent,
    OptionObservation,
    OptionReceipt,
)
from app.options.models import OptionLimits


def _bounded(db, table, limit=2000):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return []
    rows = db.execute(f"SELECT * FROM {table} LIMIT ?", (limit + 1,)).fetchall()
    if len(rows) > limit:
        raise ValueError("Position outcome evidence capacity exceeded")
    return rows


@exact
def native_position_outcome(db, entry_client_id, population_id):
    """Read within the caller's existing journal snapshot; never infer absent exit links.

    This supplies evidence for future Scope loss controls. It does not enroll a
    watch, import a caller's P&L, reset limits or authorize execution.
    """
    control = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
    config = json.loads(control[0])
    limits = OptionLimits.model_validate(config["limits"])
    if config["schema"] != "option-paper-execution-v1" or limits.population_id != population_id:
        raise ValueError("Frozen options population identity mismatch")
    policy = OptionExecutionPolicy.model_validate(config["policy"])
    rows = _bounded(db, "execution_orders")
    entries = {r["client_id"]: r for r in rows}
    row = entries.get(entry_client_id)
    if row is None:
        raise ValueError("Exact native entry required")
    entry = OptionIntent.model_validate_json(row["intent_json"])
    if entry.side != "BUY":
        raise ValueError("Native outcome requires a buy entry")
    for fill in _bounded(db, "execution_fills"):
        if fill["client_id"] not in entries:
            raise ValueError("Orphan native position fill")
    buy_ids = {
        r["client_id"]
        for r in rows
        if OptionIntent.model_validate_json(r["intent_json"]).side == "BUY"
    }
    decisions = {r["source_key"]: r for r in _bounded(db, "execution_option_decisions")}
    cycles = {r["cycle_key"]: r for r in _bounded(db, "execution_option_opportunities")}

    def outcome(key):
        cycle = cycles.get(key)
        if cycle and cycle["result_json"] is not None:
            return json.loads(cycle["result_json"])
        decision = decisions.get(key)
        return json.loads(decision["inputs_json"]) if decision else {}

    # Paid advice can exist without an order (MAINTAIN/TIGHTEN/rejected plans).
    # Check retained results even when a damaged journal has lost the call row.
    for key in sorted(set(decisions) | set(cycles)):
        evidence = outcome(key)
        if "entry_result" in evidence or "position_result" in evidence:
            decision_attribution(db, key, evidence, policy)
    reasons, linked, buy_keys = [], [], set()
    for candidate in sorted(rows, key=lambda r: r["client_id"]):
        intent = OptionIntent.model_validate_json(candidate["intent_json"])
        attr = order_attribution(db, candidate)
        if intent.side == "BUY":
            buy_keys.add(intent.source_key)
        if candidate["client_id"] == entry_client_id or attr["entry_client_id"] == entry_client_id:
            # Reuse full decision/proposal/approval checks, not just matching IDs.
            decision_attribution(db, intent.source_key, outcome(intent.source_key), policy)
            if intent.instrument != entry.instrument:
                raise ValueError("Position outcome instrument mismatch")
            if candidate["client_id"] != entry_client_id and intent.side != "SELL":
                raise ValueError("Position outcome exit side mismatch")
            linked.append((candidate, intent, attr))
        elif (
            intent.side == "SELL"
            and attr["entry_client_id"] is None
            and intent.instrument == entry.instrument
            and intent.prepared_at >= entry.prepared_at
        ):
            reasons.append("UNLINKED_SAME_INSTRUMENT_EXIT")
    receipts = []
    for r in _bounded(db, "execution_option_receipts"):
        receipt = OptionReceipt.model_validate_json(r["payload"])
        if (
            receipt.contract == entry.instrument.contract
            and receipt.occurred_at >= entry.prepared_at
        ):
            receipts.append(receipt.receipt_id)
    if receipts:
        # Current native settlement receipts identify a contract, not a unique entry.
        reasons.append("SETTLEMENT_ENTRY_LINK_UNPROVEN")
    calls, unallocated = [], []
    for call in sorted(_bounded(db, "execution_model_calls"), key=lambda r: r["source_key"]):
        key = call["source_key"]
        attr = decision_attribution(db, key, outcome(key), policy)
        if key == entry.source_key or attr.entry_client_id == entry_client_id:
            if key == entry.source_key and attr.role == "MANAGEMENT":
                raise ValueError("Entry call has management lineage")
            calls.append(attr)
        elif key not in buy_keys and attr.entry_client_id not in buy_ids:
            unallocated.append(attr)
    if unallocated:
        reasons.append("ACCOUNT_MODEL_COST_LINK_UNPROVEN")
    if any(c.model_cost is None for c in calls):
        reasons.append("POSITION_MODEL_COST_UNKNOWN")
    entry_quantity = exit_quantity = 0
    entry_cash = exit_cash = fees = Decimal(0)
    fill_ids, exit_times, entry_times = [], [], []
    for native, intent, _ in linked:
        obs = (
            OptionObservation.model_validate_json(native["observation_json"])
            if native["observation_json"]
            else None
        )
        for fill in obs.fills if obs else ():
            if fill.fill_id in fill_ids:
                raise ValueError("Duplicate position outcome fill")
            fill_ids.append(fill.fill_id)
            fees += fill.fee
            gross = fill.quantity * fill.price * entry.instrument.contract.multiplier
            if intent.side == "BUY":
                entry_quantity += fill.quantity
                entry_cash += gross
                entry_times.append(fill.occurred_at)
            else:
                exit_quantity += fill.quantity
                exit_cash += gross
                exit_times.append(fill.occurred_at)
    if exit_quantity > entry_quantity or (
        exit_times and (not entry_times or min(exit_times) < max(entry_times))
    ):
        raise ValueError("Position outcome fill chronology or quantity mismatch")
    terminal = all(r["status"] in TERMINAL for r, _, _ in linked)
    closed = terminal and entry_quantity > 0 and entry_quantity == exit_quantity and not receipts
    if not closed:
        reasons.append("POSITION_NOT_VERIFIABLY_CLOSED")
    known_cost = sum((c.model_cost for c in calls if c.model_cost is not None), Decimal(0))
    gross = exit_cash - entry_cash if closed else None
    net = gross - fees - known_cost if closed and not reasons else None
    return {
        "population_id": limits.population_id,
        "entry_client_id": entry_client_id,
        "source_key": entry.source_key,
        "instrument": entry.instrument.model_dump(mode="json"),
        "status": "COMPLETE" if net is not None else "INCOMPLETE",
        "outcome": None if net is None else "LOSS" if net < 0 else "WIN" if net > 0 else "FLAT",
        "closed_at": max(exit_times).isoformat() if closed else None,
        "entry_quantity": entry_quantity,
        "exit_quantity": exit_quantity,
        "entry_premium": str(entry_cash),
        "exit_premium": str(exit_cash),
        "execution_fees": str(fees),
        "gross_realized": str(gross) if gross is not None else None,
        "known_model_cost": str(known_cost),
        "net_after_known_execution_and_model_costs": str(net) if net is not None else None,
        "model_calls": [c.model_dump(mode="json") for c in calls],
        "unallocated_account_calls": [c.model_dump(mode="json") for c in unallocated],
        "orders": [a for _, _, a in linked],
        "fill_ids": fill_ids,
        "unlinked_settlement_receipt_ids": sorted(receipts),
        "reasons": sorted(set(reasons)),
        "execution_authority": False,
        "live_enabled": False,
        "data_host_costs_included": False,
    }
