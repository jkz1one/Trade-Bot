import asyncio
import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.execution.control_api import ControlAPIConfig, _finish_work, create_control_app
from app.execution.engine import ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.operator import OperatorCommand, OperatorControl, sign_command
from tests.test_execution_rehearsal import NOW, decision, packet

ORIGIN = "https://control.test"
KEY = b"k" * 32
TOKEN = "72" * 32


def secret(path, value):
    with path.open("w") as stream:
        path.chmod(0o600)
        stream.write(value + "\n")


@pytest.fixture
def c(tmp_path):
    engine = ExecutionEngine(
        tmp_path / "control.db",
        Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10),
    )
    venue = LocalFixtureVenue(10)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    OperatorControl.enroll(engine, KEY, now=NOW)
    engine.journal.enable_restore_fence(now=NOW)
    key_path, token_path = tmp_path / "signing.key", tmp_path / "read.token"
    secret(key_path, KEY.hex())
    secret(token_path, TOKEN)
    clock = [NOW]
    config = ControlAPIConfig(origin=ORIGIN)
    app = create_control_app(
        engine,
        config,
        operator_key_file=key_path,
        read_token_file=token_path,
        clock=lambda: clock[0],
    )
    with TestClient(app, base_url=ORIGIN, headers={"Authorization": "Bearer " + TOKEN}) as client:
        yield SimpleNamespace(
            engine=engine,
            venue=venue,
            key_path=key_path,
            token_path=token_path,
            clock=clock,
            config=config,
            app=app,
            client=client,
            key=KEY,
        )


def bytes_pair(c):
    path = c.engine.journal.path
    return [path.read_bytes(), Path(str(path) + ".authority.db").read_bytes()]


def envelope(c, action="HALT", **changes):
    review = c.client.get("/v1/review").json()
    request = OperatorCommand(
        **{
            "journal_id": review["operator_journal_id"],
            "command_id": uuid4().hex,
            "actor": "fixture-http-operator",
            "action": action,
            "reason": "Reviewed current fixture evidence",
            "expected_revision": review["revision"],
            "credential_generation": review["operator_credential_generation"],
            "issued_at": c.clock[0],
            "expires_at": c.clock[0] + timedelta(minutes=1),
            **changes,
        }
    )
    return {"command": request.model_dump(mode="json"), "signature": sign_command(request, c.key)}


def post(c, value):
    return c.client.post("/v1/commands", json=value)


def test_startup_and_review_are_read_only_and_omit_private_authority(c):
    before = bytes_pair(c)
    app = create_control_app(
        c.engine,
        c.config,
        operator_key_file=c.key_path,
        read_token_file=c.token_path,
        clock=lambda: NOW,
    )
    assert {route.path for route in app.routes} == {"/v1/review", "/v1/commands"}
    response = c.client.get("/v1/review")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    data = response.json()
    assert data["restore_fence"]["status"] == "VERIFIED" and data["snapshot"]["complete"]
    assert data["active_order"] is None and not data["live_enabled"]
    assert not {"events", "fills", "orders", "key_hash", "config", "prompt"} & data.keys()
    assert KEY.hex() not in response.text and TOKEN not in response.text
    assert bytes_pair(c) == before


@pytest.mark.parametrize(
    "origin",
    [
        "http://control.test",
        "https://user:pass@control.test",
        "https://control.test/path",
        "https://control.test?x=1",
        "https://*",
        "https://control.test:",
    ],
)
def test_invalid_origin_cannot_create_transport(origin):
    with pytest.raises(ValueError):
        ControlAPIConfig(origin=origin)


def test_startup_requires_existing_enrollment_and_verified_fence(tmp_path):
    key, token = tmp_path / "key", tmp_path / "token"
    secret(key, KEY.hex())
    secret(token, TOKEN)
    engine = ExecutionEngine(
        tmp_path / "fresh.db",
        Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10),
    )
    before = engine.journal.path.read_bytes()
    with pytest.raises(ValueError, match="authentication"):
        create_control_app(
            engine, ControlAPIConfig(origin=ORIGIN), operator_key_file=key, read_token_file=token
        )
    assert engine.journal.path.read_bytes() == before
    OperatorControl.enroll(engine, KEY, now=NOW)
    before = engine.journal.path.read_bytes()
    with pytest.raises(ValueError, match="restore authority"):
        create_control_app(
            engine, ControlAPIConfig(origin=ORIGIN), operator_key_file=key, read_token_file=token
        )
    assert engine.journal.path.read_bytes() == before


