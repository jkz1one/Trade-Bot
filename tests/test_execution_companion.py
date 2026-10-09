"""Companion startup must not recover, mutate or displace the trading owner."""

import asyncio
import json
import os
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest

from app.config import Settings
from app.execution import control_cli
from app.execution.control_api import ControlAPIConfig, create_control_app
from app.execution.engine import ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.operator import OperatorCommand, OperatorControl, sign_command
from app.execution.runtime import runtime_lease
from app.execution.runtime_cli import initialize, load
from app.execution.runtime_cli import main as runtime_main
from tests.test_execution_alert_delivery import certificate as certificate
from tests.test_execution_control_api import KEY, TOKEN, secret
from tests.test_execution_rehearsal import NOW, decision, packet


def context(tmp_path, *, fenced=True):
    engine = ExecutionEngine(
        tmp_path / "execution.db",
        Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10),
    )
    venue = LocalFixtureVenue(10)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    OperatorControl.enroll(engine, KEY, now=NOW)
    if fenced:
        engine.journal.enable_restore_fence(now=NOW)
    signing, token = tmp_path / "signing.key", tmp_path / "read.token"
    secret(signing, KEY.hex())
    secret(token, TOKEN)
    return engine, signing, token


def pair(engine):
    p = engine.journal.path
    return [p.read_bytes(), Path(str(p) + ".authority.db").read_bytes()]


def submitting(engine):
    intent = engine.prepare("in-flight", decision(), packet(), now=NOW)
    with engine.journal.write() as db:
        db.execute(
            "UPDATE execution_orders SET status='SUBMITTING',attempted_at=? WHERE client_id=?",
            (NOW.isoformat(), intent.client_id),
        )
    return intent


@pytest.mark.parametrize("status", ("PREPARED", "SUBMITTING", "UNKNOWN"))
def test_companion_attachment_preserves_reservations_halt_and_pair_bytes(tmp_path, status):
    engine, signing, token = context(tmp_path)
    intent = submitting(engine)
    with engine.journal.write() as db:
        db.execute("UPDATE execution_orders SET status=?", (status,))
        engine._halt(db, "RETAINED_OPERATOR_HALT", NOW)
    before = pair(engine)
    attached = ExecutionEngine.attach_existing(engine.journal.path)
    assert pair(engine) == before
    assert attached.settings.normalized_mode == "PAPER" and not attached.settings.live_enabled
    app = create_control_app(
        attached,
        ControlAPIConfig(origin="https://127.0.0.1:8788"),
        operator_key_file=signing,
        read_token_file=token,
        clock=lambda: NOW,
    )
    assert {route.path for route in app.routes} == {"/v1/review", "/v1/commands"}
    report = attached.journal.report(now=NOW)
    assert report["orders"][0]["status"] == status and report["halted"]
    assert report["orders"][0]["intent"]["client_id"] == intent.client_id
    assert report["restore_fence"]["status"] == "VERIFIED" and pair(engine) == before


def test_owner_constructor_still_recovers_interrupted_submission(tmp_path):
    engine, _, _ = context(tmp_path)
    submitting(engine)
    reopened = ExecutionEngine(engine.journal.path, engine.settings, limits=engine.limits)
    report = reopened.journal.report(now=NOW)
    assert report["halted"] and report["orders"][0]["status"] == "UNKNOWN"
    assert report["restore_fence"]["status"] == "VERIFIED"


