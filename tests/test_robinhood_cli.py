import pytest

from app.config import Settings
from app.robinhood.cli import shadow_cycle


@pytest.mark.anyio
async def test_openai_shadow_preflight_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = await shadow_cycle(Settings(), "openai")
    assert code == 4
