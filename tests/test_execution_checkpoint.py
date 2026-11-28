import asyncio
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.execution import checkpoint, checkpoint_transfer
from app.execution.checkpoint import MAGIC, export_checkpoint, inspect_checkpoint, stage_checkpoint
from app.execution.checkpoint_cli import main
from app.execution.checkpoint_transfer import archive_config, download_checkpoint, upload_checkpoint
from app.execution.economics import CostAccounting, CostPolicy
from app.execution.engine import ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal
from app.execution.operator import OperatorControl
from tests.test_execution_alert_delivery import TOKEN
from tests.test_execution_alert_delivery import (
    certificate as certificate,  # noqa: PLC0414 -- pytest fixture registration
)
from tests.test_execution_rehearsal import NOW, decision, packet


@pytest.fixture
def c(tmp_path):
    engine = ExecutionEngine(
        tmp_path / "execution.db",
        Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10),
    )
    venue = LocalFixtureVenue(10)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    OperatorControl.enroll(engine, b"k" * 32, now=NOW)
    costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
    costs.begin("unknown-model", packet(), now=NOW)
    engine.journal.enable_restore_fence(now=NOW)
    bundle = tmp_path / "checkpoint.tbcp"
    result = export_checkpoint(engine.journal.path, bundle, now=NOW)
    return SimpleNamespace(
        root=tmp_path,
        engine=engine,
        venue=venue,
        costs=costs,
        bundle=bundle,
        pin=result["checkpoint_sha256"],
        result=result,
    )


def pair_bytes(c):
    return [
        c.engine.journal.path.read_bytes(),
        Path(str(c.engine.journal.path) + ".authority.db").read_bytes(),
    ]


def rewrite(c, *, header_changes=None, body_change=None):
    data = c.bundle.read_bytes()
    offset = len(MAGIC)
    size = struct.unpack(">I", data[offset : offset + 4])[0]
    header = json.loads(data[offset + 4 : offset + 4 + size])
    header.update(header_changes or {})
    body = data[offset + 4 + size :]
    if body_change:
        body = body_change(header, body)
    encoded = json.dumps(header).encode()
    c.bundle.write_bytes(MAGIC + struct.pack(">I", len(encoded)) + encoded + body)
    return hashlib.sha256(c.bundle.read_bytes()).hexdigest()


def rewrite_created_at_same_size(c):
    old = json.dumps(c.result["manifest"]["created_at"]).encode()
    new = json.dumps((NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")).encode()
    data = c.bundle.read_bytes()
    assert old in data and len(old) == len(new)
    c.bundle.write_bytes(data.replace(old, new, 1))


def test_consistent_pair_preserves_unknown_model_and_source_bytes(c):
    before = pair_bytes(c)
    second = c.root / "second.tbcp"
    result = export_checkpoint(c.engine.journal.path, second, now=NOW)
    assert pair_bytes(c) == before
    assert result["manifest"]["generation"] == c.result["manifest"]["generation"]
    assert second.read_bytes() == c.bundle.read_bytes()
    report = inspect_checkpoint(second, expected_sha256=result["checkpoint_sha256"])
    assert report["summary"]["unknown_model_calls"] == 1
    assert report["status"] == "VERIFIED_EVIDENCE" and not report["execution_authority"]
    assert pair_bytes(c) == before and second.stat().st_mode & 0o777 == 0o600


def test_staged_evidence_cannot_become_execution_or_operator_authority(c):
    folder = c.root / "review"
    result = stage_checkpoint(c.bundle, folder, expected_sha256=c.pin)
    assert result["status"] == "QUARANTINED_EVIDENCE"
    assert result["summary"]["unknown_model_calls"] == 1
    assert {p.name for p in folder.iterdir()} == {
        "execution.evidence.db",
        "authority.evidence.db",
        "verified-evidence.json",
    }
    assert folder.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in folder.iterdir())
    evidence = folder / "execution.evidence.db"
    before = evidence.read_bytes()
    assert ExecutionJournal(evidence).report(now=NOW)["restore_fence"]["status"] == "BLOCKED"
    with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
        ExecutionEngine(evidence, c.engine.settings)
    assert evidence.read_bytes() == before
    with pytest.raises(FileExistsError):
        stage_checkpoint(c.bundle, folder, expected_sha256=c.pin)
    assert evidence.read_bytes() == before


def test_unknown_order_and_halt_survive_export_without_replay(tmp_path):
    engine = ExecutionEngine(
        tmp_path / "unknown.db",
        Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10),
    )
    venue = LocalFixtureVenue(10)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    entry = engine.prepare("entry", decision(), packet(), now=NOW)
    venue.lose_next_ack = True
    assert engine.dispatch(entry.client_id, venue, now=NOW, packet=packet()) == "UNKNOWN"
    engine.journal.enable_restore_fence(now=NOW)
    bundle = tmp_path / "unknown.tbcp"
    saved = export_checkpoint(engine.journal.path, bundle, now=NOW)
    report = stage_checkpoint(
        bundle, tmp_path / "review", expected_sha256=saved["checkpoint_sha256"]
    )
    assert report["summary"]["active_orders"] == 1 and report["summary"]["unresolved_attempts"] == 1
    assert report["summary"]["halted_at_checkpoint"] and venue.submit_count == 1


