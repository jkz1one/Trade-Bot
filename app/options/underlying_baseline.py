"""Deterministic long-share comparison on sealed evidence; no trader or venue authority."""

from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.options.models import paper_market_evidence
from app.options.engine import fingerprint
from app.options.governor import _fresh

ZERO = Decimal(0)


def _quote_ok(q, at, limits):
    return (
        q.source == limits.underlying_source
        and paper_market_evidence(q)
        and q.complete
        and q.bid <= q.ask
        and _fresh(
            q.source_at,
            q.received_at,
            at,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    )


def _price(q, buy, policy, limits):
    raw = (q.ask if buy else q.bid) * (1 + (1 if buy else -1) * limits.slippage_bps / 10000)
    return (raw / policy.tick_size).to_integral_value(
        rounding=ROUND_CEILING if buy else ROUND_FLOOR
    ) * policy.tick_size


class _Account:
    def __init__(self, definition, policy):
        self.definition, self.policy = definition, policy
        self.cash = self.settled = definition.policy.capital
        self.position = self.pending = None
        self.costs = ZERO
        self.broken = False

    def session(self, session, source, tape, receipts, source_ok):
        p, limits = self.policy, self.definition.limits
        start, reasons, fills, decisions, used = self.cash, [], [], [], set()
        fees = turnover = ZERO
        allocation = (p.data_cost_per_session or ZERO) + (p.host_cost_per_session or ZERO)
        quotes = {}
        if self.broken:
            reasons.append("UNDERLYING_PRIOR_SESSION_INCOMPLETE")
        if not source_ok:
            reasons.append("UNDERLYING_SOURCE_EVIDENCE_INCOMPLETE")
        if p.data_cost_per_session is None or p.host_cost_per_session is None:
            reasons.append("UNDERLYING_ALLOCATED_COST_UNKNOWN")
        settled_receipts = []
        for r in sorted(receipts, key=lambda r: r.occurred_at):
            if r.amount > self.cash - self.settled:
                reasons.append("UNDERLYING_SETTLEMENT_EXCEEDS_UNSETTLED_CASH")
                break
            self.settled += r.amount
            settled_receipts.append(r.model_dump(mode="json"))
        opening_settled = self.settled
        # An incomplete history cannot manufacture a later restart or reset.
        if reasons:
            self.broken = True
        timeline = []
        if not self.broken:
            timeline.extend((e.recorded_at, 0, e.sequence, e) for e in tape.events)
            timeline.extend(
                (o.intent.prepared_at, 1, n, o)
                for n, o in enumerate(source.orders)
                if o.intent.side == "BUY"
            )
            timeline.extend(
                (
                    min(
                        o.intent.exit_at,
                        session.closes_at
                        - timedelta(minutes=self.definition.policy.exit_cutoff_minutes),
                    ),
                    2,
                    n,
                    o.intent.client_id,
                )
                for n, o in enumerate(source.orders)
                if o.intent.side == "BUY"
            )

        def expire():
            if self.pending:
                record = self.pending["record"]
                record["status"] = (
                    "UNFILLED" if self.pending["observed"] else "QUOTE_EVIDENCE_MISSING"
                )
                if not self.pending["observed"]:
                    reasons.append("UNDERLYING_ENTRY_QUOTE_EVIDENCE_MISSING")
                self.pending = None

        for at, kind, _, item in sorted(timeline, key=lambda x: x[:3]):
            if at > session.closes_at:
                continue
            if self.pending and at >= self.pending["deadline"]:
                expire()
            if kind == 1:
                i, contract = item.intent, item.intent.instrument.contract
                record = {
                    "client_id": i.client_id,
                    "source_key": i.source_key,
                    "symbol": contract.underlying,
                    "status": "INELIGIBLE",
                }
                decisions.append(record)
                if (
                    contract.right != "CALL"
                    or contract.underlying_kind not in {"ETF", "EQUITY"}
                    or contract.underlying_market != "US_LISTED"
                ):
                    record["status"] = "CASH_INELIGIBLE_DIRECTION_OR_INSTRUMENT"
                    continue
                if self.position or self.pending:
                    record["status"] = "CASH_ALREADY_COMMITTED"
                    continue
                if (
                    start - self.cash + allocation >= self.definition.policy.daily_loss_limit
                    or self.definition.policy.capital - self.cash + self.costs + allocation
                    >= self.definition.policy.total_loss_limit
                ):
                    record["status"] = "CASH_LOSS_LIMIT"
                    continue
                q = quotes.get(contract.underlying)
                if q is None or not _quote_ok(q, at, limits):
                    record["status"] = "QUOTE_EVIDENCE_MISSING"
                    reasons.append("UNDERLYING_DECISION_QUOTE_EVIDENCE_MISSING")
                    continue
                if (
                    q.bid < limits.minimum_underlying_price
                    or (q.ask - q.bid) / q.ask > limits.max_spread_fraction
                    or q.bid <= i.original_underlying_invalidation
                ) or at >= min(
                    i.exit_at,
                    session.closes_at
                    - timedelta(minutes=self.definition.policy.entry_cutoff_minutes),
                ):
                    record["status"] = "CASH_STOP_OR_CUTOFF"
                    continue
                price = _price(q, True, p, limits)
                budget = min(
                    self.cash,
                    self.settled,
                    limits.max_entry_debit,
                    limits.max_account_exposure,
                    limits.max_full_premium_loss,
                    self.definition.policy.daily_loss_limit
                    - max(ZERO, start - self.cash + allocation),
                    self.definition.policy.total_loss_limit
                    - max(
                        ZERO, self.definition.policy.capital - self.cash + self.costs + allocation
                    ),
                )
                quantity = max(
                    0,
                    min(
                        p.max_shares,
                        int(
                            (budget - p.entry_fee_per_order - p.exit_fee_per_order)
                            // (price + p.entry_fee_per_share + p.exit_fee_per_share)
                        ),
                    ),
                )
                if quantity == 0:
                    record["status"] = "CASH_INSUFFICIENT_SETTLED_FUNDS"
                    continue
                self.pending = {
                    "intent": i,
                    "decision_at": at,
                    "limit": price,
                    "quantity": quantity,
                    "record": record,
                    "observed": False,
                    "deadline": min(
                        i.approval_expires_at,
                        i.exit_at,
                        session.closes_at
                        - timedelta(minutes=self.definition.policy.exit_cutoff_minutes),
                    ),
                }
                record["status"] = "PENDING"
            elif kind == 2:
                if (
                    self.position
                    and self.position["entry_client_id"] == item
                    and self.position["exit_at"] is None
                ):
                    self.position.update(exit_at=at, exit_reason="TIME")
            else:
                for q in item.frame.underlyings:
                    if q.symbol in quotes and q.source_at < quotes[q.symbol].source_at:
                        continue
                    quotes[q.symbol] = q
                    if not _quote_ok(q, at, limits):
                        continue
                    if self.position and self.position["symbol"] == q.symbol:
                        pos = self.position
                        if pos["exit_at"] is None and q.bid <= pos["stop"]:
                            pos.update(exit_at=at, exit_reason="STOP")
                        if pos["exit_at"] is not None and q.source_at > pos["exit_at"]:
                            if q.bid_size is None:
                                reasons.append("UNDERLYING_EXIT_QUOTE_EVIDENCE_MISSING")
                                continue
                            identity = ("SELL", q.symbol, q.source, q.source_at)
                            size = 0 if identity in used else min(pos["quantity"], q.bid_size)
                            price = _price(q, False, p, limits)
                            if size and price > 0:
                                fee = size * p.exit_fee_per_share + (
                                    ZERO if pos["exit_fee_charged"] else p.exit_fee_per_order
                                )
                                if size * price < fee:
                                    reasons.append("UNDERLYING_EXIT_FEE_EXCEEDS_PROCEEDS")
                                    continue
                                self.cash += size * price - fee
                                pos["quantity"] -= size
                                pos["exit_fee_charged"] = True
                                used.add(identity)
                                fees += fee
                                turnover += size * price
                                fills.append(
                                    self.fill(
                                        q,
                                        at,
                                        "SELL",
                                        size,
                                        price,
                                        fee,
                                        pos["entry_client_id"],
                                        pos["exit_reason"],
                                    )
                                )
                                if not pos["quantity"]:
                                    self.position = None
                    pending = self.pending
                    if (
                        pending
                        and pending["intent"].instrument.contract.underlying == q.symbol
                        and q.source_at > pending["decision_at"]
                    ):
                        i = pending["intent"]
                        if q.bid <= i.original_underlying_invalidation:
                            pending["record"]["status"] = "CASH_STOP_BEFORE_FILL"
                            self.pending = None
                            continue
                        if (
                            q.bid < limits.minimum_underlying_price
                            or (q.ask - q.bid) / q.ask > limits.max_spread_fraction
                        ):
                            pending["observed"] = True
                            continue
                        price = _price(q, True, p, limits)
                        if q.ask_size is None and price <= pending["limit"]:
                            reasons.append("UNDERLYING_ENTRY_QUOTE_EVIDENCE_MISSING")
                            continue
                        pending["observed"] = True
                        identity = ("BUY", q.symbol, q.source, q.source_at)
                        size = 0 if identity in used else min(pending["quantity"], q.ask_size or 0)
                        if size and price <= pending["limit"]:
                            fee = size * p.entry_fee_per_share + p.entry_fee_per_order
                            debit = size * price + fee
                            self.cash -= debit
                            self.settled -= debit
                            fees += fee
                            turnover += size * price
                            used.add(identity)
                            self.position = {
                                "entry_client_id": i.client_id,
                                "symbol": q.symbol,
                                "quantity": size,
                                "stop": i.original_underlying_invalidation,
                                "exit_at": None,
                                "exit_reason": None,
                                "exit_fee_charged": False,
                            }
                            pending["record"].update(status="FILLED", quantity=size)
                            fills.append(
                                self.fill(
                                    q, at, "BUY", size, price, fee, i.client_id, "ELIGIBLE_CALL"
                                )
                            )
                            # One bounded entry fill; unused quantity is canceled, never added later.
                            self.pending = None
        expire()
        if self.position:
            reasons.append("UNDERLYING_OPEN_BOUNDARY_POSITION_UNVALUED")
        self.costs += allocation
        net = None if reasons else self.cash - start - allocation
        self.broken |= bool(reasons)
        return {
            "session": session.key,
            "status": "INCONCLUSIVE" if reasons else "COMPLETE",
            "reasons": sorted(set(reasons)),
            "opening_cash": str(start),
            "opening_settled_cash": str(opening_settled),
            "closing_cash": str(self.cash),
            "closing_settled_cash": str(self.settled),
            "closing_position": {
                k: v.isoformat()
                if hasattr(v, "isoformat")
                else str(v)
                if isinstance(v, Decimal)
                else v
                for k, v in self.position.items()
            }
            if self.position
            else None,
            "venue_cash_change": str(self.cash - start),
            "venue_fees": str(fees),
            "realized_price_pnl": str(self.cash - start + fees) if self.position is None else None,
            "turnover": str(turnover),
            "known_model_cost": "0",
            "allocated_data_cost": str(p.data_cost_per_session)
            if p.data_cost_per_session is not None
            else None,
            "allocated_host_cost": str(p.host_cost_per_session)
            if p.host_cost_per_session is not None
            else None,
            "net_change": str(net) if net is not None else None,
            "decisions": decisions,
            "fills": fills,
            "settlements": settled_receipts,
        }

    @staticmethod
    def fill(q, at, side, size, price, fee, entry, reason):
        return {
            "side": side,
            "symbol": q.symbol,
            "quantity": size,
            "price": str(price),
            "fee": str(fee),
            "occurred_at": at.isoformat(),
            "quote_hash": fingerprint(q),
            "entry_client_id": entry,
            "reason": reason,
        }


def underlying_report(bundle, tapes, recorded, arm_rows):
    """Reconstruct one separately enrolled account; incomplete sessions stay in denominator."""
    m, p = bundle.manifest, bundle.manifest.underlying_baseline
    if p is None:
        return {"status": "NOT_ENROLLED", "execution_authority": False}
    account = _Account(m.arms[0], p)
    by_session = {t.header.session_key: t for t in tapes or ()}
    rows, previous = [], None
    for s, arm_row in zip(m.sessions, arm_rows, strict=True):
        source = next((a for a in bundle.evidence if a.arm == "A" and a.session_key == s.key), None)
        receipts = [
            r
            for r in bundle.underlying_settlements
            if previous and previous < r.occurred_at <= s.opens_at
        ]
        source_ok = (
            recorded is not None
            and not recorded[s.key]
            and arm_row["arms"]["A"]["status"] == "COMPLETE"
        )
        row = account.session(s, source, by_session.get(s.key), receipts, source_ok)
        row["paired_net_difference"] = {
            arm: str(Decimal(value["net_change"]) - Decimal(row["net_change"]))
            if row["status"] == "COMPLETE" and arm_row["status"] == "COMPLETE"
            else None
            for arm, value in arm_row["arms"].items()
        }
        rows.append(row)
        previous = s.closes_at
    complete = all(r["status"] == "COMPLETE" for r in rows)
    changes = [Decimal(r["net_change"]) for r in rows] if complete else []
    equity = peak = m.arms[0].policy.capital
    drawdown = ZERO
    for change in changes:
        equity += change
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "version": p.version,
        "status": "COMPLETE_ARITHMETIC" if complete else "INCONCLUSIVE",
        "account_id": p.account_id,
        "population_id": p.population_id,
        "policy_hash": fingerprint(p),
        "capital": str(m.arms[0].policy.capital),
        "execution_authority": False,
        "live_enabled": False,
        "economic_conclusion": "INCONCLUSIVE",
        "planned_sessions": len(rows),
        "complete_sessions": sum(r["status"] == "COMPLETE" for r in rows),
        "sessions": rows,
        "worst_session": str(min(changes)) if changes else None,
        "session_boundary_drawdown": str(drawdown) if complete else None,
        "net_change": str(sum(changes, ZERO)) if complete else None,
        "net_return": str(sum(changes, ZERO) / m.arms[0].policy.capital) if complete else None,
        "limitations": [
            "A-approved CALL opportunity schedule, not an independent stock signal strategy",
            "Whole shares only; PUT and index opportunities remain cash",
            "First eligible entry quote fills once; unused entry quantity is canceled",
            "Underlying stop/time exits, not option premium or model management exits",
            "Explicit own settlement only; no borrowing or inferred reuse of proceeds",
            "Fixture observed size is not queue priority or a broker fill",
        ],
    }
