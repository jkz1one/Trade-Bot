"""Stored v2 portfolio view: exact receipts and per-play quotes, no owner or network."""

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.mixed.accounting import reconstruct
from app.mixed.portfolio_store import control, history, intent
from app.mixed.portfolio_venue import PortfolioVenueSnapshot
from app.mixed.stock_models import StockPosition, StockQuote
from app.options.engine import fingerprint
from app.options.governor import _fresh
from app.options.lifecycle import OptionPosition
from app.options.models import OptionQuote
from app.options.observer import _age, _health


def snapshot(observer, db, now, limit, before, family, config, policy, limits):
    from app.mixed.observer import history_chart, stored_stream
    from app.mixed.portfolio_execution import policy as portfolio_policy
    from app.options.operator import summary

    c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
    if (
        config["schema"] != "option-paper-execution-v1"
        or limits.population_id != observer.population_id
        or Decimal(config["capital"]) != policy.capital
    ):
        raise ValueError("Frozen portfolio population required")
    owner = SimpleNamespace(
        policy=policy,
        limits=limits,
        venue=SimpleNamespace(venue_id=config["venue_id"]),
        _control=lambda connection: c,
        _closed=False,
    )
    p = portfolio_policy(owner)
    owner.portfolio_policy = p
    stored = control(owner, db, p)
    snap = PortfolioVenueSnapshot.model_validate_json(stored["snapshot_json"])
    if (snap.account_id, snap.population_id, snap.venue_id, snap.portfolio_policy) != (
        limits.account_id,
        limits.population_id,
        config["venue_id"],
        p,
    ) or snap.captured_at > now:
        raise ValueError("Portfolio snapshot identity changed")
    h = history(owner, db, p, now)
    projected = reconstruct(h)
    if (projected.ledger.cash, projected.ledger.settled_cash, projected.ledger.positions) != (
        snap.cash,
        snap.settled_cash,
        snap.positions,
    ):
        raise ValueError("Portfolio receipt accounting mismatch")
    issues = json.loads(c["issues_json"])
    if issues or not snap.complete:
        raise ValueError("Portfolio reconciliation incomplete")
    guards = json.loads(stored["protection_json"])
    orders, fills = [], []
    for row in db.execute("SELECT * FROM execution_portfolio_orders ORDER BY rowid"):
        i = intent(row)
        stock = row["asset"] == "STOCK"
        o = {
            "asset": row["asset"],
            "play_id": row["play_id"],
            "symbol": i.instrument.symbol if stock else i.instrument.contract.underlying,
            "intent": i.model_dump(mode="json"),
            "status": row["status"],
            "attempted_at": row["attempted_at"],
            "unresolved": row["active_play"] is not None,
            "origin": json.loads(row["approval_json"])["inputs"]["origin"],
            "observation": json.loads(row["observation_json"]) if row["observation_json"] else None,
        }
        orders.append(o)
        fills.extend(
            {
                "asset": o["asset"],
                "play_id": row["play_id"],
                "symbol": o["symbol"],
                "side": i.side,
                **f,
            }
            for f in (o["observation"] or {}).get("fills", [])
        )
    positions = []
    for identity, held in projected.ledger.positions.items():
        saved = guards.get(identity)
        entry = next(o for o in orders if o["intent"]["client_id"] == identity)
        positions.append(position(held, entry, saved, orders, p, now))
    health = _health(snap.captured_at, now, limits.account_max_age_seconds)
    unresolved = sum(o["unresolved"] for o in orders)
    equity = None
    if (
        not projected.unknown_cost_ids
        and not unresolved
        and health == "FRESH"
        and all(x["mark"] is not None for x in positions)
    ):
        equity = str(
            projected.ledger.cash
            + sum(Decimal(x["mark"]) for x in positions)
            - projected.known_cost
        )
    stream = stored_stream(db, (), None, now)
    for item in positions:
        stream.extend(r for r in stored_stream(db, (), item, now) if r["kind"] == "QUOTE")
    # Never duplicate shared quote receipts or change their original timestamps.
    stream = sorted(
        {fingerprint(r): r for r in stream}.values(),
        key=lambda r: datetime.fromisoformat(r["at"]),
        reverse=True,
    )[:80]
    points = []
    for row in db.execute("SELECT payload FROM execution_snapshots ORDER BY rowid DESC LIMIT 100"):
        historic = PortfolioVenueSnapshot.model_validate_json(row[0])
        if historic.positions:
            continue
        costs = [c for c in h.costs if c.occurred_at <= historic.captured_at]
        valid = all(c.amount is not None for c in costs) and all(
            o.status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
            for o in (*historic.orders, *historic.stock_orders)
        )
        points.append(
            {
                "at": historic.captured_at.isoformat(),
                "equity": str(historic.cash - sum((c.amount for c in costs), Decimal(0)))
                if valid
                else None,
                "reason": "FLAT_FULL_COST_BOUNDARY" if valid else "INCOMPLETE_EVIDENCE",
            }
        )
    points.reverse()
    decisions = []
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_opportunities'"
    ).fetchone():
        for row in db.execute(
            "SELECT rowid,* FROM execution_option_opportunities WHERE rowid < ? ORDER BY rowid DESC LIMIT ?",
            (before or 9223372036854775807, limit + 1),
        ):
            data = json.loads(row["result_json"] or "{}")
            decisions.append(
                {
                    "rowid": row["rowid"],
                    "key": row["cycle_key"],
                    "started_at": row["started_at"],
                    "status": row["status"],
                    "result": {
                        k: v
                        for k, v in data.items()
                        if k
                        in {
                            "status",
                            "reason",
                            "blocker",
                            "error_class",
                            "entry_result",
                            "position_result",
                            "mixed_selection",
                            "scope_arbitration",
                            "play_id",
                        }
                    },
                }
            )
    supervisor = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
    heartbeat = supervisor["heartbeat_at"] if supervisor else None
    revision = db.execute("SELECT COALESCE(MAX(sequence),0) FROM execution_events").fetchone()[0]
    from app.options.loss_control import stored_state

    return {
        "status": "OK",
        "schema": "mixed-portfolio-observer-v2",
        "revision": revision,
        "stream": stream,
        "accounting": "VERIFIED",
        "account_id": limits.account_id,
        "captured_at": snap.captured_at.isoformat(),
        "health": health,
        "age_seconds": _age(snap.captured_at, now),
        "cash": str(projected.ledger.cash),
        "settled_cash": str(projected.ledger.settled_cash),
        "reserved_cash": str(projected.reserved_cash),
        "known_cost": str(projected.known_cost),
        "unknown_costs": list(projected.unknown_cost_ids),
        "execution_fees": str(projected.ledger.fees_paid),
        "equity": equity,
        "positions": positions,
        # The scalar is deliberately absent for v2. The display chooses an explicit card.
        "position": None,
        "max_plays": stored["limit_value"],
        "occupied_plays": len(projected.commitments),
        "unresolved": unresolved,
        "halted": bool(c["halted"]),
        "halt_reason": c["halt_reason"],
        "issues": issues,
        "supervision": {
            "recorded_status": supervisor["status"] if supervisor else "MISSING",
            "freshness": _health(
                datetime.fromisoformat(heartbeat) if heartbeat else None,
                now,
                policy.supervisor_max_age_seconds,
            ),
            "at": heartbeat,
        },
        "orders": sorted(orders, key=lambda o: o["intent"]["prepared_at"], reverse=True)[:limit],
        "position_orders": [o for o in orders if o["play_id"] in projected.ledger.positions],
        "order_count": len(orders),
        "fills": sorted(fills, key=lambda f: f["occurred_at"], reverse=True)[:limit],
        "fill_count": len(fills),
        "costs": [x.model_dump(mode="json") for x in h.costs],
        "decisions": decisions[:limit],
        "has_older": len(decisions) > limit,
        "next_before": decisions[limit - 1]["rowid"] if len(decisions) > limit else None,
        "limit": limit,
        "points": points,
        "chart": history_chart(points),
        "initial_capital": str(policy.capital),
        "policy": policy.model_dump(mode="json"),
        "limits": limits.model_dump(mode="json"),
        "operator": summary(db),
        "loss_control": stored_state(db),
    }