def test_pinned_new_checkpoint_rejects_a_complete_older_pair(c):
    old = c.bundle.read_bytes()
    c.engine.halt("reviewed later checkpoint", now=NOW + timedelta(seconds=1))
    fresh = c.root / "new.tbcp"
    result = export_checkpoint(c.engine.journal.path, fresh, now=NOW + timedelta(seconds=1))
    assert result["manifest"]["generation"] > c.result["manifest"]["generation"]
    fresh.write_bytes(old)
    with pytest.raises(ValueError, match="retained pin"):
        stage_checkpoint(fresh, c.root / "review", expected_sha256=result["checkpoint_sha256"])
    assert not (c.root / "review").exists()


@pytest.mark.parametrize("operation", ["inspect", "stage"])
def test_changed_bundle_after_pin_scan_cannot_verify_an_older_pair(c, monkeypatch, operation):
    old = c.bundle.read_bytes()
    c.engine.halt("later retained halt", now=NOW + timedelta(seconds=1))
    fresh = c.root / "fresh.tbcp"
    result = export_checkpoint(c.engine.journal.path, fresh, now=NOW + timedelta(seconds=1))
    assert result["manifest"]["generation"] > c.result["manifest"]["generation"]
    assert len(fresh.read_bytes()) == len(old)
    before = pair_bytes(c)
    scan = checkpoint.file_hash
    calls = []

    def replace_after_scan(stream):
        verified = scan(stream)
        # An in-place rewrite preserves the descriptor's inode. Both complete
        # pairs are valid, so member/schema/authority checks alone cannot catch it.
        fresh.write_bytes(old)
        return verified

    db = checkpoint._db

    def observe_db(*args, **kwargs):
        calls.append(args[0])
        return db(*args, **kwargs)

    monkeypatch.setattr(checkpoint, "file_hash", replace_after_scan)
    monkeypatch.setattr(checkpoint, "_db", observe_db)
    with pytest.raises(ValueError, match="retained pin"):
        if operation == "inspect":
            inspect_checkpoint(fresh, expected_sha256=result["checkpoint_sha256"])
        else:
            stage_checkpoint(fresh, c.root / "review", expected_sha256=result["checkpoint_sha256"])
    assert calls == [] and pair_bytes(c) == before
    assert not (c.root / "review").exists()


