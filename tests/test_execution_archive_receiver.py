import asyncio
import hashlib
import http.client
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.execution import archive_cli, checkpoint, checkpoint_archive
from app.execution.checkpoint_archive import (
    ArchiveServer,
    ArchiveStore,
    ArchiveUnavailable,
    initialize,
)
from app.execution.checkpoint_transfer import archive_config, download_checkpoint, upload_checkpoint
from app.execution.engine import ExecutionEngine
from tests.test_execution_alert_delivery import TOKEN
from tests.test_execution_alert_delivery import certificate as certificate  # noqa: PLC0414
from tests.test_execution_checkpoint import c as c  # noqa: PLC0414


def wait_for(predicate, *, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Bounded archive observation expired")


@pytest.fixture
def a(tmp_path, certificate):
    cert, key = certificate
    key.chmod(0o600)
    root = tmp_path / "archive"
    initialize(root, max_objects=3)
    token = tmp_path / "archive.token"
    token.write_text(TOKEN + "\n")
    token.chmod(0o600)
    return SimpleNamespace(root=root, token=token, cert=cert, key=key)


@contextmanager
def local_server(a, *, timeout_seconds=2):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(a.cert, a.key)
    with (
        ArchiveStore(a.root) as store,
        ArchiveServer(
            ("127.0.0.1", 0),
            store=store,
            context=context,
            token_file=a.token,
            authority="pending",
            timeout_seconds=timeout_seconds,
        ) as server,
    ):
        a.port = server.server_port
        server.authority = f"127.0.0.1:{a.port}"
        a.store = store
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=4)
            assert not thread.is_alive()


def request(a, *, method="PUT", body=b"private opaque bytes", pin=None, headers=None, path=None):
    pin = pin or hashlib.sha256(body).hexdigest()
    metadata = {"Authorization": "Bearer " + TOKEN}
    if method == "PUT":
        metadata.update(
            {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
                "Idempotency-Key": pin,
            }
        )
    metadata.update(headers or {})
    context = ssl.create_default_context(cafile=a.cert)
    with closing(
        http.client.HTTPSConnection("127.0.0.1", a.port, context=context, timeout=4)
    ) as client:
        client.request(
            method,
            path or "/v1/checkpoints/" + pin,
            body=body if method == "PUT" else None,
            headers=metadata,
        )
        response = client.getresponse()
        return response.status, response.read(), dict(response.getheaders())


def test_durable_identity_dedup_original_retrieval_and_source_independent_report(a):
    body = b"not SQLite and not parsed as a checkpoint"
    pin = hashlib.sha256(body).hexdigest()
    with local_server(a):
        code, payload, headers = request(a, body=body)
        assert code == 201 and json.loads(payload) == {
            "checkpoint_sha256": pin,
            "byte_count": len(body),
            "retained": True,
        }
        assert headers["Cache-Control"] == "no-store"
        target = a.root / pin / "checkpoint.tbcp"
        identity = target.stat().st_ino
        assert target.read_bytes() == body and target.stat().st_mode & 0o777 == 0o600
        assert (a.root / pin).stat().st_mode & 0o777 == 0o700
        assert {p.name for p in target.parent.iterdir()} == {"checkpoint.tbcp"}
        assert request(a, body=body)[0] == 200 and target.stat().st_ino == identity
        assert request(a, method="GET", pin=pin)[:2] == (200, body)
        assert request(a, method="DELETE", pin=pin)[0] == 501
        assert target.read_bytes() == body
    with ArchiveStore(a.root) as store:
        report = store.report()
        assert report["objects"] == [
            {"checkpoint_sha256": pin, "status": "VERIFIED", "byte_count": len(body)}
        ]
        assert report["off_host_protection"] == "UNVERIFIED" and not report["execution_authority"]
        assert checkpoint_archive.MAX_BYTES == checkpoint.MAX_BYTES


@pytest.mark.parametrize(
    "change",
    [
        {"Authorization": "Bearer " + "f" * 64},
        {"Host": "foreign.test"},
        {"X-Forwarded-Host": "archive.test"},
        {"Forwarded": "proto=https"},
        {"Origin": "https://archive.test"},
        {"Content-Type": "text/plain"},
        {"Content-Encoding": "gzip"},
        {"Transfer-Encoding": "chunked"},
        {"Content-Length": "0"},
        {"Content-Length": str(checkpoint.MAX_BYTES + 1)},
        {"Idempotency-Key": "f" * 64},
        {"Content-Length": "-1"},
    ],
)
def test_rejected_metadata_does_not_admit_or_confirm(a, change):
    with local_server(a):
        code, body, _ = request(a, headers=change)
        assert code in {400, 401} and json.loads(body) == {"status": "UNAVAILABLE"}
        assert a.store.admissions() == []


