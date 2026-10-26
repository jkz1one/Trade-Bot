"""The host review script creates two native plays, then serves only frozen reads."""

import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.options import create_options_app


def test_installed_two_play_review_script_and_frozen_authenticated_page(tmp_path):
    root = Path(__file__).resolve().parents[1]
    directory = tmp_path / "ui-review-v3"
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-W",
            "error",
            str(root / "scripts/portfolio-dashboard-review.py"),
            "--output",
            str(directory),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    manifest = json.loads(run.stdout)
    assert manifest["held_plays"] == 2 and manifest["native_fill_receipts"] == 2
    assert manifest["as_of"] == "2026-10-09T14:00:02+00:00"
    assert not manifest["network_calls"] and not manifest["worker_running"]
    journal = directory / "options.db"
    before = hashlib.sha256(journal.read_bytes()).hexdigest()
    password = tmp_path / "fixture-dashboard-password"
    password.write_text("offline-review-password-123456789")
    password.chmod(0o600)
    app = create_options_app(
        journal, manifest["population_id"], password, mixed=True, review_at=manifest["as_of"]
    )
    with TestClient(app) as client:
        assert client.get("/").status_code == 401
        client.auth = ("trader", password.read_text())
        page = client.get("/")
        assert page.status_code == 200 and page.text.count("data-play-id=") == 2
        assert "Paused historical simulation" in page.text
        assert 'id="admin-dialog"' not in page.text
        assert '<strong>$599.94</strong><small>Original $599.94</small>' in page.text
        assert 'Original stop 599.94 · active stop 599.94' in page.text
        assert 'Stored bid 601.20' in page.text
        view = client.get("/api/mixed").json()
        assert view["review"]["mode"] == "FROZEN_OFFLINE_UI_FIXTURE"
        marks = [Decimal(p["gross_unrealized"]) for p in view["positions"]]
        assert min(marks) < 0 < max(marks)
        assert not view["live_enabled"] and not view["execution_authority"]
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == before == manifest["journal_sha256"]
