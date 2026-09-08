from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.config import Settings
from app.domain.models import Action, Candidate, MarketPacket, RiskDecision, TradeDecision
from app.risk.policy import drawdown_modifier, policy_for_equity
from app.risk.sizing import effective_loss_distance_fraction


def _confidence_modifier(confidence: float, setup_quality: float) -> Decimal:
    # Confidence is advisory, never a probability. It can only reduce size in Slice 1.
    score = Decimal(str(min(confidence, setup_quality)))
    return max(Decimal("0.50"), min(Decimal("1.00"), Decimal("0.50") + score / Decimal("2")))


def govern(
    decision: TradeDecision,
    packet: MarketPacket,
    settings: Settings,
    *,
    system_enabled: bool = True,
    broker_reconciled: bool = True,
    daily_entries: int = 0,
) -> RiskDecision:
    equity = packet.account.equity
    policy = policy_for_equity(equity)
    dd_mod = drawdown_modifier(packet.account.drawdown_fraction, policy.shutdown_drawdown_fraction)
    conf_mod = _confidence_modifier(decision.confidence, decision.setup_quality)
    reasons: list[str] = []
    hits: list[str] = []

    if decision.action == Action.CLOSE:
        reasons: list[str] = []
        if not broker_reconciled:
            reasons.append("BROKER_STATE_NOT_RECONCILED")
        if packet.account.position is None:
            reasons.append("NO_POSITION_TO_CLOSE")
        elif packet.account.position.symbol != decision.symbol:
            reasons.append("POSITION_SYMBOL_MISMATCH")
        candidate = next((c for c in packet.candidates if c.quote.symbol == decision.symbol), None)
        if candidate is None:
            reasons.append("SYMBOL_NOT_IN_PACKET")
            notional = Decimal("0")
        else:
            age = max(0.0, (datetime.now(timezone.utc) - candidate.quote.timestamp).total_seconds())
            if age > settings.quote_max_age_seconds:
                reasons.append("STALE_QUOTE")
            if candidate.quote.ask < candidate.quote.bid or candidate.quote.bid <= 0:
                reasons.append("INSANE_QUOTE")
            notional = (
                packet.account.position.quantity * candidate.quote.bid
                if packet.account.position is not None
                else Decimal("0")
            )
        approved = not reasons and notional > 0
        return RiskDecision(
            approved=approved,
            requested_notional=notional, approved_notional=notional if approved else Decimal("0"),
            planned_risk_dollars=Decimal("0"), planned_risk_fraction=Decimal("0"),
            effective_loss_distance=Decimal("0"), risk_mode=policy.name,
            drawdown_modifier=dd_mod, confidence_modifier=conf_mod,
            rejection_reasons=reasons,
        )

    if decision.action == Action.REDUCE:
        return RiskDecision(
            approved=False, requested_notional=Decimal("0"), approved_notional=Decimal("0"),
            planned_risk_dollars=Decimal("0"), planned_risk_fraction=Decimal("0"),
            effective_loss_distance=Decimal("0"), risk_mode=policy.name,
            drawdown_modifier=dd_mod, confidence_modifier=conf_mod,
            rejection_reasons=["REDUCE_NOT_IMPLEMENTED_SLICE1"],
        )

    if decision.action != Action.OPEN_LONG:
        return RiskDecision(
            approved=False,
            requested_notional=Decimal("0"), approved_notional=Decimal("0"),
            planned_risk_dollars=Decimal("0"), planned_risk_fraction=Decimal("0"),
            effective_loss_distance=Decimal("0"), risk_mode=policy.name,
            drawdown_modifier=dd_mod, confidence_modifier=conf_mod,
            rejection_reasons=["NO_ENTRY_REQUEST"],
        )

    if not system_enabled:
        reasons.append("SYSTEM_DISABLED")
    if settings.normalized_mode not in {"PAPER", "SHADOW", "LIVE"}:
        reasons.append("INVALID_RUNTIME_MODE")
    if settings.normalized_mode == "LIVE" and not settings.live_enabled:
        reasons.append("LIVE_NOT_DEPLOYMENT_ENABLED")
    if not broker_reconciled:
        reasons.append("BROKER_STATE_NOT_RECONCILED")
    if packet.account.position is not None:
        reasons.append("POSITION_ALREADY_OPEN")
        if packet.account.position.symbol == decision.symbol:
            reasons.append("AVERAGING_DOWN_PROHIBITED")
    if daily_entries >= settings.max_daily_entries:
        reasons.append("DAILY_ENTRY_LIMIT")
    if packet.account.drawdown_fraction >= policy.shutdown_drawdown_fraction:
        reasons.append("DRAWDOWN_SHUTDOWN")

    candidate: Candidate | None = next(
        (c for c in packet.candidates if c.quote.symbol == decision.symbol), None
    )
    if candidate is None:
        reasons.append("SYMBOL_NOT_IN_PACKET")
        effective = Decimal("0")
        requested = Decimal("0")
        approved = Decimal("0")
        risk_dollars = Decimal("0")
    else:
        q = candidate.quote
        now = datetime.now(timezone.utc)
        age = Decimal(str(max(0.0, (now - q.timestamp).total_seconds())))
        if age > settings.quote_max_age_seconds:
            reasons.append("STALE_QUOTE")
        if q.ask < q.bid or q.bid <= 0:
            reasons.append("INSANE_QUOTE")
        if not q.fractional_tradable:
            reasons.append("NOT_FRACTIONAL_TRADABLE")
        if decision.invalidation_price is None or decision.invalidation_price >= q.ask:
            reasons.append("INVALID_LONG_INVALIDATION")
            effective = Decimal("0")
        else:
            effective = effective_loss_distance_fraction(q, decision.invalidation_price, candidate.atr_fraction)

        advisory_requested = equity * Decimal(str(decision.desired_exposure_fraction))
        requested = advisory_requested
        if effective <= 0:
            approved = Decimal("0")
            risk_dollars = Decimal("0")
        else:
            risk_budget = equity * policy.max_risk_fraction * dd_mod * conf_mod
            raw_notional = risk_budget / effective
            exposure_cap = equity * policy.max_exposure_fraction
            approved = min(raw_notional, exposure_cap, packet.account.buying_power)
            if requested > 0 and approved < requested:
                hits.append("AGENT_NOTIONAL_CLIPPED")
            if requested > 0:
                approved = min(approved, requested)
            if approved < settings.min_order_notional:
                # Never round up the broker minimum if doing so violates risk/exposure constraints.
                minimum_risk = settings.min_order_notional * effective
                max_risk = risk_budget
                if (
                    settings.min_order_notional <= exposure_cap
                    and settings.min_order_notional <= packet.account.buying_power
                    and minimum_risk <= max_risk
                    and requested >= settings.min_order_notional
                ):
                    approved = settings.min_order_notional
                    hits.append("BROKER_MIN_NOTIONAL")
                else:
                    reasons.append("MIN_NOTIONAL_EXCEEDS_RISK_BUDGET")
                    approved = Decimal("0")
            risk_dollars = approved * effective

    approved_bool = not reasons and approved > 0
    return RiskDecision(
        approved=approved_bool,
        requested_notional=requested,
        approved_notional=approved if approved_bool else Decimal("0"),
        planned_risk_dollars=risk_dollars if approved_bool else Decimal("0"),
        planned_risk_fraction=(risk_dollars / equity if approved_bool and equity > 0 else Decimal("0")),
        effective_loss_distance=effective,
        risk_mode=policy.name,
        drawdown_modifier=dd_mod,
        confidence_modifier=conf_mod,
        constraint_hits=hits,
        rejection_reasons=reasons,
    )
