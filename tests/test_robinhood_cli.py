import pytest

from app.config import Settings
from app.robinhood.cli import _openai_key_problem, shadow_cycle


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