@pytest.mark.parametrize(
    "path",
    [
        "/v1/checkpoints/../archive.json",
        "/v1/checkpoints/" + "F" * 64,
        "/v1/checkpoints/" + "a" * 64 + "?x=1",
        "/v1/checkpoints/%61" + "a" * 63,
        "/v1/review",
    ],
)
def test_only_exact_content_addressed_routes_are_available(a, path):
    with local_server(a):
        assert request(a, path=path)[0] == 404
        assert a.store.admissions() == []


def test_changed_bytes_or_size_cannot_overwrite_an_existing_identity(a):
    body = b"durable first object"
    pin = hashlib.sha256(body).hexdigest()
    with local_server(a):
        assert request(a, body=body)[0] == 201
        target = a.root / pin / "checkpoint.tbcp"
        before = target.read_bytes(), target.stat().st_ino
        assert request(a, body=b"x" * len(body), pin=pin)[0] == 409
        assert request(a, body=body + b"x", pin=pin)[0] == 409
        assert (target.read_bytes(), target.stat().st_ino) == before


def test_corrupt_stored_object_is_not_served_confirmed_or_repaired(a):
    body = b"durable first object"
    pin = hashlib.sha256(body).hexdigest()
    with local_server(a):
        assert request(a, body=body)[0] == 201
        target = a.root / pin / "checkpoint.tbcp"
        target.write_bytes(b"x" * len(body))
        assert request(a, method="GET", pin=pin)[0] == 503
        assert request(a, body=body)[0] == 409
        assert target.read_bytes() == b"x" * len(body)
        assert a.store.report()["objects"][0]["status"] == "UNAVAILABLE"


def test_bad_digest_keeps_incomplete_admission_and_consumes_capacity(a):
    pins = ["a" * 64, "b" * 64, "c" * 64]
    with local_server(a):
        for pin in pins:
            assert request(a, pin=pin)[0] == 409
        assert request(a)[0] == 409
        assert len(a.store.admissions()) == 3
        assert all(row["status"] == "INCOMPLETE" for row in a.store.report()["objects"])
        for pin in pins:
            assert (a.root / pin / "incoming").read_bytes() == b"private opaque bytes"


def test_body_file_fsync_failure_never_claims_retention(a, monkeypatch):
    body = b"fsync fault object"
    pin = hashlib.sha256(body).hexdigest()
    original = os.fsync

    def fail(fd):
        if os.fstat(fd).st_size == len(body):
            raise OSError("private injected storage fault")
        return original(fd)

    with local_server(a):
        monkeypatch.setattr(checkpoint_archive.os, "fsync", fail)
        code, payload, _ = request(a, body=body)
        assert code == 409 and "retained" not in json.loads(payload)
        assert not (a.root / pin / "checkpoint.tbcp").exists()
        assert (a.root / pin / "incoming").exists()


def test_lost_durability_confirmation_retries_existing_object_without_replacing_it(a, monkeypatch):
    body = b"publication fault object"
    pin = hashlib.sha256(body).hexdigest()
    original = os.fsync
    with local_server(a):

        def fail(fd):
            if fd == a.store.fd and (a.root / pin / "checkpoint.tbcp").exists():
                raise OSError("injected root fsync fault")
            return original(fd)

        monkeypatch.setattr(checkpoint_archive.os, "fsync", fail)
        assert request(a, body=body)[0] == 409
        target = a.root / pin / "checkpoint.tbcp"
        identity = target.stat().st_ino
        monkeypatch.setattr(checkpoint_archive.os, "fsync", original)
        assert request(a, body=body)[0] == 200
        assert target.stat().st_ino == identity and target.read_bytes() == body


def test_duplicate_header_and_plaintext_cannot_create_archive_material(a):
    with local_server(a):
        context = ssl.create_default_context(cafile=a.cert)
        with (
            socket.create_connection(("127.0.0.1", a.port), timeout=3) as raw,
            context.wrap_socket(raw, server_hostname="127.0.0.1") as connection,
        ):
            connection.sendall(
                (
                    f"PUT /v1/checkpoints/{'a' * 64} HTTP/1.1\r\nHost: 127.0.0.1:{a.port}\r\nAuthorization: Bearer {TOKEN}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Length: 1\r\n\r\nx"
                ).encode()
            )
            assert b"400" in connection.recv(4096)
        with socket.create_connection(("127.0.0.1", a.port), timeout=3) as connection:
            connection.sendall(b"GET / HTTP/1.0\r\n\r\n")
        assert request(a, method="GET", pin="a" * 64)[0] == 404
        assert a.store.admissions() == []


