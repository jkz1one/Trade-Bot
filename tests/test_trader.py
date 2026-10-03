from app.agent.trader import StubTraderAgent, fail_closed_agent_run
from app.domain.models import Action


def test_stub_agent_abstains_without_fixture_language():
    decision = StubTraderAgent().decide(None).decision
    assert decision.action == Action.HOLD
    text = " ".join([
        decision.thesis,
        decision.invalidation_reason,
        decision.why_now,
        *decision.risks,
    ]).lower()
    assert "fixture" not in text
    assert "demo" not in text


def test_fail_closed_agent_run_records_error_class_only():
    run = fail_closed_agent_run(RuntimeError("secret detail"))
    assert run.decision.action == Action.HOLD
    assert run.error == "RuntimeError"
    assert "secret detail" not in run.decision.model_dump_json()



def test_trade_decision_wire_schema_avoids_unsupported_length_keywords():
    from app.domain.models import TradeDecision

    schema_text = str(TradeDecision.model_json_schema())
    assert "minLength" not in schema_text
    assert "maxLength" not in schema_text
    assert "maxItems" not in schema_text


def test_trade_decision_runtime_limits_still_enforced():
    import pytest
    from pydantic import ValidationError
    from app.domain.models import Horizon, TradeDecision

    with pytest.raises(ValidationError):
        TradeDecision(
            action=Action.HOLD,
            confidence=0,
            setup_quality=0,
            horizon=Horizon.INTRADAY,
            thesis="x" * 501,
            invalidation_reason="none",
            evidence=[],
            risks=[],
            why_now="hold",
        )
