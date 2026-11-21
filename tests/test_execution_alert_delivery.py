import asyncio
import hashlib
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import threading
import time
from datetime import timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.execution.alerts import AlertConfig, AlertDelivery, AlertLimits
from app.execution.economics import CostAccounting, CostPolicy
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.operator import OperatorCommand, OperatorControl, sign_command
from tests.test_execution_rehearsal import NOW, decision, packet

TOKEN = "73" * 32
KEY = b"k" * 32


@pytest.fixture(scope="module")
def certificate(tmp_path_factory):
    root = tmp_path_factory.mktemp("alert-tls")
    cert, key = root / "ca.pem", root / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return cert, key


@pytest.fixture
def sink(tmp_path, certificate):
    cert, key = certificate
    root = SimpleNamespace(mode="ok", calls=[], accepted={}, started=threading.Event(), ca=cert)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            message = json.loads(data)
            assert self.path == "/v1/alerts"
            assert self.headers["Authorization"] == "Bearer " + TOKEN
            assert self.headers["Idempotency-Key"] == message["delivery_id"]
            root.calls.append((message, data))
            digest = hashlib.sha256(data).hexdigest()
            prior = root.accepted.setdefault(message["delivery_id"], digest)
            assert prior == digest
            root.started.set()
            if root.mode == "stall":
                time.sleep(2)
                return
            if root.mode == "lost":
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            receipt = {
                "delivery_id": message["delivery_id"],
                "payload_sha256": digest,
                "accepted": True,
            }
            status = 202
            if root.mode == "foreign":
                receipt["delivery_id"] = "0" * 64
            elif root.mode == "hash":
                receipt["payload_sha256"] = "0" * 64
            elif root.mode == "false":
                receipt["accepted"] = False
            elif root.mode == "extra":
                receipt["extra"] = "untrusted"
            elif root.mode == "redirect":
                status = 302
            elif root.mode == "error":
                status = 503
            body = json.dumps(receipt).encode()
            if root.mode == "duplicate":
                body = body[:-1] + b',"accepted":true}'
            elif root.mode == "oversized":
                body = b"x" * 1025
            elif root.mode == "malformed":
                body = b"not json"
            self.send_response(status)
            self.send_header(
                "Content-Type", "text/html" if root.mode == "html" else "application/json"
            )
            self.send_header("Content-Length", str(len(body)))
            if root.mode == "compressed":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    root.origin = f"https://127.0.0.1:{server.server_port}"
    yield root
    server.shutdown()
    server.server_close()
    thread.join()


def setup(tmp_path, sink, *, limits=None, fenced=True):
    engine = ExecutionEngine(
        tmp_path / "alerts.db",
        Settings(
            _env_file=None,
            mode="PAPER",
            live_enabled=False,
            starting_capital=10,
        ),
    )
    venue = LocalFixtureVenue(10)
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    OperatorControl.enroll(engine, KEY, now=NOW)
    if fenced:
        engine.journal.enable_restore_fence(now=NOW)
    token = tmp_path / "sink.token"
    token.write_text(TOKEN + "\n")
    token.chmod(0o600)
    config = AlertConfig(origin=sink.origin, limits=limits or AlertLimits())
    clock = [NOW]
    delivery = AlertDelivery(
        engine, config, token_file=token, ca_file=sink.ca, clock=lambda: clock[0]
    )
    return SimpleNamespace(
        engine=engine, venue=venue, token=token, config=config, clock=clock, delivery=delivery
    )


def emit(c, kind="ATTEMPT_UNCERTAIN", at=NOW):
    with c.engine.journal.write() as db:
        c.engine.journal.event(
            db, at, kind, {"secret": "private-thesis-and-account"}, "private-order"
        )
    return c.engine.journal.alerts()[-1]["event_sequence"]


def run(c):
    return asyncio.run(c.delivery.deliver_once())


