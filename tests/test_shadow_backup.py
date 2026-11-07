import json
import os
import sqlite3
from pathlib import Path

import pytest

from app.robinhood.backup import backup_database, export_shadow_bootstrap
from app.robinhood.service import ServiceLock
from app.storage.db import make_engine, make_session_factory
from app.storage.repository import Repository
from tests.test_shadow_service import write_auth


def test_sqlite_backup_preserves_history_and_is_private(repo, settings, tmp_path):
    from app.domain.models import AccountState
    repo.save_account_snapshot(AccountState(equity=10, cash=10, buying_power=10, high_watermark=10))
    target = tmp_path / "backups" / "robinhood.db"
    settings = settings.model_copy(update={"robinhood_db_url": settings.db_url})
    assert backup_database(settings, target) == str(target)
    assert target.stat().st_mode & 0o777 == 0o600
    copied = Repository(make_session_factory(make_engine(f"sqlite:///{target}")))
    assert copied.latest_high_watermark() == 10
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(ValueError):
        backup_database(settings, Path(settings.db_url.removeprefix("sqlite:///")))


@pytest.mark.anyio
async def test_private_export_preserves_oauth_and_key_without_logging_them(repo, settings, tmp_path, monkeypatch, capsys):
    oauth = tmp_path / "oauth.json"
    write_auth(oauth)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-long-enough-for-tests")
    settings = settings.model_copy(update={
        "robinhood_db_url": settings.db_url, "robinhood_oauth_storage": str(oauth),
        "shadow_service_lock_path": str(tmp_path / "lock"),
    })
    destination = tmp_path / "export"
    result = await export_shadow_bootstrap(settings, destination)
    assert result["network_calls"] is False
    assert destination.stat().st_mode & 0o777 == 0o700
    assert {p.name for p in destination.iterdir()} == {"robinhood.db", "openai_api_key", "robinhood-oauth.json"}
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in destination.iterdir())
    assert (destination / "openai_api_key").read_text() == os.environ["OPENAI_API_KEY"]
    assert json.loads((destination / "robinhood-oauth.json").read_text()) == json.loads(oauth.read_text())
    assert "fake-key" not in json.dumps(result) + capsys.readouterr().out
    with pytest.raises(ValueError):
        await export_shadow_bootstrap(settings, destination)
    with ServiceLock(settings.shadow_service_lock_path):
        with pytest.raises(RuntimeError):
            await export_shadow_bootstrap(settings, tmp_path / "other-export")
    assert not (tmp_path / "other-export").exists()
