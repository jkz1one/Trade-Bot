"""Host service contracts and native multi-process PAPER lifecycle, no remote APIs."""

import os
import shlex
import shutil
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
from app.execution.alerts import (
    AlertConfig,
    AlertDelivery,
    AlertLimits,
    alert_delivery_lease,
)
from app.execution.control_cli import control_lease
from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.engine import ExecutionEngine
from app.execution.models import ExecutionLimits
from app.execution.operator import OperatorCommand, OperatorControl, sign_command
from app.execution.quote_feed import DurableQuoteFeed
from app.execution.runtime import PaperRuntime, RuntimeLimits, runtime_lease
from app.execution.supervisor import ExecutionSupervisor, SupervisorLimits
from tests.test_execution_alert_delivery import KEY, TOKEN
from tests.test_execution_alert_delivery import certificate as certificate
from tests.test_execution_alert_delivery import sink as sink
from tests.test_execution_rehearsal import NOW, packet

UNIT_ROOT = Path(__file__).parent.parent / "deploy" / "paper"
PYTHON = os.environ.get("PAPER_HOST_TEST_PYTHON", sys.executable)
READ_TOKEN = "74" * 32


def unit(role):
    return (UNIT_ROOT / f"trade-bot-paper-{role}.service").read_text()


def values(text, name):
    return [line.split("=", 1)[1] for line in text.splitlines() if line.startswith(name + "=")]


def secret(path, value):
    path.write_text(value + "\n")
    path.chmod(0o600)
    return path


def command(role, root, *, port=8788):
    raw = values(unit(role), "ExecStart")[0]
    raw = raw.replace("/opt/trade-bot-paper/venv/bin/python", PYTHON)
    raw = raw.replace("/var/lib/trade-bot-paper", str(root / "state"))
    raw = raw.replace("/etc/trade-bot-paper", str(root / "credentials"))
    raw = raw.replace("https://127.0.0.1:8788", f"https://127.0.0.1:{port}")
    argv = shlex.split(raw)
    if role == "control":
        argv += ["--port", str(port)]
    return argv


@pytest.mark.parametrize("role", ["runtime", "control", "alerts"])
def test_unit_boundaries_do_not_couple_failures_or_expose_peer_credentials(role):
    text = unit(role)
    assert not any(
        values(text, key)
        for key in (
            "BindsTo",
            "PartOf",
            "Requires",
            "ExecStartPre",
            "ExecStopPost",
            "EnvironmentFile",
        )
    )
    assert values(text, "Restart") == (["no"] if role == "runtime" else ["on-failure"])
    assert values(text, "KillMode") == ["mixed"]
    assert int(values(text, "TimeoutStopSec")[0]) >= (190 if role == "runtime" else 35)
    assert values(text, "ProtectSystem") == ["strict"] and values(text, "NoNewPrivileges") == [
        "true"
    ]
    assert values(text, "PrivateTmp") == ["true"] and values(text, "UMask") == ["0077"]
    # A missing peer directory must not remove the credential-root mask.
    assert values(text, "TemporaryFileSystem") == ["/etc/trade-bot-paper:ro,mode=0755,size=1M"]
    assert (
        values(text, "BindReadOnlyPaths")
        == {
            "runtime": ["-/etc/trade-bot-paper/model"],
            "control": ["/etc/trade-bot-paper/operator"],
            "alerts": ["/etc/trade-bot-paper/alerts"],
        }[role]
    )
    assert values(text, "BindPaths") == (
        ["-/etc/trade-bot-paper/market"] if role == "runtime" else []
    )
    assert values(text, "ReadWritePaths") == ["/var/lib/trade-bot-paper/population"] + (
        ["-/etc/trade-bot-paper/market"] if role == "runtime" else []
    )
    blocked = " ".join(values(text, "InaccessiblePaths"))
    assert all(
        "-/etc/trade-bot-paper/" + p in blocked
        for p in {
            "runtime": ("operator", "alerts"),
            "control": ("model", "market", "alerts"),
            "alerts": ("model", "market", "operator"),
        }[role]
    )
    assert "-/var/lib/trade-bot " in blocked and "-/etc/trade-bot " in blocked
    assert shlex.split(values(text, "ExecStart")[0])[1] == "-I"
    if role != "runtime":
        assert values(text, "StartLimitBurst") == ["3"]