def test_minimal_delivery_receipt_is_durable_but_not_ack_or_recovery(tmp_path, sink):
    c = setup(tmp_path, sink)
    c.engine.halt("fixture operator pause", now=NOW)
    before = c.engine.journal.report(now=NOW)
    sequence = before["alerts"][0]["event_sequence"]
    assert run(c) == {"status": "DELIVERED", "event_sequence": sequence}
    assert run(c) == {"status": "IDLE"}
    assert len(sink.calls) == len(sink.accepted) == 1
    message, body = sink.calls[0]
    assert set(message) == {
        "schema_version",
        "delivery_id",
        "journal_id",
        "event_sequence",
        "occurred_at",
        "kind",
    }
    assert "fixture operator pause" not in body.decode() and TOKEN not in body.decode()
    report = c.engine.journal.report(now=NOW)
    assert report["halted"] and report["alerts"][0]["acknowledged_at"] is None
    assert report["ledger"] == before["ledger"] and report["orders"] == []
    reopened = AlertDelivery(
        ExecutionEngine(c.engine.journal.path, c.engine.settings),
        c.config,
        token_file=c.token,
        ca_file=sink.ca,
        clock=lambda: NOW,
    )
    assert asyncio.run(reopened.deliver_once()) == {"status": "IDLE"}
    before = [
        c.engine.journal.path.read_bytes(),
        Path(str(c.engine.journal.path) + ".authority.db").read_bytes(),
    ]
    assert reopened.report()["status"] == "OK"
    assert reopened.report()["restore_fence"]["status"] == "VERIFIED"
    assert before == [
        c.engine.journal.path.read_bytes(),
        Path(str(c.engine.journal.path) + ".authority.db").read_bytes(),
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost",
        "https://u:p@localhost",
        "https://localhost/a",
        "https://localhost?x",
        "https://localhost#x",
        "https://*",
        "https://localhost:",
        "https://localhost:0",
        "https://localhost\\x",
        "https://localhost%20x",
        "https://a\nb",
    ],
)
def test_origin_is_explicit_https_without_redirect_or_credential_authority(origin):
    with pytest.raises(ValueError):
        AlertConfig(origin=origin)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_attempts": 4},
        {"max_attempts": True},
        {"timeout_seconds": 31},
        {"timeout_seconds": float("nan")},
        {"retry_seconds": 0},
        {"max_pending_age_seconds": 301},
    ],
)
def test_limits_are_bounded(limits):
    with pytest.raises(ValueError):
        AlertLimits(**limits)


def test_unfenced_journal_cannot_enroll(tmp_path, sink):
    with pytest.raises(ValueError, match="Verified restore"):
        setup(tmp_path, sink, fenced=False)


def test_enrollment_cannot_change_destination_or_adopt_existing_orders(tmp_path, sink):
    c = setup(tmp_path, sink)
    with pytest.raises(ValueError, match="immutable"):
        AlertDelivery(
            c.engine,
            c.config.model_copy(update={"origin": "https://different.test"}),
            token_file=c.token,
            ca_file=sink.ca,
            clock=lambda: NOW,
        )
    c.engine.prepare("entry", decision(), packet(), now=NOW)
    # A first enrollment on another engine must precede any order.
    other = ExecutionEngine(tmp_path / "other.db", c.engine.settings)
    other.reconcile(c.venue.snapshot(NOW), now=NOW)
    other.prepare("entry", decision(), packet(), now=NOW)
    other.journal.enable_restore_fence(now=NOW)
    with pytest.raises(ValueError, match="precede order"):
        AlertDelivery(other, c.config, token_file=c.token, ca_file=sink.ca, clock=lambda: NOW)


@pytest.mark.parametrize(
    "mode",
    [
        "foreign",
        "hash",
        "false",
        "extra",
        "redirect",
        "error",
        "duplicate",
        "oversized",
        "malformed",
        "html",
        "compressed",
    ],
)
def test_only_exact_bounded_json_acceptance_counts_as_delivered(tmp_path, sink, mode):
    c = setup(tmp_path, sink)
    sequence = emit(c)
    sink.mode = mode
    assert run(c) == {"status": "RETRY", "event_sequence": sequence}
    report = c.delivery.report()
    assert report["attempts"][0]["attempts"] == 1
    assert c.engine.journal.alerts()[0]["acknowledged_at"] is None
    assert len(sink.calls) == 1  # No in-process retries or redirect followup.
    text = c.engine.journal.path.read_bytes()
    assert TOKEN.encode() not in text


