from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.agent.prompts import TRADER_PROMPT_VERSION
from app.agent.trader import AgentRun, StubTraderAgent
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
from app.robinhood.models import RobinhoodTruth
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
    model_identifier = "gpt-6-luna"

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


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", ["hold", "open", "failure", "mismatch", "review_failure"])
async def test_complete_shadow_cycle_persists_evidence_and_gates_review(repo, scenario):
    import json

    truth = RobinhoodTruth.model_validate({
        "account": {
            "account_number": "RH1234", "type": "cash",
            "brokerage_account_type": "individual", "agentic_allowed": True,
            "state": "active", "deactivated": False, "permanently_deactivated": False,
        },
        "portfolio": {
            "total_value": "10", "equity_value": "0", "cash": "10",
            "buying_power": "10", "unleveraged_buying_power": "10",
            "unsupported_value": "1" if scenario == "mismatch" else "0",
        },
    })
    candidate = Candidate(
        quote=Quote(symbol="SPY", timestamp=datetime.now(timezone.utc),
                    bid=100, ask="100.01", last=100),
        atr_fraction="0.01", realized_vol_fraction="0.01",
    )
    decision = TradeDecision(
        action=Action.OPEN_LONG if scenario in {"open", "mismatch", "review_failure"} else Action.HOLD,
        symbol="SPY" if scenario in {"open", "mismatch", "review_failure"} else None,
        confidence=.8, setup_quality=.8, desired_exposure_fraction=.5,
        invalidation_price="98", thesis="Test supplied evidence",
        invalidation_reason="Test invalidation", why_now="Test rationale",
    )

    class UsageAgent:
        model_identifier = "gpt-6-luna"

        def decide(self, packet):
            return AgentRun(decision, input_tokens=100, output_tokens=40)

    class Reads:
        async def truth(self):
            return truth

    class Market:
        async def candidates(self, account_number, symbols):
            return [candidate]

        def regime(self, candidates):
            return "test"

    gateway = ReviewGateway()
    if scenario == "review_failure":
        async def failing_review(name, arguments):
            gateway.calls.append((name, arguments))
            raise RuntimeError("private broker response")
        gateway.call_safe = failing_review
    orchestrator = ShadowOrchestrator(
        Settings(mode="SHADOW"), repo, gateway,
        ExplodingAgent() if scenario == "failure" else UsageAgent(),
    )
    orchestrator.reads = Reads()
    orchestrator.market = Market()
    _, result, risk, execution, reconciliation, _ = await orchestrator.cycle()
    rows = repo.recent_cycles()
    assert len(rows) == 1
    row = rows[0]
    assert row.prompt_version == TRADER_PROMPT_VERSION
    assert row.model_identifier == "gpt-6-luna"
    assert json.loads(row.decision_json) == result.model_dump(mode="json")
    assert json.loads(row.execution_json) == execution.model_dump(mode="json")
    assert json.loads(row.packet_json)["account"]["buying_power"] == "10"
    assert repo.load_open_position() is None
    assert repo.benchmark_range("SPY") == (Decimal("100"), Decimal("100"))
    if scenario in {"open", "review_failure"}:
        assert risk.approved
        assert [name for name, _ in gateway.calls] == ["review_equity_order"]
        if scenario == "open":
            assert execution.status == "SKIPPED"
            assert execution.broker_review is not None
        else:
            assert execution.status == "REJECTED"
            assert execution.review_error == "RuntimeError"
            assert "private broker response" not in row.execution_json
            assert orchestrator.daily_entries == 0
    else:
        assert gateway.calls == []
        assert not risk.approved
    if scenario == "failure":
        assert result.action == Action.HOLD
        assert execution.agent_error == "RuntimeError"
        assert repo.latest_model_usage() is None
    else:
        assert repo.model_cost_total() == Decimal("0.00003000")
        assert execution.agent_error is None
    assert reconciliation.reconciled == (scenario != "mismatch")
    evidence = repo.shadow_cycle_evidence(row.id)
    assert evidence["status"] == "LINKED"
    assert evidence["reconciliation"]["reconciled"] == reconciliation.reconciled