@pytest.mark.parametrize("operation", ["inspect", "stage"])
@pytest.mark.parametrize("mutation", ["header", "trailing"])
def test_changed_header_or_trailing_bytes_after_pin_scan_are_rejected(
    c, monkeypatch, operation, mutation
):
    before = pair_bytes(c)
    scan = checkpoint.file_hash
    opened = []

    def change_after_scan(stream):
        verified = scan(stream)
        if mutation == "header":
            size = c.bundle.stat().st_size
            rewrite_created_at_same_size(c)
            assert c.bundle.stat().st_size == size
        else:
            with c.bundle.open("ab") as output:
                output.write(b"unexpected trailing bytes")
        return verified

    def forbidden_database(*args, **kwargs):
        opened.append(args)
        pytest.fail("Changed pinned bytes must fail before any SQLite opening")

    monkeypatch.setattr(checkpoint, "file_hash", change_after_scan)
    monkeypatch.setattr(checkpoint, "_db", forbidden_database)
    with pytest.raises(ValueError, match="retained pin"):
        if operation == "inspect":
            inspect_checkpoint(c.bundle, expected_sha256=c.pin)
        else:
            stage_checkpoint(c.bundle, c.root / "review", expected_sha256=c.pin)
    assert not opened and pair_bytes(c) == before
    assert not (c.root / "review").exists()


@pytest.mark.parametrize("operation", ["inspect", "stage"])
def test_verification_binds_consumed_bytes_not_a_later_header_rewrite(c, monkeypatch, operation):
    before = pair_bytes(c)
    validate = checkpoint.CheckpointManifest.model_validate
    manifest = c.result["manifest"]

    def change_consumed_header(value):
        validated = validate(value)
        # The original header has already been read. Change only its on-disk
        # bytes; the remaining member bytes still produce the original snapshot.
        size = c.bundle.stat().st_size
        rewrite_created_at_same_size(c)
        assert c.bundle.stat().st_size == size
        return validated

    monkeypatch.setattr(checkpoint.CheckpointManifest, "model_validate", change_consumed_header)
    result = (
        inspect_checkpoint(c.bundle, expected_sha256=c.pin)
        if operation == "inspect"
        else stage_checkpoint(c.bundle, c.root / "review", expected_sha256=c.pin)
    )
    assert result["checkpoint_sha256"] == c.pin and result["manifest"] == manifest
    assert result["summary"]["unknown_model_calls"] == 1 and not result["execution_authority"]
    assert hashlib.sha256(c.bundle.read_bytes()).hexdigest() != c.pin
    assert pair_bytes(c) == before
    if operation == "stage":
        evidence = c.root / "review" / "execution.evidence.db"
        retained = evidence.read_bytes()
        with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
            ExecutionEngine(evidence, c.engine.settings)
        assert evidence.read_bytes() == retained


@pytest.mark.parametrize("operation", ["inspect", "stage"])
def test_cli_changed_pinned_input_reports_only_failure(c, monkeypatch, capsys, operation):
    scan = checkpoint.file_hash

    def change_after_scan(stream):
        verified = scan(stream)
        with c.bundle.open("ab") as output:
            output.write(b"private changed archive material")
        return verified

    monkeypatch.setattr(checkpoint, "file_hash", change_after_scan)
    args = [operation, "--bundle", str(c.bundle), "--sha256", c.pin]
    if operation == "stage":
        args += ["--output", str(c.root / "review")]
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "ERROR",
        "error_class": "ValueError",
        "execution_authority": False,
    }
    assert not (c.root / "review").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"generation": 999},
        {"authority_id": "foreign"},
        {"state_hash": "0" * 64},
        {"schema_version": "future"},
        {"journal_sha256": "0" * 64},
        {"authority_sha256": "0" * 64},
        {"journal_bytes": 1},
        {"authority_bytes": 1},
        {"journal_bytes": True},
        {"extra": "ignored?"},
        {"created_at": "2026-10-06T15:00:00"},
    ],
)
def test_malformed_or_misbound_manifests_do_not_publish_evidence(c, changes):
    pin = rewrite(c, header_changes=changes)
    with pytest.raises(ValueError):
        stage_checkpoint(c.bundle, c.root / "review", expected_sha256=pin)
    assert not (c.root / "review").exists()