def test_invalidated_token_blocks_requests_without_admission(a):
    with local_server(a):
        a.token.chmod(0o644)
        assert request(a)[0] == 503
        assert a.store.admissions() == []


@pytest.mark.parametrize("material", ["root", "object"])
def test_changed_storage_permissions_reject_retrieval(a, material):
    body = b"private retained object"
    pin = hashlib.sha256(body).hexdigest()
    with local_server(a):
        assert request(a, body=body)[0] == 201
        path = a.root if material == "root" else a.root / pin / "checkpoint.tbcp"
        original = path.stat().st_mode & 0o777
        try:
            path.chmod(0o755 if material == "root" else 0o644)
            assert request(a, method="GET", pin=pin)[0] == 503
        finally:
            path.chmod(original)


def test_capacity_lease_and_private_existing_initialization(a):
    with ArchiveStore(a.root) as store:
        with pytest.raises(BlockingIOError):
            ArchiveStore(a.root)
        assert store.admissions() == []
        with pytest.raises(FileExistsError):
            initialize(a.root, max_objects=3)
    link = a.root.parent / "alias"
    link.symlink_to(a.root, target_is_directory=True)
    with pytest.raises(OSError):
        ArchiveStore(link)
    a.root.chmod(0o755)
    with pytest.raises(ArchiveUnavailable):
        ArchiveStore(a.root)


@pytest.mark.parametrize("capacity", [0, 1001, True, 1.0])
def test_invalid_capacity_has_no_filesystem_side_effect(tmp_path, capacity):
    root = tmp_path / "invalid"
    with pytest.raises(ValueError):
        initialize(root, max_objects=capacity)
    assert not root.exists()


@pytest.mark.parametrize("mutation", ["symlink", "broad", "duplicate", "boolean", "foreign"])
def test_untrusted_store_metadata_fails_closed(a, mutation):
    path = a.root / "archive.json"
    if mutation == "symlink":
        target = a.root.parent / "foreign"
        path.rename(target)
        path.symlink_to(target)
    elif mutation == "broad":
        path.chmod(0o644)
    elif mutation == "duplicate":
        path.write_text('{"schema":"checkpoint-archive-v1","max_objects":3,"max_objects":3}')
    elif mutation == "boolean":
        path.write_text('{"schema":"checkpoint-archive-v1","max_objects":true}')
    else:
        (a.root / "foreign").write_text("foreign material")
    with pytest.raises((OSError, ValueError)):
        ArchiveStore(a.root)


