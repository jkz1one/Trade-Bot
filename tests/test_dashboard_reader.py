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


def test_publication_fault_visible_while_worker_protects_and_account_display_is_missing(tmp_path):
    from test_paper_session_report import module as reports
    from app.mixed.paper_health import evidence
    from app.options.engine import fingerprint

    source, directory, binding, secret = setup(tmp_path, positions=True)
    (directory / 'options.db').unlink()
    report = {'run_id': 'daily-20261028', 'window_end': AT.isoformat(),
              'current_runtime': [{'status': 'RUNNING'}],
              'current_control': [{'halted': True, 'halt_reason': 'CONNECTED_PUBLICATION_FAILED'}],
              'runtime_evidence': {'heartbeat': 'FRESH', 'feed': 'FRESH'},
              'publication_failures': [{'component': 'PUBLISHER', 'error_class': 'OSError'}]}
    report['operation'] = reports.operation(report, {'Status': 'running'})
    assert report['operation']['state'] == 'MISSING_INPUTS'
    assert report['operation']['reasons'] == ['CONNECTED_PUBLICATION_FAILED']
    health = evidence({'status': 'RUNNING'}, report, observed_at=AT.isoformat(),
                      binding_hash=fingerprint(binding))
    path = directory / 'paper-status.json'
    path.write_text(json.dumps(health))
    path.chmod(0o444)
    before = digest(source)
    app = reader.create_app(directory, binding, str(secret), clock_source=lambda: AT,
                            allow_degraded=True)
    with TestClient(app) as client:
        assert client.get('/desk/operation').status_code == 401
        client.auth = ('trader', PASSWORD)
        response = client.get('/desk/operation')
        assert response.status_code == 200
        assert 'Account display failed' in response.text
        assert 'position protection still requires valid data' in response.text
        assert client.get('/api/mixed').status_code == 503
    assert digest(source) == before


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


@pytest.mark.parametrize('status,halted,allowed', [
    ('STOPPED', 1, True), ('FAILED', 1, True), ('STOPPED', 0, False),
    ('RUNNING', 1, False), ('ENROLLED', 1, False),
])
def test_terminal_halted_records_remain_viewable_without_claiming_current_feed(tmp_path, status, halted, allowed):
    source, directory, binding, secret = setup(tmp_path)
    with sqlite3.connect(source / 'options.db') as db:
        db.execute('UPDATE execution_option_runtime SET status=? WHERE id=1', (status,))
        db.execute('UPDATE execution_control SET halted=?,halt_reason=? WHERE id=1',
                   (halted, 'OPTION_RUNTIME_STOPPED' if halted else None))
    p = publisher(source, directory, create=False)
    try:
        p.publish()
    finally:
        p.close()
    before = digest(tmp_path)
    now = AT + timedelta(days=3)
    if not allowed:
        with pytest.raises(ValueError, match='Recent snapshot'):
            reader.inspect(directory, binding, clock_source=lambda: now)
    else:
        result = reader.inspect(directory, binding, clock_source=lambda: now)
        assert result['publication_state'] == 'STOPPED_RECORDS'
        assert result['stored_runtime'] == {'status': status, 'halted': True}
        assert result['publication_age_seconds'] > 30
        with TestClient(reader.create_app(directory, binding, str(secret), clock_source=lambda: now)) as client:
            assert client.get('/api/mixed').status_code == 401
            client.auth = ('trader', PASSWORD)
            data = client.get('/api/mixed').json()
            assert data['halted'] and data['age_seconds'] > 30
            assert data['health'] != 'FRESH'
            assert 'Showing the last available records.' in client.get('/').text
        with pytest.raises(ValueError, match='Recent snapshot'):
            reader.guard(directory, binding, clock_source=lambda: AT)
    assert digest(tmp_path) == before


def test_failure_visible_with_or_without_account_snapshot_and_login_required(tmp_path):
    from app.mixed.paper_health import evidence
    from app.options.engine import fingerprint

    _, directory, binding, secret = setup(tmp_path)
    at = AT + timedelta(seconds=3)
    now = [at]
    report = {"run_id": "daily-20261110", "window_end": at.isoformat(),
              "operation": {"state": "FAILED"}, "session_timing": {"elapsed_seconds": 802.3},
              "worker_exit": {"failures": [{"component": "RUNTIME", "error_class": "FixtureProcessTimeout"}]},
              "runtime_evidence": {"feed": "STALE", "heartbeat": "STALE"},
              "run_execution": {"entry_fills": 0, "exit_fills": 0}}
    record = evidence({"status": "FAILED", "reasons": ["SESSION_STOPPED_REVIEW_REQUIRED"]},
                      report, observed_at=at.isoformat(), binding_hash=fingerprint(binding))
    path = directory / "paper-status.json"
    path.write_text(json.dumps(record))
    path.chmod(0o444)
    app = reader.create_app(directory, binding, str(secret), clock_source=lambda: now[0])
    with TestClient(app) as client:
        assert all(client.get(url).status_code == 401 for url in ("/", "/desk/operation", "/desk-operation.js"))
        client.auth = ("trader", PASSWORD)
        for url in ("/", "/desk/operation"):
            response = client.get(url)
            assert response.status_code == 200
            assert 'data-state="FAILED"' in response.text and "13m 22s" in response.text
            assert "Local simulation subprocess timed out" in response.text
        (directory / "options.db").unlink()
        assert client.get("/api/mixed").status_code == 503
        page = client.get("/")
        assert page.status_code == 503 and "Current positions and balances are unknown" in page.text
        assert "13m 22s" in page.text
        now[0] += timedelta(minutes=4)
        assert "Controller updates have stopped" in client.get("/desk/operation").text
        path.unlink()
        assert "Status unavailable" in client.get("/desk/operation").text


@pytest.mark.parametrize("replacement", ["verified", "damaged", "repeated"])
def test_atomic_publication_during_account_read_reopens_and_verifies_one_generation(
    tmp_path, monkeypatch, replacement
):
    import shutil
    from app.mixed.observer import MixedObserver

    _, directory, binding, secret = setup(tmp_path)
    now = lambda: AT + timedelta(seconds=3)
    app = reader.create_app(directory, binding, str(secret), clock_source=now)
    path = directory / "options.db"
    next_file = directory / "replacement.db"
    shutil.copyfile(path, next_file)
    next_file.chmod(0o600)
    if replacement == "damaged":
        with sqlite3.connect(next_file) as db:
            raw = json.loads(db.execute("SELECT payload FROM dashboard_snapshot").fetchone()[0])
            raw["binding_sha256"] = "0" * 64
            db.execute("UPDATE dashboard_snapshot SET payload=?", (json.dumps(raw),))
    original = MixedObserver._snapshot
    replaced = []
    def project(self, db, *args):
        value = original(self, db, *args)
        if not replaced or replacement == "repeated":
            if replaced:
                shutil.copyfile(path, next_file)
                next_file.chmod(0o600)
            os.replace(next_file, path)
            replaced.append(True)
        return value
    monkeypatch.setattr(MixedObserver, "_snapshot", project)
    with TestClient(app) as client:
        client.auth = ("trader", PASSWORD)
        response = client.get("/api/mixed")
    assert len(replaced) == (2 if replacement == "repeated" else 1)
    assert response.status_code == (200 if replacement == "verified" else 503)
    if replacement == "verified":
        assert response.json()["accounting"] == "VERIFIED"