@pytest.mark.parametrize(
    "mutation", ["truncated", "trailing", "bad_magic", "huge_header", "duplicate_header"]
)
def test_envelope_is_bounded_and_has_no_paths_or_implicit_extraction(c, mutation):
    data = c.bundle.read_bytes()
    if mutation == "truncated":
        data = data[:-1]
    elif mutation == "trailing":
        data += b"extra"
    elif mutation == "bad_magic":
        data = b"x" * len(MAGIC) + data[len(MAGIC) :]
    elif mutation == "huge_header":
        data = MAGIC + struct.pack(">I", 4097) + data[len(MAGIC) + 4 :]
    else:
        offset = len(MAGIC)
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        header = data[offset + 4 : offset + 4 + size]
        header = header[:-1] + b',"generation":0}'
        data = MAGIC + struct.pack(">I", len(header)) + header + data[offset + 4 + size :]
    c.bundle.write_bytes(data)
    pin = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        inspect_checkpoint(c.bundle, expected_sha256=pin)


@pytest.mark.parametrize("pin", [None, "", "a" * 63, "A" * 64, "0" * 64, True])
def test_recovery_requires_an_independently_retained_exact_pin(c, pin):
    with pytest.raises(ValueError):
        stage_checkpoint(c.bundle, c.root / "review", expected_sha256=pin)
    assert not (c.root / "review").exists()


@pytest.mark.parametrize("bad", ["permissions", "symlink", "fifo", "directory", "oversized"])
def test_checkpoint_file_is_private_regular_and_bounded(c, bad):
    if bad == "permissions":
        c.bundle.chmod(0o644)
    elif bad == "symlink":
        target = c.root / "other.tbcp"
        c.bundle.rename(target)
        c.bundle.symlink_to(target)
    elif bad == "fifo":
        c.bundle.unlink()
        os.mkfifo(c.bundle, mode=0o600)
    elif bad == "directory":
        c.bundle.unlink()
        c.bundle.mkdir()
    else:
        with c.bundle.open("wb") as stream:
            stream.truncate(checkpoint.MAX_BYTES + 1)
    with pytest.raises((OSError, ValueError)):
        inspect_checkpoint(c.bundle, expected_sha256=c.pin)


def test_export_cannot_overwrite_or_adopt_unfenced_or_rolled_back_source(c):
    before = pair_bytes(c)
    with pytest.raises(ValueError):
        export_checkpoint(c.engine.journal.path, c.bundle, now=NOW)
    target = c.root / "link.tbcp"
    target.symlink_to(c.bundle)
    with pytest.raises(ValueError):
        export_checkpoint(c.engine.journal.path, target, now=NOW)
    c.engine.halt("advance authority", now=NOW)
    c.engine.journal.path.write_bytes(before[0])
    with pytest.raises(ValueError, match="RESTORED_OR_CHANGED"):
        export_checkpoint(c.engine.journal.path, c.root / "bad.tbcp", now=NOW)
    assert not (c.root / "bad.tbcp").exists()
    assert not list(c.root.glob(".checkpoint-*"))


def test_unfenced_source_is_not_silently_enrolled(c):
    other = ExecutionEngine(c.root / "unfenced.db", c.engine.settings)
    with pytest.raises(FileNotFoundError):
        export_checkpoint(other.journal.path, c.root / "bad.tbcp", now=NOW)
    assert not Path(str(other.journal.path) + ".authority.db").exists()


