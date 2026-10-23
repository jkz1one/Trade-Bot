"""Stored native position cash flows and model costs. No watch linkage or trade authority."""

import json
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from app.options.accounting import apply_fill, apply_receipt
from app.options.attribution import decision_attribution, order_attribution
from app.options.engine import exact, fingerprint
from app.options.entry_lineage import outcome_snapshot
from app.options.lifecycle import (
    TERMINAL,
    OptionExecutionPolicy,
    OptionIntent,
    OptionLedger,
    OptionObservation,
    OptionReceipt,
    OptionVenueSnapshot,
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


def _settlement_links(db, rows, receipts, policy):
    """Replay complete native accounting; contract equality alone never assigns a receipt."""
    control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
    recorded = OptionLedger.model_validate_json(control["ledger_json"])
    snapshot = (
        OptionVenueSnapshot.model_validate_json(control["snapshot_json"])
        if control["snapshot_json"]
        else None
    )
    if snapshot is None:
        raise ValueError("Position outcome requires a reconciled native snapshot")
    config = json.loads(control["config_json"])
    limits = OptionLimits.model_validate(config["limits"])
    if (
        not snapshot.complete
        or snapshot.underlying_exposures
        or snapshot.population_id != limits.population_id
        or snapshot.account_id != limits.account_id
        or snapshot.venue_id != config["venue_id"]
    ):
        raise ValueError("Settlement snapshot identity or completeness mismatch")
    if len({r.receipt_id for r in snapshot.receipts}) != len(snapshot.receipts):
        raise ValueError("Duplicate settlement snapshot receipt")
    if {r.receipt_id: r for r in receipts} != {r.receipt_id: r for r in snapshot.receipts}:
        raise ValueError("Settlement receipt snapshot coverage mismatch")
    events = []
    for row in rows:
        intent = OptionIntent.model_validate_json(row["intent_json"])
        order_attribution(db, row)
        obs = (
            OptionObservation.model_validate_json(row["observation_json"])
            if row["observation_json"]
            else None
        )
        for fill in obs.fills if obs else ():
            events.append((fill.sequence, fill.occurred_at, "FILL", (intent, fill)))
    observed = {(event[3][0].client_id, event[3][1].fill_id): event[3][1] for event in events}
    snapshot_fills = [(o.client_id, f) for o in snapshot.orders for f in o.fills]
    if len({(key, f.fill_id) for key, f in snapshot_fills}) != len(snapshot_fills) or observed != {
        (key, f.fill_id): f for key, f in snapshot_fills
    }:
        raise ValueError("Settlement snapshot fill coverage mismatch")
    for receipt in receipts:
        events.append((receipt.sequence, receipt.occurred_at, "RECEIPT", receipt))
    if policy.mixed_owner is not None:
        from app.mixed.native_outcome import stock_events

        events.extend(stock_events(db, snapshot))
    ordered = sorted(events, key=lambda event: event[0])
    if (
        [e[0] for e in ordered] != list(range(1, len(ordered) + 1))
        or any(a[1] > b[1] for a, b in pairwise(ordered))
        or any(e[1] > snapshot.captured_at for e in ordered)
    ):
        raise ValueError("Settlement event sequence or time mismatch")
    state = OptionLedger(cash=policy.capital, high_watermark=policy.capital)
    if policy.mixed_owner is not None:
        from app.mixed.accounting import _apply_stock, _merge, _option_part
        from app.mixed.models import MixedLedger

        state = MixedLedger.model_validate(state.model_dump())
    links = {}
    for _, _, kind, event in ordered:
        if kind == "FILL":
            intent, fill = event
            if (
                intent.side == "SELL"
                and intent.closing_entry_client_id is not None
                and (
                    state.position is None
                    or state.position.entry_client_id != intent.closing_entry_client_id
                )
            ):
                raise ValueError("Settlement replay closing entry mismatch")
            if policy.mixed_owner is not None:
                if state.stock_position is not None:
                    raise ValueError("MIXED_EXISTING_STOCK_POSITION")
                state = _merge(state, apply_fill(_option_part(state), intent, fill))
            else:
                state = apply_fill(state, intent, fill)
        elif kind == "STOCK_FILL":
            state = _apply_stock(state, *event)
        else:
            entry_id = state.position.entry_client_id if state.position else None
            state = (
                _merge(state, apply_receipt(_option_part(state), event))
                if policy.mixed_owner is not None
                else apply_receipt(state, event)
            )
            if event.kind != "FUNDS_SETTLED":
                links[event.receipt_id] = entry_id
    fields = ("cash", "settled_cash", "realized_pnl", "fees_paid", "daily_net_pnl")
    if any(getattr(state, key) != getattr(recorded, key) for key in fields):
        raise ValueError("Settlement replay ledger mismatch")
    if state.cash != snapshot.cash or state.settled_cash != snapshot.settled_cash:
        raise ValueError("Settlement replay snapshot cash mismatch")
    for position in (recorded.position, snapshot.position):
        if (state.position is None) != (position is None) or (
            state.position is not None
            and any(
                getattr(state.position, key) != getattr(position, key)
                for key in ("entry_client_id", "contract", "quantity", "lots")
            )
        ):
            raise ValueError("Settlement replay owned position mismatch")
    if policy.mixed_owner is not None:
        from app.mixed.stock_models import StockPosition

        saved = db.execute(
            "SELECT position_json FROM execution_mixed_control WHERE id=1"
        ).fetchone()[0]
        held = StockPosition.model_validate_json(saved) if saved else None
        if state.stock_position != snapshot.stock_position or state.stock_position != held:
            raise ValueError("MIXED_STOCK_OUTCOME_POSITION_MISMATCH")
    return links


@exact
@outcome_snapshot
def native_position_outcome(db, entry_client_id, population_id):
    """Read within the caller's existing journal snapshot; never infer absent exit links.

    Scope and other enrolled family loss controls consume this full-cost evidence.
    It does not import caller P&L, reset limits or authorize execution.
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
    evidence_cache, attribution_cache = {}, {}

    def outcome(key):
        if key in evidence_cache:
            return evidence_cache[key]
        cycle = cycles.get(key)
        if cycle and cycle["result_json"] is not None:
            evidence = json.loads(cycle["result_json"])
        else:
            decision = decisions.get(key)
            evidence = json.loads(decision["inputs_json"]) if decision else {}
        evidence_cache[key] = evidence
        return evidence

    def attribute(key):
        # This function does no writes. Reuse complete validation only within this
        # one reconstruction and its caller's transaction, never across revisions.
        if key not in attribution_cache:
            attribution_cache[key] = decision_attribution(db, key, outcome(key), policy)
        return attribution_cache[key]

    # Paid advice can exist without an order (MAINTAIN/TIGHTEN/rejected plans).
    # Check retained results even when a damaged journal has lost the call row.
    for key in sorted(set(decisions) | set(cycles)):
        evidence = outcome(key)
        if "entry_result" in evidence or "position_result" in evidence:
            attribute(key)
    reasons, linked, buy_keys = [], [], set()
    for candidate in sorted(rows, key=lambda r: r["client_id"]):
        intent = OptionIntent.model_validate_json(candidate["intent_json"])
        attr = order_attribution(db, candidate)
        if intent.side == "BUY":
            buy_keys.add(intent.source_key)
        if candidate["client_id"] == entry_client_id or attr["entry_client_id"] == entry_client_id:
            # Reuse full decision/proposal/approval checks, not just matching IDs.
            attribute(intent.source_key)
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
    receipt_rows = _bounded(db, "execution_option_receipts")
    native_receipts = []
    for r in receipt_rows:
        receipt = OptionReceipt.model_validate_json(r["payload"])
        if receipt.receipt_id != r["receipt_id"]:
            raise ValueError("Settlement receipt identity mismatch")
        native_receipts.append(receipt)
    settlement_links = _settlement_links(db, rows, native_receipts, policy)
    receipts = [r for r in native_receipts if settlement_links.get(r.receipt_id) == entry_client_id]
    calls, unallocated = [], []
    for call in sorted(_bounded(db, "execution_model_calls"), key=lambda r: r["source_key"]):
        key = call["source_key"]
        attr = attribute(key)
        if key == entry.source_key or attr.entry_client_id == entry_client_id:
            if key == entry.source_key and attr.role == "MANAGEMENT":
                raise ValueError("Entry call has management lineage")
            calls.append(attr)
            cycle = cycles.get(key)
            if (
                attr.role == "MANAGEMENT"
                and cycle is not None
                and cycle["status"] == "STARTED"
                and policy.scope_arbitration == "shared-scope-entry-v1"
            ):
                strategy = json.loads(
                    db.execute(
                        "SELECT policy_json FROM execution_option_strategy WHERE id=1"
                    ).fetchone()[0]
                )
                if "scope_replay" in strategy:
                    from app.options.scope_replay_enrollment import validate_stored

                    validate_stored(strategy)
                    # This new cohort freezes complete decision attribution in its
                    # loss record. A charged response can still be awaiting native
                    # application after a protective fill; do not freeze it early.
                    reasons.append("POSITION_MODEL_DECISION_PENDING")
        elif key not in buy_keys and attr.entry_client_id not in buy_ids:
            unallocated.append(attr)
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
    settlement_quantity = sum(r.quantity for r in receipts)
    settlement_cash = sum((r.cash_change for r in receipts), Decimal(0))
    if exit_quantity + settlement_quantity > entry_quantity:
        raise ValueError("Settlement and exit quantity exceed native entry")
    terminal = all(r["status"] in TERMINAL for r, _, _ in linked)
    closed = (
        terminal and entry_quantity > 0 and entry_quantity == exit_quantity + settlement_quantity
    )
    if not closed:
        reasons.append("POSITION_NOT_VERIFIABLY_CLOSED")
    closed_at = max([*exit_times, *(r.occurred_at for r in receipts)]) if closed else None
    if unallocated and (
        closed_at is None
        or any(not _later_entry_call(db, c, closed_at, policy) for c in unallocated)
    ):
        reasons.append("ACCOUNT_MODEL_COST_LINK_UNPROVEN")
    known_cost = sum((c.model_cost for c in calls if c.model_cost is not None), Decimal(0))
    gross = exit_cash + settlement_cash - entry_cash if closed else None
    net = gross - fees - known_cost if closed and not reasons else None
    from app.options.entry_lineage import entry_lineage

    lineage = entry_lineage(db, entry_client_id)
    return {
        **({"entry_lineage": lineage.model_dump(mode="json")} if lineage is not None else {}),
        "population_id": limits.population_id,
        "entry_client_id": entry_client_id,
        "source_key": entry.source_key,
        "instrument": entry.instrument.model_dump(mode="json"),
        "status": "COMPLETE" if net is not None else "INCOMPLETE",
        "outcome": None if net is None else "LOSS" if net < 0 else "WIN" if net > 0 else "FLAT",
        "closed_at": closed_at.isoformat() if closed_at else None,
        "entry_quantity": entry_quantity,
        "exit_quantity": exit_quantity,
        "entry_premium": str(entry_cash),
        "exit_premium": str(exit_cash),
        "settlement_quantity": settlement_quantity,
        "settlement_cash": str(settlement_cash),
        "settlements": [
            r.model_dump(mode="json") | {"entry_client_id": entry_client_id} for r in receipts
        ],
        "execution_fees": str(fees),
        "gross_realized": str(gross) if gross is not None else None,
        "known_model_cost": str(known_cost),
        "net_after_known_execution_and_model_costs": str(net) if net is not None else None,
        "model_calls": [c.model_dump(mode="json") for c in calls],
        "unallocated_account_calls": [c.model_dump(mode="json") for c in unallocated],
        "orders": [a for _, _, a in linked],
        "fill_ids": fill_ids,
        "unlinked_settlement_receipt_ids": [],
        "reasons": sorted(set(reasons)),
        "execution_authority": False,
        "live_enabled": False,
        "data_host_costs_included": False,
    }


def _later_entry_call(db, attribution, closed_at, policy):
    """A proven later flat-account entry call cannot belong to this closed holding.

    Only explicitly frozen native loss or series contracts opt in. Keep the call visible as
    an unallocated account charge; never waive usage, cost or global admission gates.
    Legacy outcomes and uncertain/management/overlapping calls remain unchanged.
    """
    from app.options.entry_judgment import EntryRequest
    from app.options.scope_replay_enrollment import (
        ScopeCarrySeriesEnrollment,
        ScopeSeriesEnrollment,
        validate_stored,
    )

    if attribution.role != "ENTRY":
        return False
    strategy = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    if strategy is None:
        return False
    config = json.loads(strategy[0])
    if policy.loss_control and policy.loss_control.entry_cost_attribution is not None:
        if config.get("replay_model") is not None or config.get("entry_model") is None:
            return False
        enrolled = db.execute(
            "SELECT policy_json FROM execution_option_loss_control WHERE id=1"
        ).fetchone()
        if enrolled is None or json.loads(enrolled[0]) != policy.loss_control.model_dump(
            mode="json"
        ):
            raise ValueError("Frozen later-entry attribution policy mismatch")
    else:
        if config.get("scope_replay", {}).get("version") not in {
            "scope-native-series-model-v1",
            "scope-carry-series-model-v1",
        }:
            return False
        if type(validate_stored(config)) not in (ScopeSeriesEnrollment, ScopeCarrySeriesEnrollment):
            return False
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
        (attribution.source_key,),
    ).fetchone()
    evidence = json.loads(row[0]) if row and row[0] else {}
    if "entry_request" not in evidence:
        return False
    request = EntryRequest.model_validate(evidence["entry_request"])
    p = request.packet
    call = db.execute(
        "SELECT started_at FROM execution_model_calls WHERE source_key=?",
        (attribution.source_key,),
    ).fetchone()
    return (
        call is not None
        and attribution.packet_hash == fingerprint(p)
        and p.account.position is None
        and p.account.complete
        and p.account.reconciled
        and p.account.captured_at > closed_at
        and closed_at < p.as_of <= datetime.fromisoformat(call[0])
    )
