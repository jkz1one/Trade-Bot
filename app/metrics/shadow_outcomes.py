from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.domain.models import Action
from app.storage.models import ShadowForwardOutcomeRow


OUTCOME_POLICY = "v1-forward-quote-marks"
HORIZONS = (15, 60)
GRACE_MINUTES = 5


def aware(value: datetime) -> datetime:
    # SQLite strips timezone information from columns; stored timestamps are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _parse(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Outcome evidence requires timezone-aware timestamps")
    return result.astimezone(timezone.utc)


def _session(packet):
    context = packet.session_context
    if not context or context.get("calendar") != "XNYS":
        raise ValueError("Scheduled XNYS session context required")
    opens = _parse(context["regular_open"])
    closes = _parse(context["regular_close"])
    scheduled = _parse(context["scheduled_for"])
    if not opens <= scheduled <= packet.as_of < closes:
        raise ValueError("Packet is outside the scheduled session")
    return context["session_date"], closes, scheduled


def _quotes(packet, symbols, max_age):
    quotes = {c.quote.symbol: c.quote for c in packet.candidates}
    if any(symbol not in quotes for symbol in symbols):
        return None, "MISSING_QUOTES"
    selected = {symbol: quotes[symbol] for symbol in symbols}
    for quote in selected.values():
        if quote.timestamp.tzinfo is None or quote.timestamp.utcoffset() is None:
            return None, "INVALID_QUOTE_TIME"
        age = (packet.as_of - quote.timestamp).total_seconds()
        if not 0 <= age <= max_age:
            return None, "STALE_OR_FUTURE_QUOTES"
        if quote.bid > quote.ask:
            return None, "CROSSED_QUOTES"
    return selected, None


def record_forward_outcomes(
    session, cycle_id, packet, decision, risk, execution, *, reconciliation,
    model, usage, benchmark_symbol, quote_max_age_seconds, completed_at,
):
    """Observe prior proposals and register this cycle, inside its evidence transaction.

    Price references are decision-packet asks, not assumed execution-time fills.
    Later packet bids provide conservative spread-inclusive forward quote marks.
    No additional data/model/broker calls, synthetic orders or position ownership.
    """
    # First settle earlier baselines from this newly observed packet. Model failure
    # does not invalidate fresh market data; broker reconciliation failure does.
    pending = list(session.scalars(select(ShadowForwardOutcomeRow).where(
        ShadowForwardOutcomeRow.status == "PENDING",
        ShadowForwardOutcomeRow.source_cycle_id != cycle_id,
    )))
    for row in pending:
        baseline = json.loads(row.baseline_json)
        due = aware(row.due_at)
        expires = aware(row.expires_at)
        if packet.as_of >= expires:
            row.status = "EXPIRED"
            row.reason = "NO_FRESH_PAIR_BY_DEADLINE"
            continue
        if packet.as_of < due:
            continue
        if not reconciliation["reconciled"]:
            row.reason = "RECONCILIATION_FAILED"
            continue
        try:
            session_date, _, _ = _session(packet)
        except (KeyError, TypeError, ValueError):
            row.reason = "OUTSIDE_SCHEDULED_SESSION"
            continue
        if session_date != baseline["session_date"]:
            row.reason = "SESSION_MISMATCH"
            continue
        symbols = {baseline["benchmark_symbol"]}
        if baseline["kind"] == "REVIEWED_ENTRY":
            symbols.add(baseline["symbol"])
        quotes, reason = _quotes(packet, symbols, baseline["quote_max_age_seconds"])
        if reason:
            row.reason = reason
            continue
        available = _parse(baseline["decision_completed_at"])
        if any(q.timestamp < due or q.timestamp <= available for q in quotes.values()):
            row.reason = "QUOTE_BEFORE_FORWARD_TARGET"
            continue
        notional = Decimal(baseline["reference_notional"])
        benchmark = quotes[baseline["benchmark_symbol"]]
        benchmark_return = benchmark.bid / Decimal(baseline["benchmark_reference_ask"]) - 1
        mark_return = Decimal("0")
        if baseline["kind"] == "REVIEWED_ENTRY":
            mark_return = quotes[baseline["symbol"]].bid / Decimal(baseline["reference_ask"]) - 1
        model_cost = Decimal(baseline["model_cost"])
        net_return = mark_return - model_cost / notional
        row.status = "OBSERVED"
        row.reason = None
        row.measurement_cycle_id = cycle_id
        row.result_json = json.dumps({
            "observed_at": packet.as_of.isoformat(),
            "target_lateness_seconds": str((packet.as_of - due).total_seconds()),
            "quotes": {symbol: q.model_dump(mode="json") for symbol, q in quotes.items()},
            "quote_mark_return_fraction": str(mark_return),
            "benchmark_quote_mark_return_fraction": str(benchmark_return),
            "after_model_cost_return_fraction": str(net_return),
            "after_model_cost_excess_fraction": str(net_return - benchmark_return),
            "quote_mark_change_dollars": str(notional * mark_return),
            "after_model_cost_change_dollars": str(notional * mark_return - model_cost),
            "benchmark_quote_mark_change_dollars": str(notional * benchmark_return),
        })

    kind = ("REVIEWED_ENTRY" if decision.action == Action.OPEN_LONG else
            "CASH_HOLD" if decision.action == Action.HOLD and packet.account.position is None else None)
    reason = None
    if not reconciliation["reconciled"]:
        reason = "RECONCILIATION_FAILED"
    elif execution.agent_error:
        reason = "AGENT_FAILURE"
    elif model in {"stub", "session-guard"} or usage is None:
        reason = "NO_LINKED_MODEL_USAGE"
    elif execution.session_blocked:
        reason = "SESSION_BLOCKED"
    elif kind is None:
        reason = "UNSUPPORTED_ACTION_OR_POSITION"
    elif kind == "REVIEWED_ENTRY" and (
        not risk.approved or execution.broker_review is None or execution.review_error
    ):
        reason = "ENTRY_NOT_APPROVED_AND_REVIEWED"
    baseline = {
        "policy": OUTCOME_POLICY, "kind": kind, "symbol": decision.symbol,
        "benchmark_symbol": benchmark_symbol,
        "packet_as_of": packet.as_of.isoformat(),
        "decision_completed_at": completed_at.isoformat(),
        "quote_max_age_seconds": quote_max_age_seconds,
        "model_cost": str(usage.estimated_cost) if usage else None,
    }
    due_start = closes = None
    if reason is None:
        try:
            day, closes, due_start = _session(packet)
            if not packet.as_of <= completed_at < closes:
                raise ValueError("Decision was not available in its regular session")
            baseline["session_date"] = day
        except (KeyError, TypeError, ValueError):
            reason = "OUTSIDE_SCHEDULED_SESSION"
    if reason is None:
        symbols = {benchmark_symbol}
        if kind == "REVIEWED_ENTRY":
            symbols.add(decision.symbol)
        quotes, reason = _quotes(packet, symbols, quote_max_age_seconds)
        if quotes:
            amount = risk.approved_notional if kind == "REVIEWED_ENTRY" else packet.account.equity
            if not amount.is_finite() or amount <= 0:
                reason = "NO_POSITIVE_REFERENCE_NOTIONAL"
            else:
                baseline.update({
                    "reference_notional": str(amount),
                    "reference_ask": str(quotes[decision.symbol].ask) if kind == "REVIEWED_ENTRY" else None,
                    "benchmark_reference_ask": str(quotes[benchmark_symbol].ask),
                    "reference_quotes": {symbol: q.model_dump(mode="json") for symbol, q in quotes.items()},
                })
    for horizon in HORIZONS:
        due = due_start + timedelta(minutes=horizon) if due_start else None
        horizon_reason = reason
        if horizon_reason is None and (due >= closes or completed_at >= due):
            horizon_reason = "NO_FORWARD_WINDOW_IN_SESSION"
        expires = min(due + timedelta(minutes=GRACE_MINUTES), closes) if due and closes else None
        session.add(ShadowForwardOutcomeRow(
            source_cycle_id=cycle_id, horizon_minutes=horizon,
            status="EXCLUDED" if horizon_reason else "PENDING", reason=horizon_reason,
            due_at=due, expires_at=expires, baseline_json=json.dumps(baseline),
        ))