def test_export_holds_both_source_locks_until_both_backups_complete(c, monkeypatch):
    original = checkpoint._backup
    copying = threading.Event()
    continue_copy = threading.Event()

    def backup(source, target, deadline):
        original(source, target, deadline)
        if target.name == "journal.db":
            copying.set()
            assert continue_copy.wait(5)

    monkeypatch.setattr(checkpoint, "_backup", backup)
    before = pair_bytes(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        exported = pool.submit(
            export_checkpoint, c.engine.journal.path, c.root / "race.tbcp", now=NOW
        )
        assert copying.wait(5)
        changed = pool.submit(c.engine.halt, "write after copy", now=NOW)
        time.sleep(0.05)
        assert not changed.done()
        continue_copy.set()
        result = exported.result(timeout=5)
        changed.result(timeout=5)
    report = inspect_checkpoint(c.root / "race.tbcp", expected_sha256=result["checkpoint_sha256"])
    assert not report["summary"]["halted_at_checkpoint"]
    assert pair_bytes(c) != before and c.engine.journal.report(now=NOW)["halted"]


def test_backup_failure_or_deadline_leaves_no_published_checkpoint_or_source_changes(
    c, monkeypatch
):
    before = pair_bytes(c)

    def failed(*args):
        raise OSError("fixture snapshot failure")

    monkeypatch.setattr(checkpoint, "_backup", failed)
    with pytest.raises(OSError):
        export_checkpoint(c.engine.journal.path, c.root / "failed.tbcp", now=NOW)
    assert pair_bytes(c) == before and not (c.root / "failed.tbcp").exists()
    assert not list(c.root.glob(".checkpoint-*"))
    with pytest.raises(TimeoutError):
        export_checkpoint(
            c.engine.journal.path, c.root / "expired.tbcp", now=NOW, timeout_seconds=0.00000001
        )
    assert not (c.root / "expired.tbcp").exists()
    assert not list(c.root.glob(".checkpoint-*"))


def test_cli_export_inspect_stage_are_evidence_only(c, capsys):
    assert main(["inspect", "--bundle", str(c.bundle), "--sha256", c.pin]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["execution_authority"] and not result["network_calls"]
    assert (
        main(
            [
                "stage",
                "--bundle",
                str(c.bundle),
                "--sha256",
                c.pin,
                "--output",
                str(c.root / "review"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "QUARANTINED_EVIDENCE"
    assert (
        main(
            [
                "export",
                "--journal",
                str(c.engine.journal.path),
                "--output",
                str(c.root / "cli.tbcp"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "EXPORTED"
    assert main(["inspect", "--bundle", str(c.bundle), "--sha256", "0" * 64]) == 1
    assert set(json.loads(capsys.readouterr().out)) == {
        "status",
        "error_class",
        "execution_authority",
    }


@pytest.fixture
def archive(tmp_path, certificate):
    cert, key = certificate
    token = tmp_path / "archive.token"
    token.write_text(TOKEN + "\n")
    token.chmod(0o600)
    state = SimpleNamespace(
        mode="ok", objects={}, calls=[], started=threading.Event(), token=token, ca=cert
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def authorize(self):
            assert self.headers["Authorization"] == "Bearer " + TOKEN
            assert self.path.startswith("/v1/checkpoints/")
            return self.path.rsplit("/", 1)[1]

        def do_PUT(self):
            pin = self.authorize()
            body = self.rfile.read(int(self.headers["Content-Length"]))
            assert hashlib.sha256(body).hexdigest() == pin
            assert self.headers["Idempotency-Key"] == pin
            prior = state.objects.setdefault(pin, body)
            assert prior == body
            state.calls.append(("PUT", pin))
            state.started.set()
            if state.mode == "lost":
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if state.mode == "stall":
                time.sleep(2)
                return
            receipt = {"checkpoint_sha256": pin, "byte_count": len(body), "retained": True}
            status = 201
            if state.mode == "foreign":
                receipt["checkpoint_sha256"] = "0" * 64
            elif state.mode == "size":
                receipt["byte_count"] = 1
            elif state.mode == "false":
                receipt["retained"] = False
            elif state.mode == "redirect":
                status = 302
            elif state.mode == "error":
                status = 500
            elif state.mode == "extra":
                receipt["extra"] = "untrusted"
            data = json.dumps(receipt).encode()
            if state.mode == "duplicate":
                data = data[:-1] + b',"retained":true}'
            elif state.mode == "oversized":
                data = b"x" * 1025
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            pin = self.authorize()
            state.calls.append(("GET", pin))
            data = state.objects[pin]
            status = 200
            if state.mode == "corrupt":
                data = data[:-1] + bytes([data[-1] ^ 1])
            elif state.mode == "older":
                data = next(body for name, body in state.objects.items() if name != pin)
            elif state.mode == "get_redirect":
                status = 302
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Length",
                str(checkpoint.MAX_BYTES + 1) if state.mode == "get_oversized" else str(len(data)),
            )
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    state.config = archive_config(f"https://127.0.0.1:{server.server_port}", ca_file=cert)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


def upload(c, archive, *, retry=False):
    return asyncio.run(
        upload_checkpoint(
            c.bundle,
            archive.config,
            expected_sha256=c.pin,
            token_file=archive.token,
            receipt_file=c.root / "transfer.json",
            retry=retry,
        )
    )


def test_upload_download_and_source_loss_recovery_preserve_only_evidence(c, archive):
    before = pair_bytes(c)
    result = upload(c, archive)
    assert result["status"] == "REMOTE_ACCEPTED" and pair_bytes(c) == before
    assert upload(c, archive)["status"] == "EXISTING_RECEIPT" and len(archive.calls) == 1
    assert (c.root / "transfer.json").stat().st_mode & 0o777 == 0o600
    c.engine.journal.path.unlink()
    Path(str(c.engine.journal.path) + ".authority.db").unlink()
    c.bundle.unlink()
    recovered = c.root / "retrieved.tbcp"
    result = asyncio.run(
        download_checkpoint(
            recovered, archive.config, expected_sha256=c.pin, token_file=archive.token
        )
    )
    assert result["status"] == "DOWNLOADED_VERIFIED_EVIDENCE" and not result["execution_authority"]
    report = stage_checkpoint(recovered, c.root / "recovery", expected_sha256=c.pin)
    assert report["summary"]["unknown_model_calls"] == 1
    with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
        ExecutionEngine(c.root / "recovery" / "execution.evidence.db", c.engine.settings)


@pytest.mark.parametrize(
    "mode", ["foreign", "size", "false", "redirect", "error", "extra", "duplicate", "oversized"]
)
def test_unconfirmed_retention_is_durable_and_never_automatically_retried(c, archive, mode):
    archive.mode = mode
    with pytest.raises(ValueError, match="unconfirmed"):
        upload(c, archive)
    saved = json.loads((c.root / "transfer.json").read_text())
    assert saved["status"] == "UNKNOWN" and saved["attempt"] == 1
    with pytest.raises(ValueError, match="explicit same-ID"):
        upload(c, archive)
    assert len(archive.calls) == 1
    archive.mode = "ok"
    assert upload(c, archive, retry=True)["status"] == "REMOTE_ACCEPTED"
    assert len(archive.calls) == 2 and len(archive.objects) == 1
    assert json.loads((c.root / "transfer.json").read_text())["attempt"] == 2


def test_lost_receipt_retries_same_archive_identity_and_blocks_retargeting(c, archive):
    archive.mode = "lost"
    with pytest.raises(ValueError):
        upload(c, archive)
    altered = archive.config.model_copy(update={"origin": "https://foreign.test"})
    with pytest.raises(ValueError, match="different checkpoint or destination"):
        asyncio.run(
            upload_checkpoint(
                c.bundle,
                altered,
                expected_sha256=c.pin,
                token_file=archive.token,
                receipt_file=c.root / "transfer.json",
                retry=True,
            )
        )
    archive.mode = "ok"
    assert upload(c, archive, retry=True)["status"] == "REMOTE_ACCEPTED"
    assert len(archive.objects) == 1 and len(archive.calls) == 2


@pytest.mark.parametrize("mode", ["corrupt", "get_redirect", "get_oversized"])
def test_bad_download_is_not_published_or_staged(c, archive, mode):
    upload(c, archive)
    archive.mode = mode
    with pytest.raises((ValueError, TimeoutError)):
        asyncio.run(
            download_checkpoint(
                c.root / "retrieved.tbcp",
                archive.config,
                expected_sha256=c.pin,
                token_file=archive.token,
            )
        )
    assert not (c.root / "retrieved.tbcp").exists()
    assert not list(c.root.glob(".checkpoint-download-*"))


def test_older_complete_remote_checkpoint_cannot_replace_pinned_new_checkpoint(c, archive):
    upload(c, archive)
    old_pin = c.pin
    c.engine.halt("new source state", now=NOW)
    other = c.root / "new.tbcp"
    result = export_checkpoint(c.engine.journal.path, other, now=NOW)
    archive.objects[result["checkpoint_sha256"]] = other.read_bytes()
    archive.mode = "older"
    with pytest.raises(ValueError):
        asyncio.run(
            download_checkpoint(
                c.root / "retrieved.tbcp",
                archive.config,
                expected_sha256=result["checkpoint_sha256"],
                token_file=archive.token,
            )
        )
    assert not (c.root / "retrieved.tbcp").exists()
    assert old_pin != result["checkpoint_sha256"]


def test_transfer_ca_credentials_and_environment_are_separate_from_trading(c, archive, monkeypatch):
    children = []
    real = asyncio.create_subprocess_exec
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("ROBINHOOD_TOKEN", "must-not-leak")
    monkeypatch.setenv("HTTPS_PROXY", "https://must-not-use.test")

    async def capture(*args, **kwargs):
        assert set(kwargs["env"]) <= {"PATH", "LANG", "LC_ALL", "PYTHONPATH"}
        process = await real(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    assert upload(c, archive)["status"] == "REMOTE_ACCEPTED"
    assert all(child.returncode is not None for child in children)
    state = (c.root / "transfer.json").read_text()
    assert TOKEN not in state and "must-not-leak" not in state


def test_untrusted_tls_or_changed_private_token_cannot_confirm_retention(c, archive):
    config = archive_config(archive.config.origin)
    with pytest.raises(ValueError):
        asyncio.run(
            upload_checkpoint(
                c.bundle,
                config,
                expected_sha256=c.pin,
                token_file=archive.token,
                receipt_file=c.root / "untrusted.json",
            )
        )
    assert archive.calls == []
    archive.token.chmod(0o644)
    with pytest.raises(ValueError):
        upload(c, archive)
    assert archive.calls == []


def test_cancelled_upload_reaps_child_preserves_claim_and_requires_reviewed_retry(
    c, archive, monkeypatch
):
    archive.mode = "stall"
    children = []
    real = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        process = await real(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)

    async def proof():
        task = asyncio.create_task(
            upload_checkpoint(
                c.bundle,
                archive.config,
                expected_sha256=c.pin,
                token_file=archive.token,
                receipt_file=c.root / "transfer.json",
            )
        )
        async with asyncio.timeout(5):
            while not archive.started.is_set():
                await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None

    asyncio.run(proof())
    assert json.loads((c.root / "transfer.json").read_text())["status"] == "IN_FLIGHT"
    with pytest.raises(ValueError):
        upload(c, archive)
    archive.mode = "ok"
    assert upload(c, archive, retry=True)["status"] == "REMOTE_ACCEPTED"
    assert len(archive.objects) == 1


def test_upload_timeout_and_duplicate_receipt_owner_are_bounded(c, archive):
    archive.mode = "stall"
    archive.config = archive.config.model_copy(update={"timeout_seconds": 1.5})

    async def proof():
        started = time.monotonic()
        kwargs = {
            "expected_sha256": c.pin,
            "token_file": archive.token,
            "receipt_file": c.root / "transfer.json",
        }
        task = asyncio.create_task(upload_checkpoint(c.bundle, archive.config, **kwargs))
        async with asyncio.timeout(5):
            while not archive.started.is_set():
                await asyncio.sleep(0.01)
        with pytest.raises(BlockingIOError):
            await upload_checkpoint(c.bundle, archive.config, **kwargs)
        with pytest.raises((ValueError, TimeoutError)):
            await task
        assert time.monotonic() - started < 3.5

    asyncio.run(proof())
    assert json.loads((c.root / "transfer.json").read_text())["status"] == "UNKNOWN"


def test_receipt_storage_failure_never_claims_confirmed_retention(c, archive, monkeypatch):
    real = checkpoint_transfer._save

    def fail(path, state):
        if state.status == "REMOTE_ACCEPTED":
            raise OSError("receipt storage failed")
        real(path, state)

    monkeypatch.setattr(checkpoint_transfer, "_save", fail)
    with pytest.raises(OSError):
        upload(c, archive)
    assert json.loads((c.root / "transfer.json").read_text())["status"] == "IN_FLIGHT"
    monkeypatch.setattr(checkpoint_transfer, "_save", real)
    assert upload(c, archive, retry=True)["status"] == "REMOTE_ACCEPTED"
    assert len(archive.objects) == 1


def test_ca_change_bad_pin_and_existing_download_do_not_contact_archive(c, archive):
    original = archive.ca.read_bytes()
    try:
        archive.ca.write_text("changed CA data")
        with pytest.raises(ValueError):
            upload(c, archive)
        assert archive.calls == []
    finally:
        archive.ca.write_bytes(original)
    with pytest.raises(ValueError):
        asyncio.run(
            upload_checkpoint(
                c.bundle,
                archive.config,
                expected_sha256="0" * 64,
                token_file=archive.token,
                receipt_file=c.root / "other-receipt.json",
            )
        )
    assert archive.calls == []
    with pytest.raises(ValueError):
        asyncio.run(
            download_checkpoint(
                c.bundle, archive.config, expected_sha256=c.pin, token_file=archive.token
            )
        )
    assert archive.calls == []


@pytest.mark.skipif(os.sys.platform != "linux", reason="Linux subreaper owns orphan cleanup")
def test_archive_child_parent_crash_stops_orphan_and_leaves_unconfirmed_receipt(c, archive):
    import ctypes
    import signal
    import subprocess
    import sys

    marker = c.root / "archive-orphan.pid"
    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(original), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        pytest.skip("Subreaper unavailable")
    child_pid = None
    script = '''
import asyncio,os,sys
from pathlib import Path
from app.execution.checkpoint_transfer import upload_checkpoint,ArchiveConfig
source="""
import os,time
from pathlib import Path
from app.execution import checkpoint_worker
original=checkpoint_worker.perform
def stall(request):
    Path(MARKER).write_text(str(os.getpid()))
    time.sleep(60)
    return original(request)
checkpoint_worker.perform=stall
raise SystemExit(checkpoint_worker.main())
""".replace("MARKER",repr(sys.argv[6]))
real=asyncio.create_subprocess_exec
async def spawn(*args,**kwargs): return await real(sys.executable,"-c",source,**kwargs)
asyncio.create_subprocess_exec=spawn
async def run():
    asyncio.create_task(upload_checkpoint(sys.argv[1],ArchiveConfig.model_validate_json(sys.argv[2]),expected_sha256=sys.argv[3],token_file=sys.argv[4],receipt_file=sys.argv[5]))
    async with asyncio.timeout(10):
        while not Path(sys.argv[6]).exists(): await asyncio.sleep(.01)
    os._exit(93)
asyncio.run(run())
'''
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(c.bundle),
                archive.config.model_dump_json(),
                c.pin,
                str(archive.token),
                str(c.root / "transfer.json"),
                str(marker),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 93, result.stderr
        child_pid = int(marker.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child_pid, os.WNOHANG)
            if pid:
                child_pid = None
                assert os.waitstatus_to_exitcode(status) == 94
                break
            time.sleep(0.01)
        assert child_pid is None and archive.calls == []
        assert json.loads((c.root / "transfer.json").read_text())["status"] == "IN_FLIGHT"
        with pytest.raises(ValueError, match="explicit same-ID"):
            upload(c, archive)
        assert upload(c, archive, retry=True)["status"] == "REMOTE_ACCEPTED"
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child_pid, 0)
        libc.prctl(36, original.value, 0, 0, 0)
