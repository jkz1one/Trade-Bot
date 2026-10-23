"""Stored mixed full-cost loss evidence, with no order or model authority."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.mixed.accounting import _apply_stock, _merge, _option_part
from app.mixed.models import MixedLedger
from app.mixed.native_store import verify_order
from app.mixed.stock_models import StockObservation
from app.options.accounting import apply_fill, apply_receipt
from app.options.engine import clock
from app.options.lifecycle import (
    TERMINAL,
    OptionIntent,
    OptionObservation,
    OptionReceipt,
    OptionVenueSnapshot,
)

ZERO = Decimal(0)


def stock_events(db, snapshot):
    rows = {r["client_id"]: r for r in db.execute("SELECT * FROM execution_stock_orders")}
    seen = {}
    events = []
    for obs in snapshot.stock_orders:
        row = rows.get(obs.client_id)
        if (
            row is None
            or row["observation_json"] != obs.model_dump_json()
            or not row["attempted_at"]
        ):
            raise ValueError("MIXED_STORED_STOCK_OBSERVATION_MISMATCH")
        intent = verify_order(db, row)
        if intent != obs.intent:
            raise ValueError("MIXED_STORED_STOCK_INTENT_CHANGED")
        for fill in obs.fills:
            if fill.fill_id in seen:
                raise ValueError("MIXED_DUPLICATE_STOCK_FILL")
            seen[fill.fill_id] = (obs.client_id, fill.model_dump_json())
            events.append((fill.sequence, fill.occurred_at, "STOCK_FILL", (intent, fill)))
    known = {
        r["fill_id"]: (r["client_id"], r["payload"])
        for r in db.execute("SELECT * FROM execution_stock_fills")
    }
    if seen != known:
        raise ValueError("MIXED_STORED_FILL_COVERAGE_MISMATCH")
    if any(
        r["attempted_at"] and k not in {o.client_id for o in snapshot.stock_orders}
        for k, r in rows.items()
    ):
        raise ValueError("MIXED_STOCK_ATTEMPT_MISSING")
    return events


def _intervals(db, policy):
    c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
    snap = OptionVenueSnapshot.model_validate_json(c["snapshot_json"])
    events = stock_events(db, snap)
    for row in db.execute("SELECT * FROM execution_orders"):
        intent = OptionIntent.model_validate_json(row["intent_json"])
        obs = (
            OptionObservation.model_validate_json(row["observation_json"])
            if row["observation_json"]
            else None
        )
        events.extend(
            (f.sequence, f.occurred_at, "FILL", (intent, f)) for f in (obs.fills if obs else ())
        )
    events.extend((r.sequence, r.occurred_at, "RECEIPT", r) for r in snap.receipts)
    state = MixedLedger(cash=policy.capital, high_watermark=policy.capital)
    intervals = []
    active = None
    for _, at, kind, item in sorted(events, key=lambda e: e[0]):
        if kind == "STOCK_FILL":
            state = _apply_stock(state, *item)
        elif kind == "FILL":
            state = _merge(state, apply_fill(_option_part(state), *item))
        else:
            state = _merge(state, apply_receipt(_option_part(state), item))
        current = (
            state.stock_position.entry.client_id
            if state.stock_position
            else state.position.entry_client_id
            if state.position
            else None
        )
        if active is None and current is not None:
            active = [current, at, None]
        elif active is not None and current is None:
            active[2] = at
            intervals.append(active)
            active = None
    if active:
        intervals.append(active)
    return intervals, snap.captured_at


def costed(db, policy, outcome):
    if policy.mixed_owner is None:
        return outcome
    if db.execute("SELECT 1 FROM execution_model_calls LIMIT 1").fetchone():
        raise ValueError("MIXED_PAID_CONTRACT_NOT_ENROLLED")
    intervals, at = _intervals(db, policy)
    opened = clock(
        datetime.fromisoformat(
            db.execute("SELECT opened_at FROM execution_mixed_control WHERE id=1").fetchone()[0]
        )
    )
    zone = ZoneInfo("America/New_York")
    start = opened.astimezone(zone).date()
    end = at.astimezone(zone).date()
    if not 0 <= (end - start).days <= 366:
        raise ValueError("MIXED_ALLOCATION_HORIZON")
    p = policy.mixed_owner
    records = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        when = max(opened, datetime.combine(day, time.min, zone))
        # Charge the held entry at the calendar boundary, otherwise the next actual
        # filled entry. Idle charges remain in the account budget in the meantime.
        owned = next((i for i, a, b in intervals if a <= when and (b is None or when <= b)), None)
        if owned is None:
            owned = next((i for i, a, b in intervals if a >= when), None)
        if owned != outcome["entry_client_id"]:
            continue
        records.extend(
            {
                "cost_id": f"mixed:{day}:{kind}",
                "amount": str(amount) if amount is not None else None,
            }
            for kind, amount in (
                ("DATA", p.daily_data_cost),
                ("HOST", p.daily_host_cost),
                ("OPERATING", p.daily_operating_cost),
            )
        )
    known = sum((Decimal(r["amount"]) for r in records if r["amount"] is not None), ZERO)
    unknown = any(r["amount"] is None for r in records)
    before = outcome.get("net_after_known_execution_and_model_costs")
    net = Decimal(before) - known if before is not None and not unknown else None
    return {
        **outcome,
        "operating_allocations": records,
        "known_operating_cost": str(known),
        "net_after_all_costs": str(net) if net is not None else None,
        "status": "COMPLETE" if net is not None else "INCOMPLETE",
        "outcome": None if net is None else "LOSS" if net < 0 else "WIN" if net > 0 else "FLAT",
        "data_host_costs_included": not unknown,
    }


def stock_outcome(engine, db, entry_id):
    from app.options.position_outcome import _settlement_links

    rows = db.execute("SELECT * FROM execution_stock_orders").fetchall()
    entries = {r["client_id"]: r for r in rows}
    entry = verify_order(db, entries[entry_id])
    if entry.side != "BUY":
        raise ValueError("STOCK_OUTCOME_ENTRY_REQUIRED")
    option_rows = db.execute("SELECT * FROM execution_orders").fetchall()
    receipts = [
        OptionReceipt.model_validate_json(r[0])
        for r in db.execute("SELECT payload FROM execution_option_receipts")
    ]
    _settlement_links(db, option_rows, receipts, engine.policy)
    bought = sold = cost = proceeds = fees = ZERO
    fills = []
    times = []
    terminal = True
    for row in rows:
        intent = verify_order(db, row)
        if intent.client_id != entry_id and intent.closing_entry_client_id != entry_id:
            continue
        terminal = terminal and row["status"] in TERMINAL
        obs = (
            StockObservation.model_validate_json(row["observation_json"])
            if row["observation_json"]
            else None
        )
        for f in obs.fills if obs else ():
            fills.append(f.fill_id)
            fees += f.fee
            if intent.side == "BUY":
                bought += f.quantity
                cost += f.quantity * f.price
            else:
                sold += f.quantity
                proceeds += f.quantity * f.price
                times.append(f.occurred_at)
    closed = terminal and bought > 0 and bought == sold
    net = proceeds - cost - fees if closed else None
    return costed(
        db,
        engine.policy,
        {
            "entry_kind": "STOCK",
            "entry_client_id": entry_id,
            "population_id": engine.limits.population_id,
            "entry_lineage": {
                "family": entry.family,
                "source_hash": entry.source_hash,
                "source_at": entry.source_at.isoformat(),
                "source_valid_until": entry.source_valid_until.isoformat(),
            },
            "original_entry": entry.model_dump(mode="json"),
            "closed_at": max(times).isoformat() if closed else None,
            "entry_quantity": str(bought),
            "exit_quantity": str(sold),
            "entry_cash": str(cost),
            "exit_cash": str(proceeds),
            "execution_fees": str(fees),
            "known_model_cost": "0",
            "net_after_known_execution_and_model_costs": str(net) if net is not None else None,
            "fill_ids": fills,
            "model_calls": [],
            "status": "COMPLETE" if net is not None else "INCOMPLETE",
            "execution_authority": False,
            "live_enabled": False,
        },
    )


def record(outcome):
    # Exact cost allocation and original stock source remain in the consumed digest.
    fields = (
        "entry_kind",
        "entry_client_id",
        "population_id",
        "entry_lineage",
        "original_entry",
        "closed_at",
        "entry_quantity",
        "exit_quantity",
        "entry_cash",
        "exit_cash",
        "execution_fees",
        "known_model_cost",
        "net_after_known_execution_and_model_costs",
        "fill_ids",
        "model_calls",
        "operating_allocations",
        "known_operating_cost",
        "net_after_all_costs",
        "outcome",
    )
    return {k: outcome[k] for k in fields}
