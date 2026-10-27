"""Native snapshot reader authentication, freshness and no execution routes."""

import json
import os
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_connected_runtime import digest
from test_dashboard_snapshot import owner, publisher
from test_degen_options import AT
from test_option_observer import PASSWORD

from app.mixed import dashboard_reader as reader
from app.web.options import create_options_app


def setup(tmp_path, *, positions=False):
    source, _ = owner(tmp_path, positions=positions)
    directory = tmp_path / "dashboard"
    p = publisher(source, directory)
    try:
        p.publish()
        binding = p.binding
    finally:
        p.close()
    secret = tmp_path / "password"
    secret.write_text(PASSWORD + "\n")
    secret.chmod(0o600)
    return source, directory, binding, secret


@pytest.mark.parametrize("positions", [False, True])
def test_native_account_is_authenticated_current_read_only(tmp_path, positions, monkeypatch):
    source, directory, binding, secret = setup(tmp_path, positions=positions)
    before = digest(tmp_path)

    def forbidden(*_a, **_kw):
        pytest.fail("Execution/provider/model transport opened")

    monkeypatch.setattr("app.options.runtime_cli.existing_runtime", forbidden)
    monkeypatch.setattr("app.options.coordinator.model_key", forbidden)
    monkeypatch.setattr("app.options.read_capture.collect", forbidden)
    binding = reader.parse_binding(json.dumps(binding))
    app = reader.create_app(
        directory, binding, str(secret), clock_source=lambda: AT + timedelta(seconds=3)
    )
    with TestClient(app) as client:
        assert client.get("/").status_code == 401
        assert client.get("/api/mixed").status_code == 401
        client.auth = ("trader", PASSWORD)
        response = client.get("/api/mixed")
        assert response.status_code == 200
        data = response.json()
        assert data["accounting"] == "VERIFIED"
        assert len(data["positions"]) == data["fill_count"] == (2 if positions else 0)
        assert (
            not data["admin_enabled"]
            and not data["execution_authority"]
            and not data["live_enabled"]
        )
        assert "review" not in data
        html = client.get("/").text
        assert "Paused historical simulation" not in html
        assert client.post("/api/mixed").status_code == 405
        assert client.post("/api/portfolio/operator").status_code == 404
        assert client.get("/healthz").json()["trader_health"] == "NOT_CHECKED"
    assert digest(tmp_path) == before
    assert (source / "options.db").exists()


@pytest.mark.parametrize("damage", ["stale", "future", "binding", "receipt", "missing", "public"])
def test_each_authenticated_poll_rechecks_snapshot_and_recovers(tmp_path, damage):
    _, directory, binding, secret = setup(tmp_path)
    now = [AT + timedelta(seconds=3)]
    app = reader.create_app(directory, binding, str(secret), clock_source=lambda: now[0])
    path = directory / "options.db"
    original = path.read_bytes()
    with TestClient(app) as client:
        client.auth = ("trader", PASSWORD)
        assert client.get("/api/mixed").status_code == 200
        if damage == "stale":
            now[0] = AT + timedelta(seconds=33)
        elif damage == "future":
            now[0] = AT
        elif damage in ("binding", "receipt"):
            with sqlite3.connect(path) as db:
                record = json.loads(
                    db.execute("SELECT payload FROM dashboard_snapshot").fetchone()[0]
                )
                if damage == "binding":
                    record["binding_sha256"] = "0" * 64
                else:
                    record["checkpoint"]["feed_sequence"] += 1
                db.execute("UPDATE dashboard_snapshot SET payload=?", (json.dumps(record),))
        elif damage == "missing":
            path.unlink()
        else:
            path.chmod(0o644)
        assert client.get("/api/mixed").status_code == 503
        assert client.get("/").status_code == 503
        client.auth = None
        assert client.get("/api/mixed").status_code == 401
        path.write_bytes(original)
        path.chmod(0o600)
        now[0] = AT + timedelta(seconds=32)  # Exactly 30 seconds after publication.
        client.auth = ("trader", PASSWORD)
        assert client.get("/api/mixed").status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("reader_uid", -1),
        ("reader_gid", True),
        ("version", "other"),
        ("source_journal", "relative"),
        ("owner_configuration_sha256", "x"),
        ("population_id", ""),
    ],
)
def test_reader_binding_invalid_identity_rejected(tmp_path, field, value):
    _, _, binding, _ = setup(tmp_path)
    binding[field] = value
    with pytest.raises(ValueError):
        reader.parse_binding(json.dumps(binding))


def test_wrong_reader_identity_and_unexpected_fields_rejected(tmp_path):
    _, _, binding, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        reader.parse_binding(json.dumps(binding | {"reader_uid": os.getuid() + 1}))
    with pytest.raises(ValueError):
        reader.parse_binding(json.dumps(binding | {"operator_key_file": "/never"}))
    with pytest.raises(ValueError):
        reader.parse_binding(" " * 4097)


def test_guard_cannot_enable_admin_or_frozen_mode(tmp_path):
    _, directory, binding, secret = setup(tmp_path)
    for args in ({"operator_key_file": "/never"}, {"review_at": AT.isoformat()}, {"mixed": False}):
        with pytest.raises(ValueError):
            create_options_app(
                directory / "options.db",
                binding["population_id"],
                str(secret),
                stored_guard=lambda: None,
                **({"mixed": True} | args),
            )


def test_cli_errors_hide_raw_inputs_and_never_start_server(tmp_path, capsys, monkeypatch):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *_a, **_kw: pytest.fail("server started"))
    assert (
        reader.main(
            [
                "serve",
                "--directory",
                str(tmp_path),
                "--binding-json",
                "not-json-secret",
                "--password-file",
                "/never-password",
            ]
        )
        == 2
    )
    out = capsys.readouterr()
    assert "not-json-secret" not in out.out + out.err
    assert json.loads(out.out)["status"] == "UNAVAILABLE"


def test_reader_requires_verified_native_account_and_installed_release(tmp_path, monkeypatch):
    from types import SimpleNamespace

    _, directory, binding, secret = setup(tmp_path)
    monkeypatch.setattr(reader, "inspect_release", lambda: SimpleNamespace(status="MISMATCH"))
    with pytest.raises(ValueError, match="Installed"):
        reader.create_app(
            directory, binding, str(secret), clock_source=lambda: AT + timedelta(seconds=3)
        )
    monkeypatch.setattr(reader.MixedObserver, "report", lambda _self: {"status": "UNAVAILABLE"})
    with pytest.raises(ValueError, match="accounting"):
        reader.inspect(directory, binding, clock_source=lambda: AT + timedelta(seconds=3))