@pytest.mark.parametrize(
    "fault",
    ("missing", "unfenced", "authority", "rollback", "foreign", "hash", "extra", "mode", "symlink"),
)
def test_attachment_fails_without_creating_or_repairing_evidence(tmp_path, fault):
    engine, _, _ = context(tmp_path, fenced=fault != "unfenced")
    path = engine.journal.path
    authority = Path(str(path) + ".authority.db")
    if fault == "missing":
        path = tmp_path / "missing" / "execution.db"
    elif fault == "authority":
        authority.unlink()
    elif fault == "rollback":
        old = path.read_bytes()
        engine.halt("NEWER_RETAINED_STATE", now=NOW)
        path.write_bytes(old)
    elif fault == "foreign":
        other = tmp_path / "other"
        other.mkdir()
        second, _, _ = context(other)
        authority.write_bytes(Path(str(second.journal.path) + ".authority.db").read_bytes())
    elif fault in {"hash", "extra"}:
        with engine.journal.write() as db:
            config = json.loads(
                db.execute("SELECT config_json FROM execution_control").fetchone()[0]
            )
            config["risk_policy_hash" if fault == "hash" else "unrecognized_policy"] = "bad"
            db.execute("UPDATE execution_control SET config_json=?", (json.dumps(config),))
    elif fault == "mode":
        path.chmod(0o644)
    elif fault == "symlink":
        link = tmp_path / "alias.db"
        link.symlink_to(path)
        path = link
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        ExecutionEngine.attach_existing(path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert not (tmp_path / "missing").exists()


def test_attached_writer_still_checks_retained_authority_before_mutation(tmp_path):
    engine, _, _ = context(tmp_path)
    attached = ExecutionEngine.attach_existing(engine.journal.path)
    Path(str(engine.journal.path) + ".authority.db").unlink()
    before = engine.journal.path.read_bytes()
    with pytest.raises(ValueError, match="AUTHORITY_MISSING"):
        attached.halt("cannot bypass lost authority", now=NOW)
    assert before == engine.journal.path.read_bytes()


def test_attachment_uses_frozen_limits_and_cannot_promote_from_environment(tmp_path, monkeypatch):
    engine, _, _ = context(tmp_path)
    monkeypatch.setenv("TRADER_MODE", "LIVE")
    monkeypatch.setenv("TRADER_LIVE_ENABLED", "true")
    monkeypatch.setenv("TRADER_STARTING_CAPITAL", "9999")
    attached = ExecutionEngine.attach_existing(engine.journal.path)
    assert attached.settings.starting_capital == 10
    assert attached.limits == engine.limits and not attached.settings.live_enabled


def test_new_population_operator_opt_in_is_private_and_explicit(tmp_path, capsys):
    signing = tmp_path / "signing.key"
    secret(signing, KEY.hex())
    new = tmp_path / "new"
    assert (
        runtime_main(
            [
                "init",
                "--directory",
                str(new),
                "--capital",
                "10",
                "--symbols",
                "SPY",
                "--operator-key-file",
                str(signing),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert KEY.hex() not in output
    with runtime_lease(new / "execution.db"):
        runtime = load(new)
    review = OperatorControl(runtime.engine, KEY).review_summary(now=NOW)
    assert review["operator_credential_generation"] == 1
    before = pair(runtime.engine)
    ExecutionEngine.attach_existing(new / "execution.db")
    assert pair(runtime.engine) == before
    old = tmp_path / "old"
    initialize(old, capital=10, symbols=["SPY"])
    with sqlite3.connect(old / "execution.db") as db:
        assert db.execute("SELECT count(*) FROM execution_operator").fetchone()[0] == 0
    signing.chmod(0o644)
    with pytest.raises(ValueError):
        initialize(tmp_path / "invalid", capital=10, symbols=["SPY"], operator_key_file=signing)
    assert not (tmp_path / "invalid").exists()


@pytest.mark.anyio
async def test_companion_attaches_during_actual_submission_without_recovering_it(tmp_path):
    from app.execution.durable_fixture import DurableFixtureVenue
    from app.execution.models import ExecutionLimits
    from tests.test_execution_supervisor import wait_until

    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(
        tmp_path / "engine.db",
        settings,
        limits=ExecutionLimits(
            max_entry_notional=10,
            max_position_notional=10,
            total_loss_limit=10,
            daily_loss_limit=10,
            process_timeout_seconds=2,
        ),
    )
    venue = DurableFixtureVenue(tmp_path / "venue.db", capital=10, fault="STALL_AFTER_ACCEPT")
    engine.journal.enable_restore_fence(now=NOW)
    await engine.reconcile_fixture(venue, now=NOW)
    intent = engine.prepare("actual-child", decision(), packet(), now=NOW)
    attempt = asyncio.create_task(
        engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet())
    )
    await wait_until(lambda: venue.submit_count == 1)
    before = pair(engine)
    attached = ExecutionEngine.attach_existing(engine.journal.path)
    assert attached.journal.report(now=NOW)["orders"][0]["status"] == "SUBMITTING"
    assert not attached.journal.report(now=NOW)["halted"] and pair(engine) == before
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert engine.journal.report(now=NOW)["orders"][0]["status"] == "UNKNOWN"


def arguments(engine, signing, token, certificate, port=8788):
    cert, tls_key = certificate
    return dict(
        journal=engine.journal.path,
        origin=f"https://127.0.0.1:{port}",
        operator_key_file=signing,
        read_token_file=token,
        certfile=cert,
        keyfile=tls_key,
        host="127.0.0.1",
        port=port,
    )


def test_control_lock_is_distinct_from_runtime_and_retained_through_server_return(
    tmp_path, certificate, monkeypatch
):
    engine, signing, token = context(tmp_path)
    before = pair(engine)
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    observed = []

    class Server:
        def __init__(self, config):
            assert not config.proxy_headers and config.workers == 1 and config.ws == "none"
            assert config.ssl is not None and config.ssl.minimum_version >= ssl.TLSVersion.TLSv1_2
            # TLS peer-close must fit inside application drain and the fixed host cgroup bound.
            assert asyncio.constants.SSL_SHUTDOWN_TIMEOUT < config.timeout_graceful_shutdown < 45

        def handle_exit(self, *args):
            pass

        def run(self):
            with pytest.raises(control_cli.ControlAlreadyRunning):
                with control_cli.control_lease(engine.journal.path):
                    pass
            with runtime_lease(engine.journal.path):
                pass
            observed.append(True)

    monkeypatch.setattr(control_cli.uvicorn, "Server", Server)
    control_cli.serve(**arguments(engine, signing, token, certificate))
    with control_cli.control_lease(engine.journal.path):
        pass
    assert observed == [True] and pair(engine) == before
    assert previous == {s: signal.getsignal(s) for s in previous}


@pytest.mark.parametrize(
    "fault",
    (
        "no-enrollment",
        "wrong-key",
        "tls-key-mode",
        "tls-symlink",
        "http",
        "host",
        "port",
        "tls-mismatch",
    ),
)
def test_control_startup_rejects_bad_authority_or_transport_before_serving(
    tmp_path, certificate, monkeypatch, fault
):
    engine, signing, token = context(tmp_path)
    opts = arguments(engine, signing, token, certificate)
    if fault == "no-enrollment":
        with engine.journal.write() as db:
            db.execute("DELETE FROM execution_operator")
    elif fault == "wrong-key":
        secret(signing, "99" * 32)
    elif fault in {"tls-key-mode", "tls-symlink"}:
        key = tmp_path / "tls.key"
        if fault == "tls-symlink":
            key.symlink_to(certificate[1])
        else:
            key.write_bytes(certificate[1].read_bytes())
            key.chmod(0o644)
        opts["keyfile"] = key
    elif fault == "tls-mismatch":
        opts["keyfile"] = signing
    elif fault == "http":
        opts["origin"] = "http://127.0.0.1:8788"
    elif fault == "host":
        opts["host"] = "from-env.test"
    else:
        opts["port"] = 0
    before = pair(engine)
    monkeypatch.setattr(control_cli.uvicorn, "Server", lambda config: pytest.fail("Server created"))
    with pytest.raises((ValueError, OSError, ssl.SSLError)):
        control_cli.serve(**opts)
    assert pair(engine) == before


def test_control_cli_sanitizes_startup_failure(tmp_path, capsys):
    args = [
        "--journal",
        str(tmp_path / "missing"),
        "--origin",
        "https://127.0.0.1:8788",
        "--operator-key-file",
        "PRIVATE-SIGNING",
        "--read-token-file",
        "PRIVATE-TOKEN",
        "--certfile",
        "PRIVATE-CERT",
        "--keyfile",
        "PRIVATE-KEY",
    ]
    assert control_cli.main(args) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error_class"] == "FileNotFoundError" and "PRIVATE" not in output


def test_native_tls_companion_preserves_submission_and_commits_signed_halt(tmp_path, certificate):
    engine, signing, token = context(tmp_path)
    submitting(engine)
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    opts = arguments(engine, signing, token, certificate, port)
    argv = [sys.executable, "-W", "error", "-m", "app.execution.control_cli"]
    for name, value in opts.items():
        argv += ["--" + name.replace("_", "-"), str(value)]
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "PYTHONPATH") if k in os.environ}
    before = pair(engine)
    process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        tls = ssl.create_default_context(cafile=str(certificate[0]))
        with httpx2.Client(verify=tls, trust_env=False, timeout=2) as client:
            started = time.monotonic()
            while True:
                try:
                    response = client.get(
                        opts["origin"] + "/v1/review", headers={"Authorization": "Bearer " + TOKEN}
                    )
                    if response.status_code == 200:
                        break
                except httpx2.HTTPError:
                    pass
                assert process.poll() is None and time.monotonic() - started < 20
                time.sleep(0.05)
            review = response.json()
            assert review["active_order"]["status"] == "SUBMITTING" and not review["halted"]
            assert pair(engine) == before
            duplicate = subprocess.run(argv, env=env, capture_output=True, timeout=5)
            assert duplicate.returncode == 1
            assert json.loads(duplicate.stdout)["error_class"] == "ControlAlreadyRunning"
            assert pair(engine) == before
            assert client.get(opts["origin"] + "/v1/review").status_code == 401
            now = datetime.now(timezone.utc)
            command = OperatorCommand(
                journal_id=review["operator_journal_id"],
                command_id=uuid4().hex,
                actor="native-operator",
                action="HALT",
                reason="Review active fixture attempt",
                expected_revision=review["revision"],
                credential_generation=review["operator_credential_generation"],
                issued_at=now,
                expires_at=now + timedelta(minutes=1),
            )
            envelope = {
                "command": command.model_dump(mode="json"),
                "signature": sign_command(command, KEY),
            }
            headers = {"Authorization": "Bearer " + TOKEN}
            first = client.post(opts["origin"] + "/v1/commands", headers=headers, json=envelope)
            repeat = client.post(opts["origin"] + "/v1/commands", headers=headers, json=envelope)
            assert first.status_code == repeat.status_code == 200
            initial, replay = first.json(), repeat.json()
            assert not initial.pop("replayed") and replay.pop("replayed")
            assert initial == replay
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr.decode()
        report = engine.journal.report(now=NOW)
        assert report["halted"] and report["orders"][0]["status"] == "SUBMITTING"
        assert report["restore_fence"]["status"] == "VERIFIED"
        assert not stdout and KEY.hex().encode() not in stderr and TOKEN.encode() not in stderr
        with control_cli.control_lease(engine.journal.path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
