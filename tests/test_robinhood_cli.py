import pytest

from app.config import Settings
from app.robinhood.cli import _openai_error_summary, _openai_key_problem, shadow_audit, shadow_cycle


@pytest.mark.anyio
async def test_openai_shadow_preflight_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = await shadow_cycle(Settings(), "openai")
    assert code == 4



def test_openai_key_preflight_rejects_example_placeholder():
    assert _openai_key_problem("YOUR_API_KEY") is not None
    assert _openai_key_problem("your-key-here") is not None


def test_openai_key_preflight_accepts_nonplaceholder_secret_shape():
    assert _openai_key_problem("sk-proj-example-but-long-enough-value") is None



def test_shadow_audit_reports_empty_database(tmp_path, capsys):
    settings = Settings(robinhood_db_url=f"sqlite:///{tmp_path / 'audit.db'}")
    code = shadow_audit(settings)
    assert code == 5
    assert '"status": "EMPTY"' in capsys.readouterr().out



class _FakeOpenAIError(Exception):
    status_code = 401
    body = {"code": "invalid_api_key", "type": "invalid_request_error"}


def test_openai_error_summary_distinguishes_invalid_key():
    summary = _openai_error_summary(_FakeOpenAIError())
    assert summary["status_code"] == 401
    assert summary["error_code"] == "invalid_api_key"
    assert "Create a new secret key" in summary["next_step"]



class _FakeSchemaError(Exception):
    status_code = 400
    body = {
        "code": "invalid_json_schema",
        "type": "invalid_request_error",
        "message": "Invalid schema: unsupported keyword maxLength",
    }


def test_openai_error_summary_does_not_treat_all_invalid_requests_as_bad_keys():
    summary = _openai_error_summary(_FakeSchemaError())
    assert summary["status_code"] == 400
    assert summary["error_code"] == "invalid_json_schema"
    assert "maxLength" in summary["message"]
    assert "Create a new secret key" not in summary["next_step"]


@pytest.mark.parametrize("action, expected_code", [("HOLD", 0), ("CLOSE", 7)])
def test_structured_check_requires_hold_and_never_connects_to_robinhood(
    monkeypatch, capsys, action, expected_code,
):
    import json
    from types import SimpleNamespace
    from agents import AgentOutputSchema, Runner
    from app.agent.trader import StubTraderAgent
    from app.domain.models import TradeDecision
    from app.robinhood import cli

    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-long-enough-value")

    def forbidden_connection(*args):
        raise AssertionError("Schema check must not connect to Robinhood")

    def run(agent, prompt, *, max_turns):
        assert agent.output_type is TradeDecision
        assert agent.tools == []
        assert max_turns == 1
        payload = StubTraderAgent().decide(None).decision.model_dump(mode="json")
        payload.update(action=action, symbol="SPY" if action == "CLOSE" else None)
        return SimpleNamespace(final_output=AgentOutputSchema(TradeDecision).validate_json(
            json.dumps(payload)
        ))

    monkeypatch.setattr(cli, "_connection", forbidden_connection)
    monkeypatch.setattr(Runner, "run_sync", run)
    assert cli.openai_structured_check(Settings()) == expected_code
    payload = json.loads(capsys.readouterr().out)
    assert payload["robinhood_touched"] is False
    assert payload["structured_output"] == (expected_code == 0)


@pytest.mark.anyio
@pytest.mark.parametrize("agent_error, expected_code", [(None, 0), ("BadRequestError", 8)])
async def test_shadow_cli_distinguishes_genuine_hold_from_failed_agent(
    monkeypatch, tmp_path, capsys, agent_error, expected_code,
):
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from app.agent.trader import StubTraderAgent
    from app.domain.models import ExecutionResult
    from app.robinhood import cli

    @asynccontextmanager
    async def client():
        yield object()

    class Orchestrator:
        def __init__(self, settings, repo, gateway, agent):
            assert settings.normalized_mode == "SHADOW"
            assert not settings.live_enabled

        async def cycle(self):
            return (
                SimpleNamespace(candidates=[], regime="test"),
                StubTraderAgent().decide(None).decision,
                ExecutionResult(status="SKIPPED"),
                ExecutionResult(status="SKIPPED", agent_error=agent_error),
                SimpleNamespace(reconciled=True, reasons=[]),
                SimpleNamespace(account=SimpleNamespace(account_number="RH1234")),
            )

    monkeypatch.setattr(cli, "_connection", lambda settings: SimpleNamespace(client=client))
    monkeypatch.setattr(cli, "ShadowOrchestrator", Orchestrator)
    code = await cli.shadow_cycle(
        Settings(robinhood_db_url=f"sqlite:///{tmp_path / 'shadow.db'}"), "stub",
    )
    assert code == expected_code
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution"]["agent_error"] == agent_error
