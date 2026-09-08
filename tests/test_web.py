from pathlib import Path
from fastapi.testclient import TestClient


def test_dashboard_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADER_DB_URL", f"sqlite:///{tmp_path/'web.db'}")
    monkeypatch.setenv("TRADER_MODE", "PAPER")
    from app import config
    config.get_settings.cache_clear()
    from app.main import create_app
    app = create_app()
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "AUTONOMOUS TRADER" in r.text
    assert "MICRO" in r.text
    assert "SPY benchmark" in r.text
    r = client.post("/cycle", follow_redirects=True)
    assert r.status_code == 200
    assert "HOLD" in r.text


def test_slice1_rejects_shadow_and_live(monkeypatch, tmp_path):
    import pytest
    from app import config
    from app.main import create_app
    for mode in ("SHADOW", "LIVE"):
        monkeypatch.setenv("TRADER_DB_URL", f"sqlite:///{tmp_path/(mode.lower()+'.db')}")
        monkeypatch.setenv("TRADER_MODE", mode)
        config.get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="PAPER mode only"):
            create_app()
    monkeypatch.setenv("TRADER_MODE", "PAPER")
    config.get_settings.cache_clear()
