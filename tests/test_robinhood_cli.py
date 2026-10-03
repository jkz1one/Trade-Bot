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