def test_symlinked_object_or_admission_is_never_read_or_replaced(a):
    body = b"private original"
    pin = hashlib.sha256(body).hexdigest()
    foreign = a.root.parent / "foreign.tbcp"
    foreign.write_bytes(body)
    foreign.chmod(0o600)
    with ArchiveStore(a.root) as store:
        store.admit(pin)
        (a.root / pin / "checkpoint.tbcp").symlink_to(foreign)
        assert store.report()["objects"][0]["status"] == "UNAVAILABLE"
    (a.root / pin / "checkpoint.tbcp").unlink()
    (a.root / pin).rmdir()
    (a.root / pin).symlink_to(a.root.parent, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        ArchiveStore(a.root)
    assert foreign.read_bytes() == body


@contextmanager
def native_server(a, *, timeout_seconds=2):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        a.port = reservation.getsockname()[1]
    python = os.environ.get("PAPER_ARCHIVE_TEST_PYTHON", sys.executable)
    process = subprocess.Popen(
        [
            python,
            "-I",
            "-m",
            "app.execution.archive_cli",
            "serve",
            "--directory",
            str(a.root),
            "--origin",
            f"https://127.0.0.1:{a.port}",
            "--token-file",
            str(a.token),
            "--certfile",
            str(a.cert),
            "--keyfile",
            str(a.key),
            "--port",
            str(a.port),
            "--timeout-seconds",
            str(timeout_seconds),
        ],
        cwd=a.root.parent,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:

        def ready():
            assert process.poll() is None, "Native archive stopped before readiness"
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
            out, err = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            raise
        assert not out and not err


def test_native_receiver_restart_client_source_loss_and_evidence_only_recovery(a, c):
    config = None
    with native_server(a) as process:
        config = archive_config(f"https://127.0.0.1:{a.port}", ca_file=a.cert)
        result = asyncio.run(
            upload_checkpoint(
                c.bundle,
                config,
                expected_sha256=c.pin,
                token_file=a.token,
                receipt_file=c.root / "receipt.json",
            )
        )
        assert result["status"] == "REMOTE_ACCEPTED" and not result["execution_authority"]
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 0
    c.bundle.unlink()
    c.engine.journal.path.unlink()
    Path(str(c.engine.journal.path) + ".authority.db").unlink()
    with native_server(a):
        config = archive_config(f"https://127.0.0.1:{a.port}", ca_file=a.cert)
        recovered = c.root / "download.tbcp"
        result = asyncio.run(
            download_checkpoint(recovered, config, expected_sha256=c.pin, token_file=a.token)
        )
        assert result["status"] == "DOWNLOADED_VERIFIED_EVIDENCE"
        staged = c.root / "quarantine"
        report = checkpoint.stage_checkpoint(recovered, staged, expected_sha256=c.pin)
        assert report["summary"]["unknown_model_calls"] == 1 and not report["execution_authority"]
        with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
            ExecutionEngine(staged / "execution.evidence.db", c.engine.settings)


def test_native_sigkill_retains_incomplete_admission_releases_lease_and_allows_distinct_upload(a):
    body = b"x" * 131072
    pin = hashlib.sha256(body).hexdigest()
    context = ssl.create_default_context(cafile=a.cert)
    with (
        native_server(a) as process,
        socket.create_connection(("127.0.0.1", a.port), timeout=3) as raw,
        context.wrap_socket(raw, server_hostname="127.0.0.1") as connection,
    ):
        connection.sendall(
            (
                f"PUT /v1/checkpoints/{pin} HTTP/1.1\r\nHost: 127.0.0.1:{a.port}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(body)}\r\nIdempotency-Key: {pin}\r\n\r\n"
            ).encode()
            + body[:65536]
        )
        target = a.root / pin / "incoming"
        wait_for(lambda: target.exists() and target.stat().st_size == 65536)
        process.kill()
        assert process.wait(timeout=5) == -signal.SIGKILL
    retained = target.read_bytes()
    with ArchiveStore(a.root) as store:
        assert store.report()["objects"] == [{"checkpoint_sha256": pin, "status": "INCOMPLETE"}]
    with native_server(a):
        assert request(a, body=body)[0] == 409
        assert request(a, body=b"distinct recovery object")[0] == 201
        assert target.read_bytes() == retained


@pytest.mark.parametrize("phase", ["handshake", "headers", "body"])
def test_native_slow_connection_is_bounded_and_sigterm_drains(a, phase):
    with native_server(a, timeout_seconds=0.5) as process:
        raw = socket.create_connection(("127.0.0.1", a.port), timeout=3)
        connection = raw
        try:
            if phase != "handshake":
                connection = ssl.create_default_context(cafile=a.cert).wrap_socket(
                    raw, server_hostname="127.0.0.1"
                )
                connection.sendall(b"PUT /v1/checkpoints/" + b"a" * 64 + b" HTTP/1.1\r\n")
                if phase == "body":
                    connection.sendall(
                        (
                            f"Host: 127.0.0.1:{a.port}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/octet-stream\r\nContent-Length: 10\r\nIdempotency-Key: {'a' * 64}\r\n\r\nx"
                        ).encode()
                    )
                    wait_for(lambda: (a.root / ("a" * 64)).exists())
            if phase != "body":
                started = time.monotonic()
                while connection.recv(4096):
                    pass
                assert time.monotonic() - started < 2
                assert process.poll() is None
                assert request(a, method="GET", pin="a" * 64)[0] == 404
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=3) == 0
        finally:
            connection.close()


def test_cli_report_and_errors_never_echo_private_paths_or_material(a, capsys):
    assert archive_cli.main(["report", "--directory", str(a.root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["execution_authority"] and report["objects"] == []
    assert archive_cli.main(["init", "--directory", str(a.root), "--max-objects", "3"]) == 1
    failure = capsys.readouterr().out
    assert str(a.root) not in failure and TOKEN not in failure
    assert set(json.loads(failure)) == {"status", "error_class", "execution_authority"}
