"""Installed create-only native review account and explicit frozen display clock."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.mixed.observer import MixedObserver
from app.web.options import create_options_app


@pytest.mark.parametrize("damage", ["ordinary", "legacy", "naive", "future", "clock"])
def test_frozen_review_cannot_silently_relabel_an_ordinary_account(tmp_path, damage):
    key = tmp_path / "key"
    key.write_text("offline-review-test-password")
    key.chmod(0o600)
    args = {"mixed": True, "review_at": "2026-10-09T15:00:06+00:00"}
    population = "ui-review-test"
    if damage == "ordinary":
        population = "ordinary-paper"
    elif damage == "legacy":
        args["mixed"] = False
    elif damage == "naive":
        args["review_at"] = "2026-10-09T15:00:06"
    elif damage == "future":
        args["review_at"] = "2999-10-09T15:00:06+00:00"
    else:
        args["clock"] = lambda: datetime(2026, 10, 9, tzinfo=UTC)
    with pytest.raises(ValueError):
        create_options_app(tmp_path / "absent.db", population, key, **args)
    assert not (tmp_path / "absent.db").exists()


def test_create_native_review_and_authenticated_frozen_reads_without_rewriting_clocks(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/mixed-dashboard-review.py"
    output = tmp_path / "review"
    command = [sys.executable, "-I", "-W", "error", str(script), "--output", str(output)]
    env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
    result = subprocess.run(
        command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=90, check=False
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["native_fill_receipts"] == 3
    assert manifest["cash"] == "803.64"
    assert manifest["equity_at_fixture_time"] == "1001.87"
    assert not manifest["live_enabled"] and not manifest["network_calls"]
    assert manifest["model_calls"] == 0 and not manifest["worker_running"]
    at = datetime.fromisoformat(manifest["as_of"])
    journal = output / "options.db"
    before = hashlib.sha256(journal.read_bytes()).hexdigest()
    key = tmp_path / "key"
    key.write_text("offline-review-test-password")
    key.chmod(0o600)
    app = create_options_app(
        journal, manifest["population_id"], key, mixed=True, review_at=manifest["as_of"]
    )
    with TestClient(app) as client:
        assert client.get("/").status_code == 401
        client.auth = ("trader", key.read_text())
        data = client.get("/api/mixed").json()
        assert data["review"]["mode"] == "FROZEN_OFFLINE_UI_FIXTURE"
        assert datetime.fromisoformat(data["observed_at"]) == at
        assert datetime.fromisoformat(data["position"]["quote_at"]) == at
        assert data["accounting"] == "VERIFIED" and data["position"]["active_stop"] == "95"
        assert any(p["equity"] is None for p in data["points"])
        html = client.get("/").text
        assert "Paused historical simulation" in html and "SIMULATED ACCOUNT" in html
        assert "No trading, live prices or paid model activity" in html
        assert client.post("/api/mixed").status_code == 405
    stale = MixedObserver(journal, manifest["population_id"]).report()
    assert stale["health"] == "STALE" and stale["equity"] is None
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == before
    again = subprocess.run(
        command, env=env, cwd=tmp_path, capture_output=True, timeout=20, check=False
    )
    assert again.returncode != 0 and b"FileExistsError" in again.stderr
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == before
