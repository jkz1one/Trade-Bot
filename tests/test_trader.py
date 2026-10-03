import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agents import AgentOutputSchema, ModelBehaviorError, Runner

from app.agent.trader import OpenAIAgentsTrader, StubTraderAgent, fail_closed_agent_run
from app.domain.models import Action, TradeDecision


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


def _decision_payload(**updates):
    payload = StubTraderAgent().decide(None).decision.model_dump(mode="json")
    payload.update(updates)
    return payload


def test_actual_agents_sdk_wire_schema_has_no_decimal_regex():
    schema = AgentOutputSchema(TradeDecision).json_schema()
    schema_text = json.dumps(schema)
    assert '"pattern"' not in schema_text
    assert "minLength" not in schema_text
    assert "maxLength" not in schema_text
    assert "maxItems" not in schema_text
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    for field in ("invalidation_price", "target_price"):
        price_schema = json.dumps(schema["properties"][field])
        assert '"number"' in price_schema
        assert '"string"' in price_schema
        assert '"null"' in price_schema


@pytest.mark.parametrize("field", ["invalidation_price", "target_price"])
@pytest.mark.parametrize("value", ["123.456789123456789", 123.25, None])
def test_sdk_price_parsing_preserves_decimal_types_and_precision(field, value):
    decision = AgentOutputSchema(TradeDecision).validate_json(
        json.dumps(_decision_payload(**{field: value}))
    )
    parsed = getattr(decision, field)
    assert parsed == (None if value is None else Decimal(str(value)))
    assert parsed is None or isinstance(parsed, Decimal)


@pytest.mark.parametrize("field", ["invalidation_price", "target_price"])
@pytest.mark.parametrize("value", [0, -1, "0", "-1", "NaN", "Infinity", "garbage"])
def test_sdk_rejects_invalid_prices_after_wire_schema_override(field, value):
    with pytest.raises(ModelBehaviorError):
        AgentOutputSchema(TradeDecision).validate_json(
            json.dumps(_decision_payload(**{field: value}))
        )


@pytest.mark.parametrize("updates", [
    {"action": "OPEN_LONG", "symbol": "SPY", "invalidation_price": None},
    {"action": "OPEN_LONG", "symbol": None, "invalidation_price": "100"},
    {"confidence": 1.1},
    {"thesis": " "},
    {"why_now": "x" * 301},
    {"evidence": ["x"] * 7},
    {"risks": ["x"] * 7},
])
def test_sdk_still_enforces_application_limits(updates):
    with pytest.raises(ModelBehaviorError):
        AgentOutputSchema(TradeDecision).validate_json(
            json.dumps(_decision_payload(**updates))
        )


def test_real_trader_adapter_remains_toolless_single_turn(monkeypatch):
    from app.domain.models import AccountState, MarketPacket, utc_now

    packet = MarketPacket(
        as_of=utc_now(),
        account=AccountState(equity=10, cash=10, buying_power=10, high_watermark=10),
        candidates=[],
    )

    def fake_run(agent, prompt, *, max_turns):
        assert agent.tools == []
        assert agent.output_type is TradeDecision
        assert agent.model == "gpt-6-luna"
        assert max_turns == 1
        assert json.loads(prompt.split("\n", 1)[1]) == packet.model_dump(mode="json")
        decision = AgentOutputSchema(agent.output_type).validate_json(
            json.dumps(_decision_payload())
        )
        return SimpleNamespace(
            final_output=decision,
            context_wrapper=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=100, output_tokens=40)
            ),
        )

    monkeypatch.setattr(Runner, "run_sync", fake_run)
    run = OpenAIAgentsTrader("gpt-6-luna").decide(packet)
    assert run.decision.action == Action.HOLD
    assert (run.input_tokens, run.output_tokens) == (100, 40)