def test_actual_systemd_parser_validates_all_units(tmp_path):
    binary = shutil.which("systemd-analyze")
    if binary is None:
        pytest.skip("Native systemd parser unavailable")
    paths = []
    for role in ("runtime", "control", "alerts"):
        text = unit(role).replace("/opt/trade-bot-paper/venv/bin/python", PYTHON)
        # Local syntax/command proof only: these units are never installed or started here.
        text = text.replace("User=tradebot-paper", f"User={os.geteuid()}")
        text = text.replace("Group=tradebot-paper", f"Group={os.getegid()}")
        target = tmp_path / f"trade-bot-paper-{role}.service"
        target.write_text(text)
        paths.append(str(target))
    result = subprocess.run(
        [binary, "verify", "--man=no", *paths],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr


def wait(predicate, processes, seconds=20):
    start = time.monotonic()
    while not predicate():
        assert all(p.poll() is None for p in processes), "native companion exited unexpectedly"
        assert time.monotonic() - start < seconds, "native lifecycle did not settle"
        time.sleep(0.025)


def end(process, expected=0):
    process.send_signal(signal.SIGTERM)
    output, errors = process.communicate(timeout=40)
    assert process.returncode == expected, errors.decode()
    assert not errors
    return output


@pytest.mark.parametrize("failure", ["read-failure", "hard-kill"])
def test_native_runtime_failure_and_restart_leave_operator_and_alerts_available(
    tmp_path, sink, certificate, failure
):
    # Explicit disposable population with faster frozen polling and a held fixture session.
    population = tmp_path / "state" / "population"
    population.mkdir(parents=True, mode=0o700)
    credentials = tmp_path / "credentials"
    for role in ("operator", "alerts"):
        (credentials / role).mkdir(parents=True, mode=0o700)
    signing = secret(credentials / "operator" / "signing.hex", KEY.hex())
    secret(credentials / "operator" / "read.hex", READ_TOKEN)
    cert, tls_key = certificate
    (credentials / "operator" / "chain.pem").write_bytes(cert.read_bytes())
    key = credentials / "operator" / "tls.key"
    key.write_bytes(tls_key.read_bytes())
    key.chmod(0o600)
    token = secret(credentials / "alerts" / "sink.hex", TOKEN)
    engine = ExecutionEngine(
        population / "execution.db",
        Settings(
            _env_file=None,
            mode="PAPER",
            live_enabled=False,
            starting_capital=10,
            initial_symbols=["SPY"],
        ),
        limits=ExecutionLimits(
            max_entry_notional=10,
            max_position_notional=10,
            total_loss_limit=10,
            daily_loss_limit=10,
            process_timeout_seconds=2,
        ),
    )
    venue = DurableFixtureVenue(population / "venue.db", capital=10)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    engine.journal.enable_restore_fence(now=NOW)
    OperatorControl.enroll(engine, bytes.fromhex(signing.read_text().strip()), now=NOW)
    delivery = AlertDelivery(
        engine,
        AlertConfig(origin=sink.origin, limits=AlertLimits(poll_seconds=1)),
        token_file=token,
        ca_file=sink.ca,
    )
    feed = DurableQuoteFeed(population / "quotes.db", symbols=["SPY"])
    feed.publish("held-fixture-session", packet())
    supervisor = ExecutionSupervisor(
        engine,
        venue,
        feed,
        limits=SupervisorLimits(poll_seconds=0.05, tick_timeout_seconds=3, max_age_seconds=4),
        clock=lambda: NOW,
    )
    runtime = PaperRuntime(
        supervisor,
        limits=RuntimeLimits(poll_seconds=0.05, max_age_seconds=1, cycle_timeout_seconds=6),
        clock=lambda: NOW,
    )
    runtime.enroll()

    owner_script = tmp_path / "fixture_owner.py"
    owner_script.write_text("""import sys
from datetime import datetime
from app.execution import runtime_cli
original = runtime_cli.load
def fixture_load(directory):
    runtime = original(directory)
    runtime.clock = runtime.supervisor.clock = lambda: datetime.fromisoformat("2026-10-06T15:00:00+00:00")
    return runtime
runtime_cli.load = fixture_load
raise SystemExit(runtime_cli.main(sys.argv[1:]))
""")
    owner_argv = command("runtime", tmp_path)
    # The production CLI/handlers/load remain real; only the test session clock is held.
    owner_argv = owner_argv[:2] + [str(owner_script)] + owner_argv[4:]
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    env.update(TRADER_MODE="LIVE", TRADER_LIVE_ENABLED="true")
    processes = []

    def start(argv):
        process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        processes.append(process)
        return process

    control = start(command("control", tmp_path, port=port))
    alerts = start(command("alerts", tmp_path))
    owner = start(owner_argv)
    origin = f"https://127.0.0.1:{port}"
    headers = {"Authorization": "Bearer " + READ_TOKEN}
    tls = ssl.create_default_context(cafile=str(cert))
    try:
        with httpx2.Client(verify=tls, trust_env=False, timeout=2) as client:

            def ready():
                try:
                    return client.get(origin + "/v1/review", headers=headers).status_code == 200
                except httpx2.HTTPError:
                    return False

            wait(ready, (control, alerts, owner))
            wait(
                lambda: engine.journal.report(now=NOW)["runtime"]["cycles"] == {"COMPLETE": 1},
                (control, alerts, owner),
            )
            hold_events = [
                e for e in engine.journal.report(now=NOW)["events"] if e["kind"] == "HOLD"
            ]
            assert len(hold_events) == 1 and venue.submit_count == 0
            with sqlite3.connect(venue.path) as db:
                retained_venue = db.execute("SELECT state FROM fixture_control").fetchone()[0]
            if failure == "read-failure":
                with sqlite3.connect(venue.path) as db:
                    db.execute("UPDATE fixture_control SET state='invalid fixture evidence'")
                owner.communicate(timeout=15)
                assert owner.returncode == 1
                assert engine.journal.report(now=NOW)["runtime"]["status"] == "FAILED"
                assert engine.journal.report(now=NOW)["halted"]
                with sqlite3.connect(venue.path) as db:
                    db.execute("UPDATE fixture_control SET state=?", (retained_venue,))
            else:
                owner.kill()
                owner.communicate(timeout=5)
                assert owner.returncode == -signal.SIGKILL
                # An unclean death is detected on explicit owner restart, never fabricated as delivery.
                assert engine.journal.report(now=NOW)["runtime"]["status"] == "RUNNING"

            owner = start(owner_argv)
            wait(
                lambda: engine.journal.report(now=NOW)["runtime"]["generation"] == 2,
                (control, alerts, owner),
            )
            assert engine.journal.report(now=NOW)["halted"]
            end(owner)
            assert engine.journal.report(now=NOW)["runtime"]["status"] == "STOPPED"
            wait(lambda: delivery.report()["status"] == "OK", (control, alerts))
            assert len(sink.calls) == len(sink.accepted) > 0
            report = engine.journal.report(now=NOW)
            assert report["runtime"]["cycles"] == {"COMPLETE": 1} and not report["orders"]
            assert venue.submit_count == 0 and report["halted"]
            assert report["restore_fence"]["status"] == "VERIFIED"
            assert all(a["acknowledged_at"] is None for a in engine.journal.alerts())

            # Operator inspection and an exact signed ACK survive the dead trader.
            review = client.get(origin + "/v1/review", headers=headers).json()
            target = engine.journal.alerts()[0]["event_sequence"]
            now = datetime.now(timezone.utc)
            ack = OperatorCommand(
                journal_id=review["operator_journal_id"],
                command_id=uuid4().hex,
                actor="native-host-fixture",
                action="ACK_ALERT",
                alert_sequence=target,
                reason="Review retained runtime failure",
                expected_revision=review["revision"],
                credential_generation=review["operator_credential_generation"],
                issued_at=now,
                expires_at=now + timedelta(minutes=1),
            )
            envelope = {"command": ack.model_dump(mode="json"), "signature": sign_command(ack, KEY)}
            response = client.post(origin + "/v1/commands", headers=headers, json=envelope)
            assert response.status_code == 200 and not response.json()["replayed"]
            assert engine.journal.report(now=NOW)["halted"]
            count = len(sink.calls)
            end(alerts)
            assert control.poll() is None
            alerts = start(command("alerts", tmp_path))
            end(control)
            assert alerts.poll() is None
            control = start(command("control", tmp_path, port=port))
            wait(ready, (control, alerts))
            replay = client.post(origin + "/v1/commands", headers=headers, json=envelope)
            assert replay.status_code == 200 and replay.json()["replayed"]
            assert len(sink.calls) == count
            assert (
                engine.journal.report(now=NOW)["halted"]
                and not engine.journal.report(now=NOW)["orders"]
            )
            end(control)
            end(alerts)
            for lease in (runtime_lease, control_lease, alert_delivery_lease):
                with lease(engine.journal.path):
                    pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