def test_lost_receipt_retry_retains_exact_event_payload_and_id(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    sink.mode = "lost"
    assert run(c)["status"] == "RETRY"
    assert run(c)["status"] == "IDLE"
    assert len(sink.calls) == 1
    c.clock[0] += timedelta(seconds=60)
    sink.mode = "ok"
    assert run(c)["status"] == "DELIVERED"
    assert len(sink.calls) == 2 and len(sink.accepted) == 1
    assert sink.calls[0] == sink.calls[1]
    assert "private-thesis" not in sink.calls[0][1].decode()


def test_capped_exponential_retry_and_exhaustion_block_entry_and_model(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    sink.mode = "error"
    assert run(c)["status"] == "RETRY"
    c.clock[0] += timedelta(seconds=59)
    assert run(c)["status"] == "IDLE"
    c.clock[0] += timedelta(seconds=1)
    assert run(c)["status"] == "RETRY"
    c.clock[0] += timedelta(seconds=119)
    assert run(c)["status"] == "IDLE"
    c.clock[0] += timedelta(seconds=1)
    assert run(c)["status"] == "EXHAUSTED"
    assert run(c)["status"] == "IDLE"
    assert len(sink.calls) == 3
    assert c.delivery.report()["status"] == "BLOCKED"
    c.engine.reconcile(c.venue.snapshot(c.clock[0]), now=c.clock[0])
    with pytest.raises(ExecutionBlocked, match="ALERT_DELIVERY_NOT_READY"):
        c.engine.prepare("entry", decision(), packet(c.clock[0]), now=c.clock[0])
    accounting = CostAccounting(c.engine, CostPolicy(total_budget=1, daily_budget=1))
    with pytest.raises(ExecutionBlocked, match="ALERT_DELIVERY_NOT_READY"):
        accounting.begin("model", packet(c.clock[0]), now=c.clock[0])
    assert not c.engine.journal.report(now=c.clock[0])["halted"]
    assert c.engine.prepare("hold", decision("HOLD"), packet(c.clock[0]), now=c.clock[0]) is None


def test_overdue_acknowledged_alert_still_requires_delivery(tmp_path, sink):
    c = setup(tmp_path, sink)
    sequence = emit(c)
    operator = OperatorControl(c.engine, KEY)
    command = OperatorCommand(
        journal_id=operator.journal_id,
        command_id="ack",
        actor="tester",
        action="ACK_ALERT",
        reason="Reviewed alert",
        expected_revision=operator.review()["revision"],
        alert_sequence=sequence,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
    )
    operator.apply(command, sign_command(command, KEY), now=NOW)
    c.clock[0] += timedelta(seconds=121)
    assert c.delivery.report()["status"] == "BLOCKED"
    c.engine.reconcile(c.venue.snapshot(c.clock[0]), now=c.clock[0])
    with pytest.raises(ExecutionBlocked, match="ALERT_DELIVERY_NOT_READY"):
        c.engine.prepare("entry", decision(), packet(c.clock[0]), now=c.clock[0])
    assert run(c)["status"] == "DELIVERED"
    assert c.delivery.report()["status"] == "OK"
    assert c.engine.prepare("entry", decision(), packet(c.clock[0]), now=c.clock[0])


@pytest.mark.parametrize("bad", ["permissions", "symlink", "directory", "fifo", "huge", "invalid"])
def test_sink_token_is_private_and_rechecked_in_child(tmp_path, sink, bad):
    c = setup(tmp_path, sink)
    emit(c)
    if bad == "permissions":
        c.token.chmod(0o644)
    elif bad == "symlink":
        target = tmp_path / "other.token"
        c.token.rename(target)
        c.token.symlink_to(target)
    elif bad == "directory":
        c.token.unlink()
        c.token.mkdir()
    elif bad == "fifo":
        c.token.unlink()
        os.mkfifo(c.token, mode=0o600)
    elif bad == "huge":
        c.token.write_bytes(b"x" * 1024 * 1024)
    else:
        c.token.write_text("g" * 64)
    assert run(c)["status"] == "RETRY"
    assert sink.calls == []


def test_tls_is_verified_and_ca_binding_cannot_change(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    ca = tmp_path / "ca.pem"
    ca.write_bytes(sink.ca.read_bytes())
    # Frozen CA hash mismatch fails before sending an authenticated request.
    c.delivery.ca_file = str(ca)
    with pytest.raises(ValueError, match="configuration changed"):
        run(c)
    assert sink.calls == []
    c.delivery.ca_file = str(sink.ca)
    original = sink.ca.read_bytes()
    try:
        sink.ca.write_text("different CA data")
        assert run(c)["status"] == "RETRY"
        assert sink.calls == []
    finally:
        sink.ca.write_bytes(original)


def test_default_ca_rejects_untrusted_local_certificate(tmp_path, sink):
    c = setup(tmp_path, sink)
    other = ExecutionEngine(tmp_path / "untrusted.db", c.engine.settings)
    other.reconcile(c.venue.snapshot(NOW), now=NOW)
    other.journal.enable_restore_fence(now=NOW)
    c.engine = other
    c.delivery = AlertDelivery(other, c.config, token_file=c.token, clock=lambda: NOW)
    emit(c)
    assert run(c)["status"] == "RETRY" and sink.calls == []


def test_timeout_and_duplicate_owner_are_bounded(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(timeout_seconds=1.5))
    emit(c)
    sink.mode = "stall"

    async def proof():
        started = time.monotonic()
        first = asyncio.create_task(c.delivery.deliver_once())
        while not sink.started.is_set():
            await asyncio.sleep(0.01)
        assert await c.delivery.deliver_once() == {"status": "BUSY"}
        assert (await first)["status"] == "RETRY"
        assert time.monotonic() - started < 3.5

    asyncio.run(proof())
    assert c.delivery.report()["attempts"][0]["attempts"] == 1


def test_cancelled_child_is_reaped_and_lease_prevents_immediate_replay(tmp_path, sink, monkeypatch):
    c = setup(tmp_path, sink)
    emit(c)
    sink.mode = "stall"
    children = []
    original = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        process = await original(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)

    async def proof():
        task = asyncio.create_task(c.delivery.deliver_once())
        while not sink.started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None
        assert await c.delivery.deliver_once() == {"status": "IDLE"}

    asyncio.run(proof())
    assert c.delivery.report()["attempts"][0]["status"] == "IN_FLIGHT"
    c.clock[0] += timedelta(seconds=60)
    sink.mode = "ok"
    assert run(c)["status"] == "DELIVERED" and len(sink.accepted) == 1


def test_crashed_final_claim_expires_to_exhausted_without_fourth_send(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(max_attempts=1))
    emit(c)
    claim = c.delivery._claim(NOW)
    assert claim["attempts"] == 1
    c.clock[0] += timedelta(seconds=60)
    assert run(c) == {"status": "EXHAUSTED"}
    assert sink.calls == [] and c.delivery.report()["status"] == "BLOCKED"


def test_epoch_offset_is_normalized_for_retry_admission(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    sink.mode = "lost"
    assert run(c)["status"] == "RETRY"
    c.clock[0] = (NOW + timedelta(seconds=60)).astimezone(timezone(timedelta(hours=-4)))
    sink.mode = "ok"
    assert run(c)["status"] == "DELIVERED"


def test_child_receives_no_model_or_broker_environment_and_private_paths_are_not_payload(
    tmp_path, sink, monkeypatch
):
    c = setup(tmp_path, sink)
    emit(c)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("ROBINHOOD_TOKEN", "must-not-leak-either")
    monkeypatch.setenv("HTTPS_PROXY", "https://must-not-use.test")
    original = asyncio.create_subprocess_exec
    observed = []

    async def capture(*args, **kwargs):
        observed.append((args, kwargs["env"]))
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    assert run(c)["status"] == "DELIVERED"
    assert set(observed[0][1]) <= {"PATH", "LANG", "LC_ALL", "PYTHONPATH"}
    assert str(c.engine.journal.path) not in json.dumps(sink.calls[0][0])
    assert str(c.token) not in json.dumps(sink.calls[0][0])


def test_restore_rollback_blocks_send_before_attempt_and_reopen_is_compatible(tmp_path, sink):
    c = setup(tmp_path, sink)
    before = c.engine.journal.path.read_bytes()
    emit(c)
    c.engine.journal.path.write_bytes(before)
    with pytest.raises(ValueError, match="RESTORED_OR_CHANGED"):
        run(c)
    assert sink.calls == []


def test_runtime_configuration_change_and_unsafe_lock_fail_before_network(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    path = Path(str(c.engine.journal.path) + ".alerts.lock")
    path.symlink_to(c.token)
    with pytest.raises(OSError):
        run(c)
    path.unlink()
    c.delivery.config = c.config.model_copy(update={"limits": AlertLimits(max_attempts=1)})
    with pytest.raises(ValueError, match="configuration changed"):
        run(c)
    assert sink.calls == []


def test_report_bounds_and_clock_regression_block_entries(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    assert c.delivery.report(now=NOW - timedelta(seconds=1))["status"] == "BLOCKED"
    with pytest.raises(ValueError):
        c.delivery.report(limit=101)
    with pytest.raises(ValueError):
        c.delivery.report(now=NOW.replace(tzinfo=None))


def test_alert_completion_storage_failure_retains_claim_for_same_id_retry(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    with c.engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER completion_failure BEFORE UPDATE OF completed_at ON execution_alert_attempts WHEN NEW.status='DELIVERED' BEGIN SELECT RAISE(ABORT,'local failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        run(c)
    assert c.delivery.report()["attempts"][0]["status"] == "IN_FLIGHT"
    with c.engine.journal.write() as db:
        db.execute("DROP TRIGGER completion_failure")
    c.clock[0] += timedelta(seconds=60)
    assert run(c)["status"] == "DELIVERED"
    assert len(sink.calls) == 2 and len(sink.accepted) == 1


def test_delivery_service_exits_on_stop_without_changing_engine_authority(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(poll_seconds=1))
    emit(c)

    async def proof():
        stop = asyncio.Event()
        task = asyncio.create_task(c.delivery.run(stop))
        for _ in range(500):
            if c.delivery.report()["status"] == "OK":
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("delivery did not settle")
        stop.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(proof())
    assert len(sink.calls) == 1
    assert c.engine.journal.report(now=NOW)["orders"] == []


def test_delivery_backlog_does_not_disable_governed_protective_exit(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(max_pending_age_seconds=30))
    intent = c.engine.prepare("entry", decision(), packet(), now=NOW)
    assert c.engine.dispatch(intent.client_id, c.venue, now=NOW, packet=packet()) == "OPEN"
    c.venue.fill(intent.client_id, intent.quantity, 10, NOW, fill_id="buy")
    c.engine.reconcile(c.venue.snapshot(NOW), now=NOW)
    emit(c)
    c.clock[0] += timedelta(seconds=31)
    at = c.clock[0]
    c.engine.reconcile(c.venue.snapshot(at), now=at)
    assert c.delivery.report()["status"] == "BLOCKED"
    p = packet(at, "9.4", "9.41")
    exit_intent = c.engine.prepare_protective_exit(p, now=at)
    assert exit_intent.side == "SELL"
    assert c.engine.dispatch(exit_intent.client_id, c.venue, now=at, packet=p) == "OPEN"
    assert c.venue.submit_count == 2


def test_claim_storage_failure_does_not_send(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    with c.engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER claim_failure BEFORE INSERT ON execution_alert_attempts BEGIN SELECT RAISE(ABORT,'local failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        run(c)
    assert sink.calls == [] and c.delivery.report()["attempts"] == []


def test_dead_sender_backlog_blocks_model_before_creating_receipt(tmp_path, sink):
    c = setup(tmp_path, sink)
    accounting = CostAccounting(c.engine, CostPolicy(total_budget=1, daily_budget=1))
    emit(c)
    c.clock[0] += timedelta(seconds=121)
    at = c.clock[0]
    c.engine.reconcile(c.venue.snapshot(at), now=at)
    with pytest.raises(ExecutionBlocked, match="ALERT_DELIVERY_NOT_READY"):
        accounting.begin("never-called", packet(at), now=at)
    with c.engine.journal.read() as db:
        assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 0


def test_reviewed_local_rearm_keeps_identity_total_history_and_halt(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(max_attempts=1))
    c.engine.halt("review required", now=NOW)
    sequence = c.engine.journal.alerts()[0]["event_sequence"]
    sink.mode = "lost"
    assert run(c)["status"] == "EXHAUSTED"
    with pytest.raises(ValueError):
        c.delivery.rearm(sequence, "", now=NOW)
    c.delivery.rearm(sequence, "Sink retained the first receipt; retry exact ID", now=NOW)
    assert c.engine.journal.report(now=NOW)["halted"]
    sink.mode = "ok"
    assert run(c)["status"] == "DELIVERED"
    row = c.delivery.report()["attempts"][0]
    assert row["attempts"] == 2 and row["batch_attempts"] == 1
    assert len(sink.calls) == 2 and len(sink.accepted) == 1
    assert sink.calls[0] == sink.calls[1]
    events = c.engine.journal.report(now=NOW)["events"]
    assert sum(e["kind"] == "ALERT_DELIVERY_ATTEMPTED" for e in events) == 2
    assert sum(e["kind"] == "ALERT_DELIVERY_RESULT" for e in events) == 2
    assert any(e["kind"] == "ALERT_DELIVERY_REARMED" for e in events)
    assert c.engine.journal.alerts()[0]["acknowledged_at"] is None
    with pytest.raises(ValueError, match="Only an exhausted"):
        c.delivery.rearm(sequence, "already complete", now=NOW)


def test_idle_poll_is_read_only_and_future_alert_blocks_entry(tmp_path, sink):
    c = setup(tmp_path, sink)
    before = [
        c.engine.journal.path.read_bytes(),
        Path(str(c.engine.journal.path) + ".authority.db").read_bytes(),
    ]
    assert run(c) == {"status": "IDLE"}
    assert before == [
        c.engine.journal.path.read_bytes(),
        Path(str(c.engine.journal.path) + ".authority.db").read_bytes(),
    ]
    emit(c, at=NOW + timedelta(seconds=1))
    assert c.delivery.report()["status"] == "BLOCKED"


def test_failed_oldest_alert_does_not_starve_later_due_alert(tmp_path, sink):
    c = setup(tmp_path, sink)
    first = emit(c)
    second = emit(c)
    sink.mode = "error"
    assert run(c) == {"status": "RETRY", "event_sequence": first}
    sink.mode = "ok"
    assert run(c) == {"status": "DELIVERED", "event_sequence": second}
    assert c.delivery.report()["pending"] == 1


@pytest.mark.skipif(os.sys.platform != "linux", reason="Linux subreaper owns orphan cleanup")
def test_actual_parent_crash_watchdog_reaps_child_and_preserves_delivery_lease(tmp_path, sink):
    import ctypes
    import signal
    import sys

    c = setup(tmp_path, sink)
    emit(c)
    marker = tmp_path / "orphan.pid"
    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(original), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        pytest.skip("Subreaper unavailable")
    child_pid = None
    script = '''
import asyncio, os, sys
from pathlib import Path
from datetime import datetime
from app.config import Settings
from app.execution.engine import ExecutionEngine
from app.execution.alerts import AlertDelivery, AlertConfig
at=datetime.fromisoformat(sys.argv[5])
engine=ExecutionEngine(sys.argv[1],Settings(_env_file=None,mode="PAPER",live_enabled=False,starting_capital=10))
delivery=AlertDelivery(engine,AlertConfig.model_validate_json(sys.argv[2]),token_file=sys.argv[3],ca_file=sys.argv[4],clock=lambda:at)
source="""
import os,time
from pathlib import Path
from app.execution import alert_worker
original=alert_worker.perform
def stall(request):
    Path(MARKER).write_text(str(os.getpid()))
    time.sleep(60)
    return original(request)
alert_worker.perform=stall
raise SystemExit(alert_worker.main())
""".replace("MARKER",repr(sys.argv[6]))
real_spawn=asyncio.create_subprocess_exec
async def spawn(*args,**kwargs):
    return await real_spawn(sys.executable,"-c",source,**kwargs)
asyncio.create_subprocess_exec=spawn
async def run():
    asyncio.create_task(delivery.deliver_once())
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
                str(c.engine.journal.path),
                c.config.model_dump_json(),
                str(c.token),
                str(sink.ca),
                NOW.isoformat(),
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
                assert os.waitstatus_to_exitcode(status) == 98
                break
            time.sleep(0.01)
        assert child_pid is None
        assert c.delivery.report()["attempts"][0]["status"] == "IN_FLIGHT"
        assert run(c) == {"status": "IDLE"}
        assert sink.calls == []
        c.clock[0] += timedelta(seconds=60)
        assert run(c)["status"] == "DELIVERED"
        assert c.delivery.report()["attempts"][0]["attempts"] == 2
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child_pid, 0)
        libc.prctl(36, original.value, 0, 0, 0)
