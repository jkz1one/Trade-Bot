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
