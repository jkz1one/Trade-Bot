"""Reviewed archive service command and native lifecycles, not systemd enforcement."""

import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.execution.checkpoint_archive import ArchiveStore
from tests.test_execution_archive_receiver import TOKEN, request, wait_for
from tests.test_execution_archive_receiver import a as a  # noqa: PLC0414
from tests.test_execution_archive_receiver import certificate as certificate  # noqa: PLC0414

UNIT = Path(__file__).parent.parent / "deploy" / "archive" / "trade-bot-archive.service"
PYTHON = os.environ.get("PAPER_ARCHIVE_TEST_PYTHON", sys.executable)


def values(name):
    return [
        line.split("=", 1)[1]
        for line in UNIT.read_text().splitlines()
        if line.startswith(name + "=")
    ]


def command(a):
    args = shlex.split(values("ExecStart")[0])
    args[0] = PYTHON
    replacements = {
        "--directory": str(a.root),
        "--origin": f"https://127.0.0.1:{a.port}",
        "--token-file": str(a.token),
        "--certfile": str(a.cert),
        "--keyfile": str(a.key),
        "--host": "127.0.0.1",
        "--port": str(a.port),
    }
    for flag, value in replacements.items():
        args[args.index(flag) + 1] = value
    return args


def launch(a):
    # The original 30-second connection budget and real native CLI remain unchanged.
    return subprocess.Popen(
        command(a),
        cwd=a.root.parent,
        env={
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TRADER_MODE": "LIVE",
            "TRADER_LIVE_ENABLED": "true",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@contextmanager
def owner(a):
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        a.port = available.getsockname()[1]
    process = launch(a)
    try:

        def ready():
            assert process.poll() is None, "Archive unit command failed before readiness"
            try:
                return request(a, method="GET", pin="a" * 64)[0] == 404
            except OSError:
                return False

        wait_for(ready)
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            out, err = process.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            raise
        assert not out and not err


def test_archive_unit_has_separate_owner_storage_credentials_and_bounded_lifecycle():
    assert values("User") == values("Group") == ["tradebot-archive"]
    assert values("ReadWritePaths") == ["/var/lib/trade-bot-archive/objects"]
    assert values("TemporaryFileSystem") == ["/etc/trade-bot-archive:ro,mode=0755,size=1M"]
    assert values("BindReadOnlyPaths") == ["/etc/trade-bot-archive/receiver"]
    assert not values("BindPaths")
    assert values("ProtectSystem") == ["strict"] and values("UMask") == ["0077"]
    assert values("NoNewPrivileges") == ["true"] and values("ProtectHome") == ["true"]
    assert values("Restart") == ["on-failure"] and values("RestartSec") == ["10"]
    assert values("StartLimitIntervalSec") == ["300"] and values("StartLimitBurst") == ["3"]
    assert values("KillMode") == ["mixed"] and values("KillSignal") == ["SIGTERM"]
    assert values("TimeoutStopSec") == ["45"]
    assert not any(
        values(key)
        for key in (
            "Requires",
            "BindsTo",
            "PartOf",
            "ExecStartPre",
            "ExecStopPost",
            "EnvironmentFile",
            "StateDirectory",
            "DynamicUser",
        )
    )
    args = shlex.split(values("ExecStart")[0])
    assert args[:5] == [
        "/opt/trade-bot-archive/venv/bin/python",
        "-I",
        "-m",
        "app.execution.archive_cli",
        "serve",
    ]
    assert args[args.index("--timeout-seconds") + 1] == "30"
    assert args[args.index("--origin") + 1] == "https://archive.invalid:8790"
    assert set(values("ConditionPathExists")) == {
        "/var/lib/trade-bot-archive/objects/archive.json",
        "/etc/trade-bot-archive/receiver/archive.token",
        "/etc/trade-bot-archive/receiver/chain.pem",
        "/etc/trade-bot-archive/receiver/tls.key",
    }
    assert "-/opt/trade-bot-paper" in " ".join(values("InaccessiblePaths"))
    assert "-/opt/trade-bot" in " ".join(values("InaccessiblePaths"))


def test_native_systemd_parser_accepts_archive_service(tmp_path):
    binary = shutil.which("systemd-analyze")
    if binary is None:
        pytest.skip("Native systemd parser unavailable")
    text = UNIT.read_text().replace("/opt/trade-bot-archive/venv/bin/python", PYTHON)
    text = text.replace("User=tradebot-archive", f"User={os.geteuid()}")
    text = text.replace("Group=tradebot-archive", f"Group={os.getegid()}")
    target = tmp_path / UNIT.name
    target.write_text(text)
    result = subprocess.run(
        [binary, "verify", "--man=no", str(target)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0 and not result.stderr, result.stderr


@pytest.mark.parametrize("death", [signal.SIGTERM, signal.SIGKILL])
def test_unit_command_retains_complete_and_interrupted_evidence_on_stop_and_restart(a, death):
    complete = b"original retained object"
    complete_pin = hashlib.sha256(complete).hexdigest()
    body = b"x" * 131072
    pin = hashlib.sha256(body).hexdigest()
    with owner(a) as process:
        assert request(a, body=complete)[0] == 201
        target = a.root / complete_pin / "checkpoint.tbcp"
        identity = target.stat().st_ino
        duplicate = launch(a)
        try:
            out, err = duplicate.communicate(timeout=5)
        finally:
            if duplicate.poll() is None:
                duplicate.kill()
                duplicate.communicate(timeout=5)
        assert duplicate.returncode == 1 and not err
        assert json.loads(out) == {
            "status": "ERROR",
            "error_class": "BlockingIOError",
            "execution_authority": False,
        }
        with (
            socket.create_connection(("127.0.0.1", a.port), timeout=3) as raw,
            ssl.create_default_context(cafile=a.cert).wrap_socket(
                raw, server_hostname="127.0.0.1"
            ) as connection,
        ):
            connection.sendall(
                (
                    f"PUT /v1/checkpoints/{pin} HTTP/1.1\r\nHost: 127.0.0.1:{a.port}\r\n"
                    f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/octet-stream\r\n"
                    f"Content-Length: {len(body)}\r\nIdempotency-Key: {pin}\r\n\r\n"
                ).encode()
                + body[:65536]
            )
            incoming = a.root / pin / "incoming"
            wait_for(lambda: incoming.exists() and incoming.stat().st_size == 65536)
            started = time.monotonic()
            process.send_signal(death)
            assert process.wait(timeout=40) == (0 if death == signal.SIGTERM else -signal.SIGKILL)
            assert time.monotonic() - started < int(values("TimeoutStopSec")[0])
    partial = incoming.read_bytes()
    with ArchiveStore(a.root) as store:
        report = store.report()
        assert report["admitted_objects"] == 2
        assert {r["status"] for r in report["objects"]} == {"VERIFIED", "INCOMPLETE"}
        assert report["off_host_protection"] == "UNVERIFIED" and not report["execution_authority"]
    with owner(a):
        assert request(a, method="GET", pin=complete_pin)[:2] == (200, complete)
        assert request(a, body=complete)[0] == 200 and target.stat().st_ino == identity
        assert request(a, body=body)[0] == 409 and incoming.read_bytes() == partial
        assert request(a, body=b"distinct future object")[0] == 201


@pytest.mark.parametrize("missing", ["root", "token", "key"])
def test_unit_command_never_initializes_or_adopts_missing_provisioning(a, missing):
    a.port = 8790
    if missing == "root":
        a.root = a.root.parent / "missing-store"
    elif missing == "key":
        # Preserve the module-scoped TLS fixture for other tests/orderings.
        a.key = a.root.parent / "missing-key"
    else:
        getattr(a, missing).unlink()
    result = subprocess.run(command(a), capture_output=True, timeout=5, check=False)
    assert result.returncode == 1 and not result.stderr
    failure = json.loads(result.stdout)
    assert not failure["execution_authority"] and failure["status"] == "ERROR"
    assert str(a.root).encode() not in result.stdout and TOKEN.encode() not in result.stdout
    if missing == "root":
        assert not a.root.exists()
    else:
        with ArchiveStore(a.root) as store:
            assert store.report()["objects"] == []
