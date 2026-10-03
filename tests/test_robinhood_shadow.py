from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.agent.trader import StubTraderAgent
from app.config import Settings
from app.domain.models import (
    AccountState,
    Action,
    Candidate,
    Horizon,
    MarketPacket,
    Quote,
    RiskDecision,
    TradeDecision,
)
from app.robinhood.shadow import ShadowOrchestrator


class ReviewGateway:
    def __init__(self):
        self.calls = []

    async def call_safe(self, name, arguments):
        self.calls.append((name, arguments))
        assert name == "review_equity_order"
        return {"structuredContent": {"data": {
            "symbol": "QQQ",
            "side": "buy",
            "type": "market",
            "dollar_amount": arguments["dollar_amount"],
            "order_checks": {},
            "quote_data": {"symbol": "QQQ"},
        }}}


@pytest.mark.anyio
async def test_shadow_review_never_places_order(repo):
    settings = Settings(mode="SHADOW", live_enabled=False, db_url="sqlite://")
    gateway = ReviewGateway()
    orchestrator = ShadowOrchestrator(
        settings,
        repo,
        gateway,
        StubTraderAgent(),
    )
    quote = Quote(
        symbol="QQQ",
        timestamp=datetime.now(timezone.utc),
        bid=Decimal("100"),
        ask=Decimal("100.01"),
        last=Decimal("100"),
        fractional_tradable=True,
    )
    packet = MarketPacket(
        as_of=datetime.now(timezone.utc),
        account=AccountState(
            equity=Decimal("10"),
            cash=Decimal("10"),
            buying_power=Decimal("10"),
            high_watermark=Decimal("10"),
        ),
        candidates=[Candidate(
            quote=quote,
            atr_fraction=Decimal("0.01"),
            realized_vol_fraction=Decimal("0.01"),
        )],
    )
    decision = TradeDecision(
        action=Action.OPEN_LONG,
        symbol="QQQ",
        confidence=.8,
        setup_quality=.8,
        horizon=Horizon.INTRADAY,
        desired_exposure_fraction=.5,
        invalidation_price=Decimal("98"),
        thesis="t",
        invalidation_reason="i",
        why_now="n",
    )
    risk = RiskDecision(
        approved=True,
        requested_notional=Decimal("5"),
        approved_notional=Decimal("4"),
        planned_risk_dollars=Decimal("0.08"),
        planned_risk_fraction=Decimal("0.008"),
        effective_loss_distance=Decimal("0.02"),
        risk_mode="MICRO",
        drawdown_modifier=Decimal("1"),
        confidence_modifier=Decimal("0.9"),
    )
    execution = await orchestrator._review(decision, risk, packet, "RH1")
    assert execution.status == "SKIPPED"
    assert execution.broker_review is not None
    assert [name for name, _ in gateway.calls] == ["review_equity_order"]


class ExplodingAgent:
    def decide(self, packet):
        raise RuntimeError("simulated model outage")


@pytest.mark.anyio
async def test_agent_failure_becomes_fail_closed_hold(repo):
    settings = Settings(mode="SHADOW", live_enabled=False, db_url="sqlite://")
    orchestrator = ShadowOrchestrator(
        settings,
        repo,
        ReviewGateway(),
        ExplodingAgent(),
    )
    packet = MarketPacket(
        as_of=datetime.now(timezone.utc),
        account=AccountState(
            equity=Decimal("10"),
            cash=Decimal("10"),
            buying_power=Decimal("10"),
            high_watermark=Decimal("10"),
        ),
        candidates=[],
    )
    run = await orchestrator._decide(packet)
    assert run.error == "RuntimeError"
    assert run.decision.action == Action.HOLD
    assert run.decision.confidence == 0