def forward_outcomes_report(repo, limit: int) -> dict:
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000")
    rows = repo.shadow_forward_outcomes(limit)
    outcomes = [{
        "source_cycle_id": r.source_cycle_id, "horizon_minutes": r.horizon_minutes,
        "status": r.status, "reason": r.reason,
        "due_at": aware(r.due_at).isoformat() if r.due_at else None,
        "expires_at": aware(r.expires_at).isoformat() if r.expires_at else None,
        "measurement_cycle_id": r.measurement_cycle_id,
        "baseline": json.loads(r.baseline_json),
        "result": json.loads(r.result_json) if r.result_json else None,
    } for r in rows]
    groups = []
    for horizon in HORIZONS:
        for kind in ("REVIEWED_ENTRY", "CASH_HOLD"):
            samples = [o for o in outcomes if o["horizon_minutes"] == horizon
                       and o["baseline"]["kind"] == kind and o["status"] == "OBSERVED"]
            if not samples:
                continue
            keys = ("quote_mark_return_fraction", "benchmark_quote_mark_return_fraction",
                    "after_model_cost_return_fraction", "after_model_cost_excess_fraction")
            means = {"mean_" + key: str(sum(
                (Decimal(o["result"][key]) for o in samples), Decimal("0")
            ) / len(samples)) for key in keys}
            groups.append({"horizon_minutes": horizon, "kind": kind,
                           "sample_count": len(samples), **means})
    return {
        "status": "OK" if rows else "EMPTY", "mode": "SHADOW",
        "window_limit_cycles": limit, "policy": OUTCOME_POLICY,
        "status_counts": dict(Counter(o["status"] for o in outcomes)),
        "reason_counts": dict(Counter(o["reason"] for o in outcomes if o["reason"])),
        "groups": groups, "outcomes": outcomes, "network_calls": False,
        "database_reported_model_cost": str(repo.model_cost_total()),
        "strategy_pnl": None, "economic_pnl": None,
        "measurement_note": "Decision-packet ask to later fresh bid quote marks, not fills. Cash HOLD marks zero price change. Fixed source notionals and linked source model cost only. Horizons/overlapping proposals are not independent samples or summed into portfolio/compounding return; fees, slippage and dividends are not modeled.",
    }
