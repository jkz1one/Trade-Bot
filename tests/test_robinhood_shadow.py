from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    Position,
    ExecutionResult,
    Quote,
    RiskDecision,
    TradeDecision,
)
from app.robinhood.models import RobinhoodTruth
from app.robinhood.shadow import ShadowOrchestrator
from app.robinhood.schedule import SessionWindow
from app.risk.governor import govern


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
@pytest.mark.parametrize("scenario", [
    "hold", "open", "failure", "mismatch", "review_failure",
    "scheduled_closed", "scheduled_expiry", "daily_limit", "exit_cooldown", "cooldown_expired",
])
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
    now = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        quote=Quote(symbol="SPY", timestamp=now,
                    bid=100, ask="100.01", last=100),
        atr_fraction="0.01", realized_vol_fraction="0.01",
    )
    entry = scenario not in {"hold", "failure"}
    decision = TradeDecision(
        action=Action.OPEN_LONG if entry else Action.HOLD,
        symbol="SPY" if entry else None,
        confidence=.8, setup_quality=.8, desired_exposure_fraction=.5,
        invalidation_price="98", thesis="Test supplied evidence",
        invalidation_reason="Test invalidation", why_now="Test rationale",
    )
    clock_now = now
    calls = []

    class UsageAgent:
        model_identifier = "gpt-6-luna"

        def decide(self, packet):
            nonlocal clock_now
            calls.append(1)
            if scenario == "scheduled_closed":
                raise AssertionError("Closed session must skip the model")
            if scenario == "scheduled_expiry":
                clock_now = now + timedelta(seconds=30)
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
        Settings(mode="SHADOW", max_daily_entries=1), repo, gateway,
        ExplodingAgent() if scenario == "failure" else UsageAgent(),
        clock=lambda: clock_now,
    )
    orchestrator.reads = Reads()
    orchestrator.market = Market()
    previous_saved = scenario in {"daily_limit", "exit_cooldown", "cooldown_expired"}
    if previous_saved:
        previous_packet = MarketPacket(
            as_of=now - timedelta(minutes=15 if scenario == "cooldown_expired" else 5),
            candidates=[candidate],
            account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
        )
        previous_decision = decision
        if scenario in {"exit_cooldown", "cooldown_expired"}:
            previous_packet.account.position = Position(
                symbol="SPY", quantity="0.04", entry_price=100, current_price=100,
                original_invalidation=98, thesis="previous position", opened_at=previous_packet.as_of,
            )
            previous_decision = decision.model_copy(update={"action": Action.CLOSE})
        previous_risk = govern(previous_decision, previous_packet, Settings(mode="SHADOW"))
        assert previous_risk.approved
        repo.save_shadow_cycle(
            previous_packet, previous_decision, previous_risk,
            ExecutionResult(status="SKIPPED", broker_review={}), "stub",
            prompt_version=TRADER_PROMPT_VERSION, latency_ms=0,
            input_tokens=0, output_tokens=0, input_price=Decimal("0.1"),
            output_price=Decimal("0.5"), benchmark_symbol="SPY",
            reconciliation={"reconciled": True, "reasons": []},
        )
    scheduled = scenario in {"scheduled_closed", "scheduled_expiry"}
    window = SessionWindow(
        now.date().isoformat(), now - timedelta(minutes=15),
        now - timedelta(seconds=1) if scenario == "scheduled_closed" else now + timedelta(seconds=20),
        now - timedelta(minutes=15),
    ) if scheduled else None
    if scheduled:
        assert repo.claim_shadow_slot(window, "test-owner", now)
    _, result, risk, execution, reconciliation, _ = await orchestrator.cycle(
        schedule_window=window, claim_token="test-owner" if scheduled else None,
    )
    rows = repo.recent_cycles()
    assert len(rows) == (2 if previous_saved else 1)
    row = rows[0]
    assert row.prompt_version == TRADER_PROMPT_VERSION
    assert row.model_identifier == ("session-guard" if scenario == "scheduled_closed" else "gpt-6-luna")
    assert json.loads(row.decision_json) == result.model_dump(mode="json")
    assert json.loads(row.execution_json) == execution.model_dump(mode="json")
    assert json.loads(row.packet_json)["account"]["buying_power"] == "10"
    assert repo.load_open_position() is None
    assert repo.benchmark_range("SPY") == (Decimal("100"), Decimal("100"))
    if scenario in {"open", "review_failure", "cooldown_expired"}:
        assert risk.approved
        assert [name for name, _ in gateway.calls] == ["review_equity_order"]
        if scenario != "review_failure":
            assert execution.status == "SKIPPED"
            assert execution.broker_review is not None
        else:
            assert execution.status == "REJECTED"
            assert execution.review_error == "RuntimeError"
            assert "private broker response" not in row.execution_json
            assert orchestrator.daily_entries == 0
    elif scenario == "scheduled_expiry":
        assert risk.approved
        assert gateway.calls == []
        assert execution.session_blocked
    else:
        assert gateway.calls == []
        assert not risk.approved
    if scenario in {"failure", "scheduled_closed"}:
        assert result.action == Action.HOLD
        assert execution.agent_error == ("RuntimeError" if scenario == "failure" else None)
        assert repo.latest_model_usage() is None
    else:
        assert repo.model_cost_total() == Decimal("0.00003000")
        assert execution.agent_error is None
    assert reconciliation.reconciled == (scenario != "mismatch")
    evidence = repo.shadow_cycle_evidence(row.id)
    assert evidence["status"] == "LINKED"
    assert evidence["reconciliation"]["reconciled"] == reconciliation.reconciled
    forward_rows = repo.shadow_forward_outcomes()
    assert len(forward_rows) == 2
    assert {o.source_cycle_id for o in forward_rows} == {row.id}
    # These synthetic scenarios are unscheduled or have no forward session window.
    assert {o.status for o in forward_rows} == {"EXCLUDED"}
    if scenario == "scheduled_closed":
        assert calls == []
        assert execution.session_blocked
    if scheduled:
        from app.metrics.shadow import shadow_history_report

        assert json.loads(row.packet_json)["session_context"] == window.context()
        assert repo.shadow_slot(window.key).status == "COMPLETED"
        assert repo.shadow_slot(window.key).cycle_id == row.id
        history = shadow_history_report(repo, "SPY", 100)
        assert history["session_blocked_count"] == 1
        assert history["deterministic_hold_count"] == (1 if scenario == "scheduled_closed" else 0)
        assert history["cycles"][0]["session_context"] == window.context()
    if scenario == "daily_limit":
        assert "DAILY_ENTRY_LIMIT" in risk.rejection_reasons
    if scenario == "exit_cooldown":
        assert "EXIT_COOLDOWN" in risk.rejection_reasons