def position(held, entry, saved, orders, policy, now):
    stock = isinstance(held, StockPosition)
    i = entry["intent"]
    identity = held.entry_client_id
    candidates = []
    if saved and saved.get("quote"):
        candidates.append(saved["quote"])
    candidates.extend(
        f["quote"]
        for o in orders
        if o["play_id"] == identity
        for f in (o["observation"] or {}).get("fills", [])
    )
    cls = StockQuote if stock else OptionQuote
    quotes = [cls.model_validate(q) for q in candidates]
    quotes = [q for q in quotes if q.received_at <= now]
    q = max(quotes, key=lambda q: q.received_at) if quotes else None
    conflict = q is not None and any(x.received_at == q.received_at and x != q for x in quotes)
    rule = policy.stocks if stock else policy.options
    correct = q is not None and (
        q.instrument == held.instrument if stock else q.instrument.contract == held.contract
    )
    usable = bool(
        correct
        and not conflict
        and q.complete
        and q.entitlement == "REALTIME"
        and q.source == (rule.quote_source if stock else rule.option_source)
        and q.bid is not None
        and q.bid > 0
        and q.bid_size is not None
        and q.bid_size >= held.quantity
        and _fresh(
            q.source_at,
            q.received_at,
            now,
            rule.quote_max_age_seconds,
            rule.max_receive_lag_seconds,
        )
    )
    multiplier = 1 if stock else held.contract.multiplier
    mark = q.bid * held.quantity * multiplier if usable else None
    guard = saved["guard"] if saved else {}
    managed = OptionPosition.model_validate(saved["position"]) if saved and not stock else None
    if saved and guard.get("entry_client_id") != identity:
        raise ValueError("Portfolio supervision identity changed")
    details = {
        "quote": q.model_dump(mode="json") if q else None,
        "position": held.model_dump(mode="json"),
    }
    if not stock:
        if managed and (
            managed.contract != held.contract
            or managed.original_underlying_invalidation != held.original_underlying_invalidation
        ):
            raise ValueError("Portfolio original option supervision changed")
        details.update(
            contract=held.contract.model_dump(mode="json"),
            underlying=saved.get("underlying") if saved else None,
        )
        if managed and managed.trade_floor:
            details["trade_floor"] = managed.trade_floor.model_dump(mode="json")
        if managed and managed.premium_trail:
            from app.options.premium_trail import floor_value

            value = floor_value(managed.premium_trail, held.contract.multiplier)
            details["premium_trail"] = {
                **managed.premium_trail.model_dump(mode="json"),
                "floor_original_quantity_premium": str(value) if value is not None else None,
            }
    else:
        details["protection"] = guard
    original_stop = (
        held.entry.original_invalidation if stock else held.original_underlying_invalidation
    )
    return {
        "play_id": identity,
        "asset": entry["asset"],
        "symbol": entry["symbol"],
        "quantity": str(held.quantity),
        "basis": str(held.basis),
        "mark": str(mark) if mark is not None else None,
        "mark_status": "USABLE_STORED_BID"
        if usable
        else "CONFLICTING"
        if conflict
        else "STALE_OR_MISSING",
        "quote_at": q.source_at.isoformat() if q else None,
        "quote_age_seconds": _age(q.source_at if q else None, now),
        "original_stop": str(original_stop),
        "active_stop": str(
            guard.get("invalidation", original_stop)
            if stock
            else managed.tightened_underlying_invalidation
            if managed
            else original_stop
        ),
        "exit_at": (held.entry.exit_at if stock else held.exit_at).isoformat(),
        "exit_reason": guard.get("exit_reason"),
        "issue": guard.get("issue") if saved else "PROTECTION_NOT_ASSESSED",
        "thesis": i["thesis"],
        "entry": i,
        "details": details,
        "targets": [
            {
                "underlying_price": str(held.entry.original_target),
                "quantity": str(held.entry.quantity),
            }
        ]
        if stock
        else (i.get("target_exit_schedule") or {}).get("steps", []),
        "target_stage": managed.target_exit_stage if managed else None,
        "gross_unrealized": str(mark - held.basis) if mark is not None else None,
    }