@pytest.mark.parametrize(
    "bad", ["permissions", "symlink", "short", "shared", "directory", "missing"]
)
def test_invalid_secret_files_cannot_provision_authority(c, bad):
    before = bytes_pair(c)
    if bad == "permissions":
        c.key_path.chmod(0o644)
    elif bad == "symlink":
        real = c.key_path.with_suffix(".real")
        c.key_path.rename(real)
        c.key_path.symlink_to(real)
    elif bad == "short":
        secret(c.key_path, "short")
    elif bad == "shared":
        secret(c.token_path, KEY.hex())
    elif bad == "directory":
        c.key_path.unlink()
        c.key_path.mkdir()
    else:
        c.key_path.unlink()
    with pytest.raises((OSError, ValueError)):
        create_control_app(
            c.engine, c.config, operator_key_file=c.key_path, read_token_file=c.token_path
        )
    assert bytes_pair(c) == before


@pytest.mark.parametrize(
    "path,method",
    [
        ("/v1/review", "get"),
        ("/v1/commands", "post"),
        ("/docs", "get"),
        ("/place_equity_order", "post"),
    ],
)
def test_anonymous_requests_never_parse_commands_or_mutate(c, path, method):
    before = bytes_pair(c)
    response = getattr(c.client, method)(path, headers={"Authorization": ""})
    assert response.status_code == 401
    assert bytes_pair(c) == before


@pytest.mark.parametrize(
    "kind,code",
    [
        ("http", 426),
        ("host", 421),
        ("origin", 403),
        ("cross-site", 403),
        ("forwarded", 400),
        ("x-forwarded", 400),
        ("duplicate-auth", 400),
        ("duplicate-host", 400),
    ],
)
def test_transport_origin_headers_cannot_grant_authority(c, kind, code):
    value = envelope(c)
    before = bytes_pair(c)
    headers = {"Authorization": "Bearer " + TOKEN}
    url = ORIGIN + "/v1/commands"
    if kind == "http":
        url = url.replace("https://", "http://")
    elif kind == "host":
        headers["Host"] = "attacker.test"
    elif kind == "origin":
        headers["Origin"] = "https://attacker.test"
    elif kind == "cross-site":
        headers["Sec-Fetch-Site"] = "cross-site"
    elif kind == "forwarded":
        headers["Forwarded"] = "proto=https;host=control.test"
    elif kind == "x-forwarded":
        headers["X-Forwarded-Proto"] = "https"
    elif kind == "duplicate-auth":
        headers = [("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer " + TOKEN)]
    else:
        headers = [
            ("Authorization", "Bearer " + TOKEN),
            ("Host", "control.test"),
            ("Host", "control.test"),
        ]
    response = c.client.post(url, json=value, headers=headers)
    assert response.status_code == code
    assert bytes_pair(c) == before


