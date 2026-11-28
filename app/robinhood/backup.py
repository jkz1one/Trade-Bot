from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.engine import make_url


def backup_database(settings, output):
    url = make_url(settings.robinhood_db_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("A file-backed SHADOW SQLite database is required")
    source = Path(url.database).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    if not source.is_file() or target == source:
        raise ValueError("Backup requires an existing database and a different output path")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".trade-bot-backup-", dir=target.parent)
    os.close(fd)
    try:
        with sqlite3.connect("file:" + quote(str(source)) + "?mode=ro", uri=True) as original:
            with sqlite3.connect(temporary) as snapshot:
                original.backup(snapshot)
                if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite backup integrity check failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


async def export_shadow_bootstrap(settings, output):
    """One-time private SSH transfer bundle; no secrets printed and no network calls."""
    from app.robinhood.cli import _configured_openai_key_problem, _repo
    from app.robinhood.client import JsonOAuthStorage
    from app.robinhood.service import ServiceLock

    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise ValueError("Choose a new output directory; existing exports are not overwritten")
    with ServiceLock(settings.shadow_service_lock_path):
        repo = _repo(settings)
        if repo.active_shadow_slot() is not None:
            raise RuntimeError("Inspect the active scheduled claim before exporting")
        if _configured_openai_key_problem(settings):
            raise ValueError("OpenAI key is not configured")
        storage = JsonOAuthStorage(settings.robinhood_oauth_storage)
        tokens = await storage.get_tokens()
        client = await storage.get_client_info()
        if not tokens or not tokens.access_token or not client or not client.client_id:
            raise ValueError("Robinhood OAuth state is not configured")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stage = Path(tempfile.mkdtemp(prefix=".trade-bot-export-", dir=destination.parent))
        try:
            backup_database(settings, stage / "robinhood.db")
            for name, content in (
                ("openai_api_key", os.environ["OPENAI_API_KEY"]),
                ("robinhood-oauth.json", storage.path.read_text()),
            ):
                path = stage / name
                path.write_text(content)
                path.chmod(0o600)
            os.replace(stage, destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return {"status": "OK", "output_directory": str(destination), "network_calls": False,
            "files": ["robinhood.db", "robinhood-oauth.json", "openai_api_key"]}
