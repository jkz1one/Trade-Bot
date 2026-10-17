"""Signed recovery has no trading authority and preserves exact reviewed evidence."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from test_degen_options import AT, owned_strategy
from test_option_runtime import enable, packet, policy, settings, state, step

from app.options.operator import OptionsControl, sign
from app.options.operator_cli import review, submit
from app.options.operator_inbox import save
from app.options.operator_models import OptionsCommand, SignedOptionsCommand
from app.options.runtime import OptionRuntime
from app.options.runtime_cli import initialize

KEY = b"o" * 32


@pytest.fixture
def context(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, _, times, _, _):
        key = tmp_path / "operator.key"
        key.write_text(KEY.hex() + "\n")
        key.chmod(0o600)
        for name in ("operator-inbox", "operator-receipts"):
            (tmp_path / name).mkdir(mode=0o700)
        OptionsControl.enroll(c.engine, KEY, now=AT)
        r = OptionRuntime(c, policy(tmp_path, operator_key_file=str(key)), create=True)
        enable(r)
        packet(r)
        asyncio.run(step(r))
        yield c, r, OptionsControl(c.engine, KEY), key, times, venue


def command(c, **changes):
    with c.engine.journal.read() as db:
        b = db.execute("SELECT * FROM execution_operator WHERE id=1").fetchone()
        data = {
            "journal_id": b["journal_id"],
            "population_id": c.engine.limits.population_id,
            "credential_generation": b["generation"],
            "command_id": uuid4().hex,
            "expected_revision": c.engine.journal.revision(db),
            "actor": "fixture-operator",
            "reason": "Reviewed saved account and protection",
            "action": "HALT",
            "issued_at": c.now(),
            "expires_at": c.now() + timedelta(seconds=60),
        }
    return OptionsCommand.model_validate(data | changes)


def apply(c, control, request):
    return control.apply(request, sign(request, KEY), now=c.now())


@pytest.mark.parametrize("signature", ["", "0" * 64, "é" * 64, None])
def test_invalid_signature_never_mutates(context, signature):
    c, _, control, _, _, _ = context
    before = c.engine.journal.path.read_bytes()
    with pytest.raises(ValueError):
        control.apply(command(c), signature, now=c.now())
    assert c.engine.journal.path.read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"journal_id": "foreign"},
        {"population_id": "other"},
        {"credential_generation": 2},
    ],
)
def test_cross_binding_is_rejected_without_mutation(context, changes):
    c, _, control, _, _, _ = context
    request = command(c, **changes)
    before = c.engine.journal.path.read_bytes()
    with pytest.raises(ValueError):
        apply(c, control, request)
    assert c.engine.journal.path.read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "PLACE_ORDER"},
        {"action": "ACK_ALERT"},
        {"client_id": "order"},
        {"reason": " "},
        {"actor": " "},
        {"expected_revision": True},
        {"command_id": "../bad"},
        {"expires_at": AT},
        {"expires_at": AT + timedelta(seconds=301)},
        {"issued_at": AT.replace(tzinfo=None)},
        {"version": "equity-operator-v1"},
    ],
)
def test_unsupported_or_unbounded_envelope(context, changes):
    c = context[0]
    with pytest.raises(ValueError):
        command(c, **changes)


def test_tampering_and_equity_domain_cannot_authenticate(context):
    from app.execution.operator import OperatorCommand, sign_command

    c, _, control, _, _, _ = context
    request = command(c)
    with pytest.raises(ValueError):
        control.apply(
            request.model_copy(update={"action": "RESUME"}), sign(request, KEY), now=c.now()
        )
    equity = OperatorCommand(
        journal_id=request.journal_id,
        command_id=request.command_id,
        actor=request.actor,
        action="HALT",
        reason=request.reason,
        expected_revision=request.expected_revision,
        issued_at=request.issued_at,
        expires_at=request.expires_at,
    )
    with pytest.raises(ValueError):
        control.apply(request, sign_command(equity, KEY), now=c.now())


def test_halt_replay_nonce_conflict_and_resume_are_atomic(context):
    c, _, control, _, times, _ = context
    request = command(c, expected_revision=0)
    result = apply(c, control, request)
    assert result["status"] == "APPLIED" and not result["replayed"]
    before = c.engine.journal.path.read_bytes()
    times[0] += timedelta(seconds=61)
    assert apply(c, control, request)["replayed"]
    assert c.engine.journal.path.read_bytes() == before
    with pytest.raises(ValueError):
        apply(c, control, request.model_copy(update={"reason": "changed reason"}))
    times[0] = AT
    resumed = apply(c, control, command(c, action="RESUME"))
    assert resumed["status"] == "APPLIED" and not c.engine.journal.report(now=AT)["halted"]
    assert KEY not in c.engine.journal.path.read_bytes()
    with c.engine.journal.read() as db:
        assert db.execute("SELECT COUNT(*) FROM execution_commands").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0


@pytest.mark.parametrize(
    "which",
    [
        "stale_revision",
        "expired",
        "future",
        "unknown_cost",
        "stale_account",
        "busy",
        "stop",
        "runtime_blocked",
        "working_order",
    ],
)
def test_resume_keeps_halt_on_unsafe_evidence(context, which):
    c, r, control, _, times, _ = context
    apply(c, control, command(c))
    request = command(c, action="RESUME")
    if which == "stale_revision":
        with c.engine.journal.write() as db:
            c.engine.journal.event(db, AT, "REVIEW_CHANGED", {})
    elif which == "expired":
        times[0] += timedelta(seconds=60)
    elif which == "future":
        request = request.model_copy(update={"issued_at": AT + timedelta(seconds=1)})
    elif which == "stale_account":
        times[0] += timedelta(seconds=21)
    elif which == "busy":

        async def pending():
            r.task = asyncio.create_task(asyncio.sleep(10))
            try:
                result = apply(c, control, request)
                assert result["reason"] == "OPTION_RUNTIME_CYCLE_IN_PROGRESS"
            finally:
                r.task.cancel()
                await asyncio.gather(r.task, return_exceptions=True)

        asyncio.run(pending())
        return
    elif which == "stop":
        r.stop = asyncio.Event()
        r.stop.set()
    elif which == "runtime_blocked":
        with c.engine.journal.write() as db:
            db.execute("UPDATE execution_option_runtime SET status='BLOCKED'")
    elif which == "working_order":
        from test_degen_options import frame

        # Use the already admitted native strategy; resume then prepare a PAPER entry.
        apply(c, control, request)
        times[0] += timedelta(minutes=5)
        with c.engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_runtime SET heartbeat_at=?", (times[0].isoformat(),)
            )
        from app.options.models import OptionProposal

        assert c.engine.reconcile(c.engine.venue.snapshot(times[0]), now=times[0])["reconciled"]
        c.engine.assess(None, None, now=times[0])
        f = frame()
        q = f.quotes[0].model_copy(update={"source_at": times[0], "received_at": times[0]})
        u = f.underlyings[0].model_copy(update={"source_at": times[0], "received_at": times[0]})
        prepared = c.engine.prepare(
            "operator-pending",
            OptionProposal(
                action="OPEN_LONG",
                contract=q.instrument.contract,
                underlying_invalidation="600",
                thesis="fixture pending",
            ),
            q,
            u,
            now=times[0],
        )
        assert prepared["status"] == "PREPARED", prepared
        apply(c, control, command(c))
    else:
        with c.engine.journal.write() as db:
            db.execute(
                "INSERT INTO execution_model_calls(source_key,packet_hash,started_at) VALUES('unknown','hash',?)",
                (AT.isoformat(),),
            )
    if which in {"unknown_cost", "working_order", "runtime_blocked"}:
        request = command(c, action="RESUME")
    result = apply(c, control, request)
    assert result["status"] == "REJECTED"
    assert c.engine.journal.report(now=c.now())["halted"]


def test_revocation_halts_and_retires_key(context):
    c, r, control, _, _, _ = context
    result = apply(c, control, command(c, action="REVOKE_KEY", expected_revision=0))
    assert result["status"] == "APPLIED" and c.engine.journal.report(now=AT)["halted"]
    with pytest.raises(ValueError):
        OptionsControl(c.engine, KEY)
    assert r.operator.poll(now=AT) == "OPTION_OPERATOR_UNAVAILABLE"


def test_review_submit_poll_and_immutable_observer_summary(context, tmp_path):
    c, r, control, key, _, _ = context
    apply(c, control, command(c))
    before = c.engine.journal.path.read_bytes()
    reviewed = review(c.engine.journal.path, c.engine.limits.population_id, key, now=AT)
    assert c.engine.journal.path.read_bytes() == before
    assert reviewed["evidence"]["entry"]["halted"]
    assert not reviewed["execution_authority"] and KEY.hex() not in json.dumps(reviewed)
    artifact = tmp_path / "review.json"
    save(artifact, reviewed)
    queued = submit(
        c.engine.journal.path,
        artifact,
        key,
        "RESUME",
        "operator",
        "Fresh reviewed recovery",
        now=AT,
    )
    assert queued["status"] == "QUEUED" and c.engine.journal.path.read_bytes() == before
    asyncio.run(step(r))
    receipt = json.loads(Path(queued["receipt_file"]).read_text())
    assert receipt["result"]["status"] == "APPLIED"
    assert not c.engine.journal.report(now=AT)["halted"]
    assert not list(r.operator.inbox.glob("*.json"))
    from app.options.observer import OptionObserver

    o = OptionObserver(c.engine.journal.path, c.engine.limits.population_id, clock=c.clock)
    observed = o.report()
    assert observed["operator"]["status"] == "ENROLLED"
    assert observed["operator"]["recent_commands"][0]["action"] == "RESUME"


def test_crash_after_apply_replays_before_receipt_without_reexecuting(context, monkeypatch):
    c, r, _, _, _, _ = context
    request = command(c)
    signed = SignedOptionsCommand(command=request, signature=sign(request, KEY))
    save(r.operator.inbox / (request.command_id + ".json"), signed.model_dump(mode="json"))
    original = save
    failed = []

    def fault(path, value):
        if not failed:
            failed.append(True)
            raise OSError("fixture failed receipt publication")
        return original(path, value)

    monkeypatch.setattr("app.options.operator_inbox.save", fault)
    assert r.operator.poll(now=AT) == "OPTION_OPERATOR_UNAVAILABLE"
    with c.engine.journal.read() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM execution_events WHERE kind='OPTIONS_OPERATOR_COMMAND'"
        ).fetchone()[0]
    assert r.operator.poll(now=AT) is None
    with c.engine.journal.read() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM execution_events WHERE kind='OPTIONS_OPERATOR_COMMAND'"
            ).fetchone()[0]
            == count
        )
    assert json.loads((r.operator.receipts / (request.command_id + ".json")).read_text())["result"][
        "replayed"
    ]


@pytest.mark.parametrize("damage", ["bad_signature", "wrong_name", "fifo", "symlink", "oversize"])
def test_bad_inbox_requests_never_apply(context, damage):
    c, r, _, _, _, _ = context
    request = command(c)
    signed = SignedOptionsCommand(command=request, signature=sign(request, KEY))
    path = r.operator.inbox / (
        uuid4().hex + ".json" if damage == "wrong_name" else request.command_id + ".json"
    )
    if damage == "fifo":
        os.mkfifo(path, 0o600)
    elif damage == "symlink":
        path.symlink_to(r.policy.feed_file)
    else:
        data = signed.model_dump(mode="json")
        if damage == "bad_signature":
            data["signature"] = "0" * 64
        path.write_text("x" * 17000 if damage == "oversize" else json.dumps(data))
        path.chmod(0o600)
    before = c.engine.journal.path.read_bytes()
    assert r.operator.poll(now=AT) is None
    assert c.engine.journal.path.read_bytes() == before
    assert (
        json.loads((r.operator.receipts / path.name).read_text())["result"]["status"] == "REJECTED"
    )


def test_key_loss_halts_entry_but_supervision_continues(context):
    c, r, _, key, _, _ = context
    key.unlink()
    asyncio.run(step(r))
    assert state(c)["status"] == "BLOCKED"
    assert c.engine.journal.report(now=AT)["halted"]
    with c.engine.journal.read() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM execution_events WHERE kind='POSITION_SUPERVISED'"
            ).fetchone()[0]
            >= 3
        )


def test_inbox_overflow_and_receipt_conflict_fence_entry(context):
    c, r, _, _, _, _ = context
    for n in range(65):
        (r.operator.inbox / str(n)).write_text("fixture overflow")
    assert r.operator.poll(now=AT) == "OPTION_OPERATOR_INBOX_OVERFLOW"
    for p in r.operator.inbox.iterdir():
        p.unlink()
    request = command(c)
    envelope = SignedOptionsCommand(command=request, signature=sign(request, KEY))
    name = request.command_id + ".json"
    save(r.operator.inbox / name, envelope.model_dump(mode="json"))
    save(r.operator.receipts / name, {"command_fingerprint": "wrong", "result": {}})
    assert r.operator.poll(now=AT) == "OPTION_OPERATOR_RECEIPT_CONFLICT"
    assert c.engine.journal.report(now=AT)["halted"]


def test_malformed_receipt_cannot_terminate_independent_protection(context):
    c, r, _, _, _, _ = context
    request = command(c)
    envelope = SignedOptionsCommand(command=request, signature=sign(request, KEY))
    name = request.command_id + ".json"
    save(r.operator.inbox / name, envelope.model_dump(mode="json"))
    save(r.operator.receipts / name, {"result": "malformed receipt"})
    asyncio.run(step(r))
    assert state(c)["status"] == "BLOCKED"
    assert state(c)["reason"] == "OPTION_OPERATOR_RECEIPT_CONFLICT"
    with c.engine.journal.read() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM execution_events WHERE kind='POSITION_SUPERVISED'"
            ).fetchone()[0]
            >= 3
        )


def test_enrollment_rejects_shared_model_operator_secret_before_creation(tmp_path):
    from app.execution.economics import CostPolicy
    from app.execution.judgment import JudgmentLimits

    s = settings(tmp_path)
    key = tmp_path / "operator.key"
    key.write_text(KEY.hex())
    key.chmod(0o600)
    model = tmp_path / "model.key"
    model.write_text(KEY.hex().upper())
    model.chmod(0o600)
    s = s.model_copy(
        update={
            "runtime": policy(tmp_path, operator_key_file=str(key)),
            "key_file": str(model),
            "judgment_limits": JudgmentLimits(),
            "execution": s.execution.model_copy(
                update={"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")}
            ),
        }
    )
    with pytest.raises(ValueError):
        initialize(tmp_path / "rejected", s, clock=lambda: AT)
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize("ttl", [0, 301, 10**100, True])
def test_submission_ttl_is_bounded_before_io(context, tmp_path, ttl):
    c, _, _, key, _, _ = context
    with pytest.raises(ValueError):
        submit(
            c.engine.journal.path,
            tmp_path / "unused-review.json",
            key,
            "RESUME",
            "actor",
            "reason",
            now=AT,
            ttl=ttl,
        )


def test_operator_secret_and_capability_never_enter_model_packet(tmp_path, monkeypatch):
    from test_degen_options import frame
    from test_option_entry_coordination import fake_model, owned_entry

    with owned_entry(tmp_path) as (c, _, _, _):
        key = tmp_path / "operator.key"
        key.write_text(KEY.hex())
        key.chmod(0o600)
        for name in ("operator-inbox", "operator-receipts"):
            (tmp_path / name).mkdir(mode=0o700)
        OptionsControl.enroll(c.engine, KEY, now=AT)
        r = OptionRuntime(c, policy(tmp_path, operator_key_file=str(key)), create=True)
        enable(r)
        calls = fake_model(monkeypatch, c)
        result = asyncio.run(c.cycle(frame()))
        assert result["status"] == "OPEN"
        assert calls
        raw = calls[0].model_dump_json()
        assert KEY.hex() not in raw and str(key) not in raw
        assert "operator_key_file" not in raw and "credential_generation" not in raw


def test_explicit_new_population_enrollment_preserves_legacy_policy(tmp_path):
    assert "operator_key_file" not in policy(tmp_path).model_dump()
    s = settings(tmp_path)
    key = tmp_path / "operator.key"
    key.write_text(KEY.hex())
    key.chmod(0o600)
    s = s.model_copy(update={"runtime": policy(tmp_path, operator_key_file=str(key))})
    initialize(tmp_path / "run", s, clock=lambda: AT)
    assert (tmp_path / "run/operator-inbox").stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError):
        policy(tmp_path, operator_key_file=str(tmp_path / "feed.json"))


def test_installed_cli_read_and_submission_are_not_execution(context, tmp_path):
    c, r, _, key, _, _ = context
    artifact = tmp_path / "cli-review.json"
    base = [sys.executable, "-I", "-m", "app.options.operator_cli"]
    before = hashlib.sha256(c.engine.journal.path.read_bytes()).hexdigest()
    reviewed = subprocess.run(
        base
        + [
            "review",
            "--journal",
            str(c.engine.journal.path),
            "--population-id",
            c.engine.limits.population_id,
            "--key-file",
            str(key),
            "--output",
            str(artifact),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert reviewed.returncode == 0, reviewed.stderr
    submitted = subprocess.run(
        base
        + [
            "submit",
            "--journal",
            str(c.engine.journal.path),
            "--review-file",
            str(artifact),
            "--key-file",
            str(key),
            "--action",
            "HALT",
            "--actor",
            "fixture",
            "--reason",
            "Reviewed halt",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert submitted.returncode == 0, submitted.stderr
    assert json.loads(submitted.stdout)["status"] == "QUEUED"
    assert hashlib.sha256(c.engine.journal.path.read_bytes()).hexdigest() == before
    from app.domain.models import utc_now

    assert r.operator.poll(now=utc_now()) is None
    receipt = json.loads(Path(json.loads(submitted.stdout)["receipt_file"]).read_text())
    assert receipt["result"]["status"] == "APPLIED"


def test_observer_html_reads_capability_without_signing_key_access(context, tmp_path, monkeypatch):
    from test_option_observer import app_for

    c = context[0]
    client, _ = app_for(c, tmp_path)
    before = c.engine.journal.path.read_bytes()

    def forbidden(*_, **__):
        raise AssertionError("Observer tried to read the operator key")

    monkeypatch.setattr("app.options.operator_inbox._secret", forbidden)
    response = client.get("/")
    assert response.status_code == 200
    assert "Operator capability: ENROLLED" in response.text
    assert c.engine.journal.path.read_bytes() == before