@pytest.mark.parametrize(
    "bad",
    ["extra", "broker-action", "naive-clock", "duplicate", "nonfinite", "unicode", "malformed"],
)
def test_bad_command_shape_is_sanitized_and_never_mutates(c, bad):
    value = envelope(c)
    if bad == "extra":
        value["command"]["api_key"] = "private-never-echo"
    elif bad == "broker-action":
        value["command"]["action"] = "PLACE_EQUITY_ORDER"
    elif bad == "naive-clock":
        value["command"]["issued_at"] = NOW.replace(tzinfo=None).isoformat()
        value["command"]["expires_at"] = (
            (NOW + timedelta(seconds=60)).replace(tzinfo=None).isoformat()
        )
    body = json.dumps(value).encode()
    if bad == "duplicate":
        body = body.replace(b'"signature":', b'"signature":"' + b"0" * 64 + b'", "signature":')
    elif bad == "nonfinite":
        body = body.replace(b'"expected_revision": ', b'"expected_revision": NaN, "duplicate": ')
    elif bad == "unicode":
        body = b"\xffprivate-never-echo"
    elif bad == "malformed":
        body = b'{"private-never-echo":'
    before = bytes_pair(c)
    response = c.client.post(
        "/v1/commands", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400 and "private-never-echo" not in response.text
    assert bytes_pair(c) == before


@pytest.mark.parametrize(
    "headers,body,code",
    [
        ({"Content-Type": "text/plain"}, b"{}", 415),
        ({"Content-Type": "application/json", "Content-Encoding": "gzip"}, b"{}", 415),
        ({"Content-Type": "application/json"}, b"x" * 16385, 413),
        ({"Content-Type": "application/json", "Content-Length": "9" * 5000}, b"{}", 413),
        ({"Content-Type": "application/json", "Content-Length": "-1"}, b"{}", 400),
    ],
)
def test_media_and_body_limits_fail_before_command_authority(c, headers, body, code):
    before = bytes_pair(c)
    response = c.client.post("/v1/commands", content=body, headers=headers)
    assert response.status_code == code and bytes_pair(c) == before


@pytest.mark.parametrize("bad", ["signature", "tamper", "journal"])
def test_valid_read_token_does_not_grant_command_signing_authority(c, bad):
    value = envelope(c)
    if bad == "signature":
        value["signature"] = "0" * 64
    elif bad == "tamper":
        value["command"]["action"] = "RESUME"
    else:
        value["command"]["journal_id"] = uuid4().hex
        value["signature"] = sign_command(OperatorCommand.model_validate(value["command"]), KEY)
    before = bytes_pair(c)
    assert post(c, value).status_code == 403 and bytes_pair(c) == before


def test_halt_replay_and_reviewed_resume_preserve_durable_receipts(c):
    value = envelope(c)
    first = post(c, value)
    assert first.status_code == 200 and c.engine.journal.report()["halted"]
    revision = c.engine.journal.report()["revision"]
    again = post(c, value)
    assert again.json()["replayed"] and c.engine.journal.report()["revision"] == revision
    resume = envelope(c, "RESUME")
    assert post(c, resume).status_code == 200 and not c.engine.journal.report()["halted"]
    c.clock[0] += timedelta(minutes=2)
    assert post(c, value).json()["replayed"] and not c.engine.journal.report()["halted"]
    with c.engine.journal.read() as db:
        assert db.execute("SELECT count(*) FROM execution_commands").fetchone()[0] == 2


def test_stale_review_is_audited_rejected_and_cannot_resume(c):
    c.engine.halt("First review", now=NOW)
    value = envelope(c, "RESUME")
    c.engine.halt("Evidence changed", now=NOW)
    result = post(c, value)
    assert result.status_code == 409 and result.json()["reason"] == "OPERATOR_REVIEW_STALE"
    assert c.engine.journal.report()["halted"]
    revision = c.engine.journal.report()["revision"]
    assert post(c, value).json()["replayed"]
    assert c.engine.journal.report()["revision"] == revision


def test_attempted_order_cannot_be_abandoned_or_resumed_by_transport(c):
    intent = c.engine.prepare("entry", decision(), packet(), now=NOW)
    assert c.engine.dispatch(intent.client_id, c.venue, now=NOW, packet=packet()) == "OPEN"
    c.engine.halt("Review uncertain remainder", now=NOW)
    for action, extra, reason in [
        ("RESUME", {}, "ORDER_ALREADY_IN_FLIGHT"),
        (
            "ABANDON_PREPARED",
            {"client_id": intent.client_id},
            "ATTEMPTED_ORDER_REQUIRES_RECONCILIATION",
        ),
    ]:
        result = post(c, envelope(c, action, **extra))
        assert result.status_code == 409 and result.json()["reason"] == reason
    assert c.venue.submit_count == 1 and c.engine.journal.report()["orders"][0]["active"]


def test_unattempted_abandonment_and_alert_ack_never_clear_halt(c):
    intent = c.engine.prepare("entry", decision(), packet(), now=NOW)
    c.engine.halt("Manual review", now=NOW)
    assert post(c, envelope(c, "ABANDON_PREPARED", client_id=intent.client_id)).status_code == 200
    review = c.client.get("/v1/review").json()
    assert review["active_order"] is None and review["halted"]
    assert (
        post(
            c, envelope(c, "ACK_ALERT", alert_sequence=review["alerts"][0]["event_sequence"])
        ).status_code
        == 200
    )
    assert c.engine.journal.report()["halted"] and c.venue.submit_count == 0


def test_owned_position_resume_requires_fresh_supervision(c):
    intent = c.engine.prepare("entry", decision(), packet(), now=NOW)
    assert c.engine.dispatch(intent.client_id, c.venue, now=NOW, packet=packet()) == "OPEN"
    c.venue.fill(intent.client_id, intent.quantity, intent.limit_price, NOW, fill_id="fixture-fill")
    assert c.engine.reconcile(c.venue.snapshot(NOW), now=NOW)["reconciled"]
    c.engine.halt("Position review", now=NOW)
    result = post(c, envelope(c, "RESUME"))
    assert (
        result.status_code == 409
        and result.json()["reason"] == "FRESH_POSITION_SUPERVISION_REQUIRED"
    )
    c.engine.supervise(packet(), now=NOW)
    assert post(c, envelope(c, "RESUME")).status_code == 200
    assert not c.engine.journal.report()["halted"]


def test_rotated_signer_requires_local_secret_update_and_old_key_cannot_replay(c):
    new = b"n" * 32
    old_halt = envelope(c)
    rotation = envelope(c, "ROTATE_KEY", replacement_fingerprint=hashlib.sha256(new).hexdigest())
    assert post(c, rotation).status_code == 200 and c.engine.journal.report()["halted"]
    assert c.client.get("/v1/review").status_code == 503
    assert post(c, rotation).status_code == 403
    secret(c.key_path, new.hex())
    c.key = new
    assert c.client.get("/v1/review").json()["operator_credential_generation"] == 2
    assert post(c, old_halt).status_code == 403 and post(c, rotation).status_code == 403
    assert post(c, envelope(c, "RESUME")).status_code == 200


def test_revocation_has_no_http_enrollment_or_recovery_backdoor(c):
    assert post(c, envelope(c, "REVOKE_KEY")).status_code == 200
    assert c.client.get("/v1/review").status_code == 503
    before = bytes_pair(c)
    for path in ("/v1/enroll", "/v1/recover", "/v1/place", "/v1/cancel", "/v1/live"):
        assert c.client.post(path, json={}).status_code == 404
    assert bytes_pair(c) == before and c.engine.journal.report()["halted"]


def test_read_token_file_rotation_is_checked_on_every_request(c):
    secret(c.token_path, "74" * 32)
    assert c.client.get("/v1/review").status_code == 401
    assert (
        c.client.get("/v1/review", headers={"Authorization": "Bearer " + "74" * 32}).status_code
        == 200
    )


def test_journal_rollback_blocks_transport_before_any_mutation(c):
    old = c.engine.journal.path.read_bytes()
    assert post(c, envelope(c)).status_code == 200
    c.engine.journal.path.write_bytes(old)
    before = bytes_pair(c)
    assert c.client.get("/v1/review").status_code == 503
    control = OperatorControl(c.engine, KEY)
    cmd = OperatorCommand(
        journal_id=control.journal_id,
        command_id=uuid4().hex,
        actor="fixture",
        action="HALT",
        reason="Keep halted",
        expected_revision=0,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert (
        post(
            c, {"command": cmd.model_dump(mode="json"), "signature": sign_command(cmd, KEY)}
        ).status_code
        == 403
    )
    assert bytes_pair(c) == before


@pytest.mark.anyio
async def test_unknown_length_body_and_slow_body_are_bounded(c):
    config = ControlAPIConfig(origin=ORIGIN, body_timeout_seconds=0.03)
    app = create_control_app(
        c.engine,
        config,
        operator_key_file=c.key_path,
        read_token_file=c.token_path,
        clock=lambda: NOW,
    )
    before = bytes_pair(c)

    async def large():
        yield b"x" * 10000
        yield b"x" * 10000

    async def slow():
        yield b"{"
        await asyncio.sleep(0.2)
        yield b"}"

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    ) as client:
        assert (await client.post("/v1/commands", content=large())).status_code == 413
        assert (await client.post("/v1/commands", content=slow())).status_code == 408
    assert bytes_pair(c) == before


@pytest.mark.anyio
async def test_inflight_admission_is_bounded_and_released_after_request(c):
    app = create_control_app(
        c.engine,
        ControlAPIConfig(origin=ORIGIN, max_inflight=1),
        operator_key_file=c.key_path,
        read_token_file=c.token_path,
        clock=lambda: NOW,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def waiting():
        entered.set()
        await release.wait()
        yield b"{}"

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    ) as client:
        request = asyncio.create_task(client.post("/v1/commands", content=waiting()))
        try:
            await entered.wait()
            assert (await client.get("/v1/review")).status_code == 429
        finally:
            release.set()
            assert (await request).status_code == 400
        assert (await client.get("/v1/review")).status_code == 200


@pytest.mark.anyio
async def test_repeated_cancel_drains_local_commit_and_receipt_can_replay(c):
    value = envelope(c)
    started, release = threading.Event(), threading.Event()
    control = OperatorControl(c.engine, KEY)

    def work():
        started.set()
        if not release.wait(10):
            raise RuntimeError("Fixture cleanup never released")
        return control.apply(
            OperatorCommand.model_validate(value["command"]), value["signature"], now=NOW
        )

    task = asyncio.create_task(_finish_work(work))
    try:
        async with asyncio.timeout(5):
            while not started.is_set():
                await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert c.engine.journal.report()["halted"] and post(c, value).json()["replayed"]


def test_review_response_is_bounded_without_echoing_large_state(c):
    with c.engine.journal.write() as db:
        db.execute("UPDATE execution_control SET halt_reason=?", ("private-large-state" * 5000,))
    before = bytes_pair(c)
    response = c.client.get("/v1/review")
    assert response.status_code == 503 and response.json()["reason"] == "CONTROL_REVIEW_TOO_LARGE"
    assert "private-large-state" not in response.text and bytes_pair(c) == before


@pytest.mark.anyio
async def test_http_cancellation_keeps_admission_until_commit_thread_finishes(c, monkeypatch):
    app = create_control_app(
        c.engine,
        ControlAPIConfig(origin=ORIGIN, max_inflight=1),
        operator_key_file=c.key_path,
        read_token_file=c.token_path,
        clock=lambda: NOW,
    )
    value = envelope(c)
    started, release = threading.Event(), threading.Event()
    real = OperatorControl.apply

    def delayed(self, *args, **kwargs):
        started.set()
        if not release.wait(10):
            raise RuntimeError("Cleanup not released")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(OperatorControl, "apply", delayed)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Authorization": "Bearer " + TOKEN},
    ) as client:
        request = asyncio.create_task(client.post("/v1/commands", json=value))
        try:
            async with asyncio.timeout(5):
                while not started.is_set():
                    await asyncio.sleep(0.01)
            request.cancel()
            await asyncio.sleep(0.01)
            request.cancel()
            await asyncio.sleep(0.01)
            assert not request.done()
            assert (await client.get("/v1/review")).status_code == 429
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
        assert c.engine.journal.report()["halted"]
        assert (await client.get("/v1/review")).status_code == 200
        assert (await client.post("/v1/commands", json=value)).json()["replayed"]


def test_runtime_engine_changes_fail_closed_without_mutation(c):
    value = envelope(c)
    c.engine.settings.live_enabled = True
    before = bytes_pair(c)
    assert c.client.get("/v1/review").status_code == 503
    assert post(c, value).status_code == 503
    assert bytes_pair(c) == before


def test_secret_permissions_are_rechecked_after_startup(c):
    value = envelope(c)
    c.token_path.chmod(0o644)
    before = bytes_pair(c)
    assert c.client.get("/v1/review").status_code == 503
    assert post(c, value).status_code == 503
    assert bytes_pair(c) == before
