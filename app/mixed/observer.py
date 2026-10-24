"""Explicit mixed-account stored observer. No executable owner or provider attachment."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.native_models import StockProtection
from app.mixed.native_store import TABLES, allocations, history, model_costs, verify, verify_order
from app.mixed.replay_export import native_snapshot_coverage, option_holding
from app.mixed.stock_models import StockQuote
from app.options.attribution import order_attribution
from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.governor import _fresh
from app.options.lifecycle import (
    OptionExecutionPolicy,
    OptionIntent,
    OptionLedger,
    OptionVenueSnapshot,
)
from app.options.models import OptionLimits
from app.options.observer import REQUIRED, OptionObserver, _age, _health, _json

MAX_ROWS = 2000


def rows(db, table):
    values = db.execute(f"SELECT * FROM {table} ORDER BY rowid LIMIT {MAX_ROWS + 1}").fetchall()
    if len(values) > MAX_ROWS:
        raise ValueError("Mixed observer row capacity exceeded")
    return values


class MixedObserver(OptionObserver):
    """The legacy observer remains unchanged and rejects mixed enrollment."""

    def report(self, **kwargs):
        value = super().report(**kwargs)
        return value | {"version": "mixed-stored-observer-v1", "mode": "MIXED_PAPER_FIXTURE"}

    def _snapshot(self, db, now, limit, before, family):
        try:
            return self._mixed_snapshot(db, now, limit, before, family)
        except ExecutionBlocked as exc:
            raise ValueError("Stored mixed evidence unavailable") from exc

    def _mixed_snapshot(self, db, now, limit, before, family):
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED | TABLES <= tables:
            raise ValueError("Explicit native mixed schema required")
        # Bound the complete validation scans, including paid requests and runtime packets.
        for table in sorted(tables):
            if (
                table.startswith("execution_")
                and db.execute(
                    'SELECT count(*) FROM "' + table.replace('"', '""') + '"'
                ).fetchone()[0]
                > MAX_ROWS
            ):
                raise ValueError("Mixed observer row capacity exceeded")
        c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
        config = _json(c["config_json"])
        policy = OptionExecutionPolicy.model_validate(config["policy"])
        limits = OptionLimits.model_validate(config["limits"])
        if (
            config["schema"] != "option-paper-execution-v1"
            or policy.mixed_owner is None
            or limits.population_id != self.population_id
            or Decimal(config["capital"]) != policy.capital
        ):
            raise ValueError("Frozen native mixed population required")
        # This facade only supplies data to existing pure verification functions.
        owner = SimpleNamespace(
            policy=policy,
            limits=limits,
            venue=SimpleNamespace(venue_id=config["venue_id"]),
            _control=lambda connection: c,
        )
        mixed = verify(owner, db)
        ledger = OptionLedger.model_validate_json(c["ledger_json"])
        snap = (
            OptionVenueSnapshot.model_validate_json(c["snapshot_json"])
            if c["snapshot_json"]
            else None
        )
        if snap and (
            snap.population_id != self.population_id
            or snap.account_id != limits.account_id
            or snap.venue_id != config["venue_id"]
            or snap.captured_at > now
        ):
            raise ValueError("Native mixed snapshot identity/clock mismatch")
        issues = _json(c["issues_json"])
        if not isinstance(issues, list) or any(not isinstance(x, str) for x in issues):
            raise ValueError("Stored reconciliation issues required")
        orders, fills = [], []
        for table, kind in [("execution_orders", "OPTION"), ("execution_stock_orders", "STOCK")]:
            for row in rows(db, table):
                intent = (
                    verify_order(db, row)
                    if kind == "STOCK"
                    else OptionIntent.model_validate_json(row["intent_json"])
                )
                if kind == "OPTION":
                    order_attribution(db, row)
                instrument = intent.instrument
                approval = _json(row["approval_json"])
                orders.append(
                    {
                        "asset": kind,
                        "symbol": instrument.symbol
                        if kind == "STOCK"
                        else instrument.contract.underlying,
                        "intent": intent.model_dump(mode="json"),
                        "status": row["status"],
                        "attempted_at": row["attempted_at"],
                        "unresolved": row["active_lock"] == 1,
                        "origin": (approval.get("inputs", {}) if kind == "STOCK" else approval).get(
                            "origin", "UNKNOWN"
                        ),
                        "observation": _json(row["observation_json"])
                        if row["observation_json"]
                        else None,
                    }
                )
        cost_records = allocations(owner, db, now) + model_costs(owner, db)
        if any(c.occurred_at > now for c in cost_records):
            raise ValueError("Future cost evidence")
        unknown_costs = [c.cost_id for c in cost_records if c.amount is None]
        if policy.mixed_owner.reasoning is None and rows(db, "execution_model_calls"):
            unknown_costs.append("UNENROLLED_MODEL_CALLS")
        known_cost = sum((c.amount for c in cost_records if c.amount is not None), Decimal(0))
        captured = projected = None
        accounting = "VERIFIED"
        try:
            if snap is None or not snap.complete or issues:
                raise ValueError("Incomplete reconciliation")
            native_snapshot_coverage(db, snap)
            captured = history(owner, db, as_of=now)
            projected = reconstruct(captured)
            option_holding(db, projected.ledger.position, ledger.position, snap.position, limits)
            stock = projected.ledger.stock_position
            if (
                projected.ledger.model_dump(exclude={"version", "stock_position", "position"})
                != ledger.model_dump(exclude={"version", "position"})
                or (stock.model_dump(mode="json") if stock else None)
                != (_json(mixed["position_json"]) if mixed["position_json"] else None)
                or stock != snap.stock_position
                or ledger.cash != snap.cash
                or ledger.settled_cash != snap.settled_cash
            ):
                raise ValueError("Mixed ledger/snapshot mismatch")
        except (ValueError, ExecutionBlocked, KeyError, TypeError, ArithmeticError):
            accounting, captured, projected = "UNAVAILABLE", None, None
        if projected:
            for order in orders:
                for fill in (order["observation"] or {}).get("fills", []):
                    fills.append(
                        {
                            "asset": order["asset"],
                            "symbol": order["symbol"],
                            "side": order["intent"]["side"],
                            **fill,
                        }
                    )
        frames = stored_frames(db, tables, now)
        position = None
        if projected and projected.ledger.stock_position:
            position = stock_position(
                db, projected.ledger.stock_position, mixed, policy, now, frames
            )
        elif projected and ledger.position:
            p = self._position(db, ledger, frames, limits, now)
            entry = next(
                o["intent"]
                for o in orders
                if o["intent"]["client_id"] == ledger.position.entry_client_id
            )
            position = {
                "asset": "OPTION",
                "symbol": p["contract"]["underlying"],
                "quantity": p["quantity"],
                "basis": p["cost_basis"],
                "mark": p["gross_bid_mark"],
                "mark_status": p["quote_status"],
                "quote_at": p["quote"]["source_at"] if p["quote"] else None,
                "quote_age_seconds": p["quote_age_seconds"],
                "original_stop": p["original_invalidation"],
                "active_stop": p["tightened_invalidation"],
                "exit_at": p["exit_at"],
                "exit_reason": p["exit_reason"],
                "issue": p["supervision_issue"],
                "thesis": p["thesis"],
                "entry": entry,
                "details": p,
                "targets": (entry.get("target_exit_schedule") or {}).get("steps", []),
                "target_stage": ledger.position.target_exit_stage,
            }
        if position:
            position["gross_unrealized"] = (
                str(Decimal(position["mark"]) - Decimal(position["basis"]))
                if position["mark"] is not None
                else None
            )
        health = _health(snap.captured_at if snap else None, now, limits.account_max_age_seconds)
        costs = [x.model_dump(mode="json") for x in cost_records]
        unresolved = sum(o["unresolved"] for o in orders)
        equity = None
        if (
            projected
            and not unknown_costs
            and not unresolved
            and health == "FRESH"
            and (position is None or position["mark"] is not None)
        ):
            equity = str(ledger.cash + Decimal(position["mark"] if position else 0) - known_cost)
        supervisor = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
        heartbeat = supervisor["heartbeat_at"] if supervisor else None
        decisions = []
        if "execution_option_opportunities" in tables:
            for row in db.execute(
                "SELECT rowid,* FROM execution_option_opportunities WHERE rowid < ? ORDER BY rowid DESC LIMIT ?",
                (before or 9223372036854775807, limit + 1),
            ):
                if before is not None and row["rowid"] >= before:
                    continue
                result = _json(row["result_json"]) if row["result_json"] else {}
                decisions.append(
                    {
                        "rowid": row["rowid"],
                        "key": row["cycle_key"],
                        "started_at": row["started_at"],
                        "status": row["status"],
                        "result": {
                            k: v
                            for k, v in result.items()
                            if k
                            in {
                                "status",
                                "reason",
                                "blocker",
                                "error_class",
                                "entry_result",
                                "position_result",
                                "entry_review",
                                "position_review",
                                "cost",
                                "model_cost",
                                "model_error_class",
                                "client_id",
                                "position_application",
                            }
                        },
                        "proposal": (
                            result.get("entry_result") or result.get("position_result") or {}
                        ).get("plan"),
                        "linked_orders": [
                            o["intent"]["client_id"]
                            for o in orders
                            if o["intent"]["source_key"] == row["cycle_key"]
                        ],
                    }
                )
        points = (
            balance_history(db, captured, now, orders)
            if projected and "UNENROLLED_MODEL_CALLS" not in unknown_costs
            else []
        )
        return {
            "status": "OK",
            "accounting": accounting,
            "account_id": limits.account_id,
            "captured_at": snap.captured_at.isoformat() if snap else None,
            "health": health,
            "age_seconds": _age(snap.captured_at if snap else None, now),
            "cash": str(ledger.cash) if projected else None,
            "settled_cash": str(ledger.settled_cash) if projected else None,
            "reserved_cash": str(projected.reserved_cash) if projected else None,
            "known_cost": str(known_cost),
            "unknown_costs": unknown_costs,
            "execution_fees": str(ledger.fees_paid) if projected else None,
            "equity": equity,
            "position": position,
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
                "age_seconds": _age(datetime.fromisoformat(heartbeat), now) if heartbeat else None,
            },
            "orders": sorted(orders, key=lambda o: o["intent"]["prepared_at"], reverse=True)[
                :limit
            ],
            "order_count": len(orders),
            "fills": sorted(fills, key=lambda f: f["occurred_at"], reverse=True)[:limit],
            "fill_count": len(fills) if projected else None,
            "costs": costs,
            "decisions": decisions[:limit],
            "has_older": len(decisions) > limit,
            "next_before": decisions[limit - 1]["rowid"] if len(decisions) > limit else None,
            "limit": limit,
            "points": points,
            "chart": history_chart(points),
            "initial_capital": str(policy.capital),
            "policy": policy.model_dump(mode="json"),
            "limits": limits.model_dump(mode="json"),
        }


def stored_frames(db, tables, now):
    frames = []
    if "execution_option_opportunities" in tables:
        for row in db.execute(
            "SELECT inputs_json FROM execution_option_opportunities ORDER BY rowid DESC LIMIT 100"
        ):
            frames.append(DegenFrame.model_validate(_json(row[0])))
    if "execution_mixed_runtime_inputs" in tables:
        from app.options.runtime_models import MixedRuntimePacket

        for row in db.execute(
            "SELECT * FROM execution_mixed_runtime_inputs ORDER BY sequence DESC LIMIT 100"
        ):
            packet = MixedRuntimePacket.model_validate_json(row["packet_json"])
            if fingerprint(packet) != row["packet_hash"] or packet.recorded_at > now:
                raise ValueError("Original mixed runtime packet changed")
            if row["status"] == "DELIVERED":
                frames.append(packet.frame)
    return frames


def stock_position(db, p, mixed, policy, now, frames):
    guard = StockProtection.model_validate_json(mixed["protection_json"])
    if (
        guard.entry_client_id != p.entry_client_id
        or guard.invalidation < p.entry.original_invalidation
    ):
        raise ValueError("Original stock protection mismatch")
    quotes = [
        item.quote
        for frame in frames
        for item in frame.stocks
        if item.quote.instrument.instrument_id == p.instrument.instrument_id
    ]
    for row in rows(db, "execution_stock_decisions"):
        raw = _json(row["inputs_json"]).get("quote")
        if raw:
            q = StockQuote.model_validate(raw)
            if q.instrument.instrument_id == p.instrument.instrument_id:
                quotes.append(q)
    for row in rows(db, "execution_stock_fills"):
        q = StockQuote.model_validate(_json(row["payload"])["quote"])
        if q.instrument.instrument_id == p.instrument.instrument_id:
            quotes.append(q)
    q = max(quotes, key=lambda q: q.received_at) if quotes else None
    conflict = q is not None and any(x.received_at == q.received_at and x != q for x in quotes)
    limits = policy.mixed_owner.stocks
    usable = bool(
        q
        and not conflict
        and q.instrument == p.instrument
        and q.complete
        and q.entitlement == "REALTIME"
        and q.source == limits.quote_source
        and q.bid_size is not None
        and q.bid_size >= p.quantity
        and _fresh(
            q.source_at,
            q.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    )
    return {
        "asset": "STOCK",
        "symbol": p.instrument.symbol,
        "quantity": str(p.quantity),
        "basis": str(p.basis),
        "mark": str(q.bid * p.quantity) if usable else None,
        "mark_status": "USABLE_STORED_BID"
        if usable
        else "CONFLICTING"
        if conflict
        else "STALE_OR_MISSING",
        "quote_at": q.source_at.isoformat() if q else None,
        "quote_age_seconds": _age(q.source_at if q else None, now),
        "original_stop": str(p.entry.original_invalidation),
        "active_stop": str(guard.invalidation),
        "exit_at": p.entry.exit_at.isoformat(),
        "exit_reason": guard.exit_reason,
        "issue": guard.issue,
        "thesis": p.entry.thesis,
        "entry": p.entry.model_dump(mode="json"),
        "targets": [
            {"underlying_price": str(p.entry.original_target), "quantity": str(p.entry.quantity)}
        ],
        "target_stage": None,
        "details": {
            "protection": guard.model_dump(mode="json"),
            "position": p.model_dump(mode="json"),
            "quote": q.model_dump(mode="json") if q else None,
        },
    }


def snapshot_prefix(snap, captured, orders):
    """Historical fills must be exact native prefixes; missing coverage creates a gap."""
    native = {o["intent"]["client_id"]: o for o in orders}
    observed_ids = [o.client_id for o in (*snap.orders, *snap.stock_orders)]
    required_orders = {
        key
        for key, order in native.items()
        if order["attempted_at"] is not None
        and datetime.fromisoformat(order["attempted_at"]) < snap.captured_at
    }
    if len(set(observed_ids)) != len(observed_ids) or not required_orders <= set(observed_ids):
        return False
    for observed in (*snap.orders, *snap.stock_orders):
        order = native.get(observed.client_id)
        if (
            order is None
            or order["attempted_at"] is None
            or datetime.fromisoformat(order["attempted_at"]) > snap.captured_at
            or observed.updated_at > snap.captured_at
        ):
            return False
        intent = order["intent"]
        if any(
            observed.model_dump(mode="json")[k] != intent[k]
            for k in ("instrument", "side", "quantity", "limit_price")
        ):
            return False
        if hasattr(observed, "intent") and observed.intent.model_dump(mode="json") != intent:
            return False
    actual = {
        f.fill_id: (o.client_id, f) for o in (*snap.orders, *snap.stock_orders) for f in o.fills
    }
    if len(actual) != sum(len(o.fills) for o in (*snap.orders, *snap.stock_orders)):
        return False
    expected = {
        e.fill.fill_id: (e.intent.client_id, e.fill) for e in captured.events if hasattr(e, "fill")
    }
    required = {key for key, (_, fill) in expected.items() if fill.occurred_at < snap.captured_at}
    if not required <= actual.keys() or any(
        expected.get(key) != pair for key, pair in actual.items()
    ):
        return False
    receipts = {e.receipt.receipt_id: e.receipt for e in captured.events if hasattr(e, "receipt")}
    if any(receipts.get(r.receipt_id) != r for r in snap.receipts):
        return False
    return {key for key, r in receipts.items() if r.occurred_at < snap.captured_at} <= {
        r.receipt_id for r in snap.receipts
    }


def balance_history(db, captured, now, orders):
    """Only fill-reconstructed flat boundaries have equity; open exposure stays a gap."""
    values = db.execute(
        "SELECT payload FROM execution_snapshots ORDER BY rowid DESC LIMIT 100"
    ).fetchall()
    points = []
    for row in reversed(values):
        snap = OptionVenueSnapshot.model_validate_json(row[0])
        if snap.captured_at > captured.captured_at or snap.captured_at > now:
            raise ValueError("Future historical snapshot")
        historical_coverage = snapshot_prefix(snap, captured, orders)
        # Reconstruct cash at this boundary from the verified complete current history.
        events = tuple(
            e
            for e in captured.events
            if (e.fill.occurred_at if hasattr(e, "fill") else e.receipt.occurred_at)
            <= snap.captured_at
        )
        costs = tuple(c for c in captured.costs if c.occurred_at <= snap.captured_at)
        h = captured.model_copy(
            update={
                "captured_at": snap.captured_at,
                "events": events,
                "costs": costs,
                "reservations": (),
            }
        )
        result = reconstruct(h)
        if (
            snap.population_id != captured.population_id
            or snap.account_id != captured.account_id
            or snap.venue_id != captured.venue_id
            or result.ledger.cash != snap.cash
            or result.ledger.settled_cash != snap.settled_cash
        ):
            raise ValueError("Historical cash evidence changed")
        held = result.ledger.position is not None or result.ledger.stock_position is not None
        pending = any(
            o.status not in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
            for o in (*snap.orders, *snap.stock_orders)
        )
        known = (
            historical_coverage
            and snap.complete
            and not held
            and snap.position is None
            and snap.stock_position is None
            and not pending
            and not result.unknown_cost_ids
        )
        points.append(
            {
                "at": snap.captured_at.isoformat(),
                "equity": str(result.ledger.cash - result.known_cost) if known else None,
                "reason": "FLAT_FULL_COST_BOUNDARY" if known else "OPEN_OR_INCOMPLETE_EVIDENCE",
            }
        )
    return points


def history_chart(points):
    known = [Decimal(p["equity"]) for p in points if p["equity"] is not None]
    if not known:
        return None
    low, high = min(known), max(known)
    pad = max((high - low) / 10, Decimal(1))
    low, high = low - pad, high + pad
    y = lambda value: format(190 - (value - low) / (high - low) * 160, ".2f")
    segments, segment, dots = [], [], []
    for i, p in enumerate(points):
        if p["equity"] is None:
            if segment:
                segments.append(" ".join(segment))
                segment = []
            continue
        x = format(Decimal(60) + Decimal(620) * i / max(1, len(points) - 1), ".2f")
        dot = {"x": x, "y": y(Decimal(p["equity"])), "at": p["at"], "equity": p["equity"]}
        dots.append(dot)
        segment.append(x + "," + dot["y"])
    if segment:
        segments.append(" ".join(segment))
    return {
        "segments": segments,
        "dots": dots,
        "ticks": [{"label": format(v, ".2f"), "y": y(v)} for v in (low, (low + high) / 2, high)],
    }
