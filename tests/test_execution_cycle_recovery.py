import hashlib
import hmac
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.execution import judgment
from app.execution.control_api import ControlAPIConfig, create_control_app
from app.execution.economics import UsageEvidence
from app.execution.engine import ExecutionEngine
from app.execution.judgment import JudgmentResult
from app.execution.models import Snapshot
from app.execution.operator import OperatorCommand, OperatorControl, sign_command
from app.execution.runtime import runtime_lease
from tests.test_execution_rehearsal import NOW, decision, packet
from tests.test_execution_runtime import context as runtime_context

KEY = b"k" * 32
SLOT = "PAPER:XNYS:" + NOW.isoformat()


def interrupted(engine, *, slot=SLOT, p=None, status="INTERRUPTED", at=NOW):
    with engine.journal.write() as db:
        db.execute(
            "INSERT INTO execution_runtime_cycles(slot,owner,status,started_at,completed_at,feed_sequence,feed_hash,packet_json,result_json) VALUES(?,'lost-fixture-owner',?,?,?,1,?,?,?)",
            (
                slot,
                status,
                at.isoformat(),
                at.isoformat(),
                hashlib.sha256((p or packet()).model_dump_json().encode()).hexdigest(),
                (p or packet()).model_dump_json(),
                json.dumps({"error_class": "CancelledError"}),
            ),
        )
    engine.halt("Interrupted fixture cycle", now=at)


def context(tmp_path, *, model=False):
    runtime, engine, venue, settings, feed, clock = runtime_context(tmp_path, model=model)
    OperatorControl.enroll(engine, KEY, now=NOW)
    interrupted(engine)
    return runtime, engine, venue, settings, feed, clock, OperatorControl(engine, KEY)


def command(operator, *, slot=SLOT, at=NOW, **updates):
    return OperatorCommand(
        **{
            "journal_id": operator.journal_id,
            "credential_generation": operator.credential_generation,
            "command_id": uuid4().hex,
            "actor": "fixture-cycle-reviewer",
            "action": "RESOLVE_CYCLE",
            "reason": "Reviewed terminal fixture/account and model evidence; abandon without replay",
            "cycle_slot": slot,
            "issued_at": at,
            "expires_at": at + timedelta(minutes=1),
            "expected_revision": operator.review()["revision"],
            **updates,
        }
    )


def apply(operator, request, *, now=NOW):
    return operator.apply(request, sign_command(request, KEY), now=now)


def cycle(engine):
    with engine.journal.read() as db:
        return dict(
            db.execute("SELECT * FROM execution_runtime_cycles WHERE slot=?", (SLOT,)).fetchone()
        )


def pair(engine):
    from app.execution.restore import authority_path

    return [p.read_bytes() for p in (engine.journal.path, authority_path(engine.journal.path))]


def test_resolution_preserves_original_claim_halt_alerts_and_read_only_review(tmp_path):
    _, engine, venue, _, _, _, operator = context(tmp_path)
    before = cycle(engine)
    report = engine.journal.report(now=NOW)
    request = command(operator)
    result = apply(operator, request)
    assert result["status"] == "APPLIED" and not result["replayed"]
    after = engine.journal.report(now=NOW)
    assert (
        cycle(engine) == before
        and after["halted"]
        and after["halt_reason"] == report["halt_reason"]
    )
    assert (
        after["orders"] == report["orders"] == []
        and after["fills"] == []
        and venue.submit_count == 0
    )
    assert after["runtime"]["cycles"] == {"INTERRUPTED": 1}
    assert after["runtime"]["resolved_cycles"] == 1 and after["runtime"]["unresolved_cycles"] == 0
    assert after["unacknowledged_alerts"] == report["unacknowledged_alerts"]
    assert after["runtime"]["latest_cycles"][0]["resolution"]["command_id"] == request.command_id
    before_pair = pair(engine)
    review = operator.review_summary(now=NOW)
    assert review["runtime"]["resolved_cycles"] == 1 and pair(engine) == before_pair
    assert (
        not {"packet_json", "decision_json", "key_hash"}
        & review["runtime"]["latest_cycles"][0].keys()
    )
    assert after["restore_fence"]["status"] == "VERIFIED"


def test_committed_lost_response_replay_after_restart_is_exact_and_idempotent(tmp_path):
    _, engine, _, settings, _, _, operator = context(tmp_path)
    request = command(operator)
    original = apply(operator, request)
    reopened = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    operator = OperatorControl(reopened, KEY)
    repeat = apply(operator, request, now=NOW + timedelta(days=1))
    assert repeat == {**original, "replayed": True}
    assert reopened.journal.report(now=NOW)["runtime"]["resolved_cycles"] == 1
    assert reopened.journal.report()["halted"]
    second = apply(operator, command(operator))
    assert second["reason"] == "PAPER_CYCLE_ALREADY_RESOLVED"


def test_concurrent_reviewed_resolution_has_one_receipt_one_effect(tmp_path):
    *_, operator = context(tmp_path)
    request = command(operator)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(operator, request), range(2)))
    assert {r["replayed"] for r in results} == {False, True}
    assert operator.engine.journal.report(now=NOW)["runtime"]["resolved_cycles"] == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"cycle_slot": None},
        {"cycle_slot": " "},
        {"cycle_slot": "x" * 129},
        {"action": "RESUME"},
        {"client_id": "order"},
        {"alert_sequence": 1},
    ],
)
def test_new_command_contract_binds_only_the_cycle_target(tmp_path, updates):
    *_, operator = context(tmp_path)
    with pytest.raises(ValueError):
        command(operator, **updates)


def test_six_action_canonical_signatures_and_saved_receipts_stay_compatible(tmp_path):
    *_, operator = context(tmp_path)
    request = command(operator, action="HALT", cycle_slot=None)
    legacy = request.model_dump(mode="json")
    del legacy["cycle_slot"]
    payload = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(KEY, payload.encode(), hashlib.sha256).hexdigest()
    assert signature == sign_command(request, KEY)
    assert (
        operator.apply(OperatorCommand.model_validate(legacy), signature, now=NOW)["status"]
        == "APPLIED"
    )
    assert operator.apply(request, signature, now=NOW)["replayed"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing", "PAPER_CYCLE_NOT_FOUND"),
        ("claimed", "PAPER_CYCLE_NOT_INTERRUPTED"),
        ("complete", "PAPER_CYCLE_NOT_INTERRUPTED"),
        ("other-claim", "PAPER_CLAIM_REQUIRES_STARTUP_REVIEW"),
        ("resumed", "CYCLE_RESOLUTION_REQUIRES_HALT"),
        ("future", "CYCLE_RESOLUTION_TIME_REGRESSION"),
        ("running", "PAPER_RUNTIME_NOT_STOPPED"),
        ("stopping", "PAPER_RUNTIME_NOT_STOPPED"),
        ("foreign-account", "EXECUTION_ACCOUNT_MISMATCH"),
        ("missing-snapshot", "RECONCILIATION_REQUIRED"),
        ("issues", "RECONCILIATION_REQUIRED"),
    ],
)
def test_evidence_and_lifecycle_guards_never_remove_blocker(tmp_path, change, reason):
    _, engine, _, _, _, _, operator = context(tmp_path)
    with engine.journal.write() as db:
        if change == "missing":
            db.execute("DELETE FROM execution_runtime_cycles")
        elif change in {"claimed", "complete"}:
            db.execute("UPDATE execution_runtime_cycles SET status=?", (change.upper(),))
        elif change == "other-claim":
            db.execute(
                "INSERT INTO execution_runtime_cycles SELECT slot||':other',owner,'CLAIMED',started_at,completed_at,feed_sequence,feed_hash,packet_json,decision_json,result_json FROM execution_runtime_cycles"
            )
        elif change == "resumed":
            db.execute("UPDATE execution_control SET halted=0")
        elif change == "future":
            db.execute(
                "UPDATE execution_runtime_cycles SET completed_at=?",
                ((NOW + timedelta(seconds=1)).isoformat(),),
            )
        elif change in {"running", "stopping"}:
            db.execute("UPDATE execution_runtime SET status=?", (change.upper(),))
        elif change == "missing-snapshot":
            db.execute("UPDATE execution_control SET snapshot_json=NULL")
        elif change == "issues":
            db.execute("UPDATE execution_control SET issues_json='[\"UNRESOLVED\"]'")
        else:
            row = db.execute("SELECT snapshot_json FROM execution_control").fetchone()[0]
            snap = Snapshot.model_validate_json(row).model_copy(update={"account_id": "foreign"})
            db.execute("UPDATE execution_control SET snapshot_json=?", (snap.model_dump_json(),))
    result = apply(operator, command(operator))
    assert result["reason"] == reason
    assert engine.journal.report(now=NOW)["runtime"]["resolved_cycles"] == 0


@pytest.mark.parametrize("offset", [-1, 91])
def test_future_or_stale_account_requires_new_reconciliation(tmp_path, offset):
    _, engine, _, _, _, _, operator = context(tmp_path)
    at = NOW + timedelta(seconds=offset)
    assert apply(operator, command(operator, at=at), now=at)["reason"] in {
        "STALE_EXECUTION_SNAPSHOT",
        "CYCLE_RESOLUTION_TIME_REGRESSION",
    }
    assert engine.journal.report(now=NOW)["runtime"]["unresolved_cycles"] == 1


def test_current_revision_signature_and_lease_are_required(tmp_path):
    _, engine, _, _, _, _, operator = context(tmp_path)
    request = command(operator)
    with pytest.raises(ValueError, match="authentication"):
        operator.apply(
            request.model_copy(update={"cycle_slot": "different"}),
            sign_command(request, KEY),
            now=NOW,
        )
    engine.halt("New evidence after review", now=NOW)
    assert apply(operator, request)["reason"] == "OPERATOR_REVIEW_STALE"
    request = command(operator)
    with runtime_lease(engine.journal.path):
        assert apply(operator, request)["reason"] == "PAPER_RUNTIME_RUNNING"
    assert engine.journal.report(now=NOW)["runtime"]["resolved_cycles"] == 0


@pytest.mark.parametrize("target", ["receipt", "event", "authority"])
def test_storage_failure_rolls_back_resolution_original_evidence_and_authority(tmp_path, target):
    _, engine, _, _, _, _, operator = context(tmp_path)
    from app.execution.restore import authority_path

    if target == "authority":
        with sqlite3.connect(authority_path(engine.journal.path)) as db:
            db.execute(
                "CREATE TRIGGER fail_advance BEFORE UPDATE ON restore_authority BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
            )
    else:
        with engine.journal.write() as db:
            db.execute(
                "CREATE TRIGGER execution_fail BEFORE INSERT ON "
                + ("execution_commands" if target == "receipt" else "execution_events")
                + " BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
            )
    request = command(operator)
    before = pair(engine)
    with pytest.raises(sqlite3.IntegrityError):
        apply(operator, request)
    assert (
        pair(engine) == before and engine.journal.report(now=NOW)["runtime"]["resolved_cycles"] == 0
    )
    with runtime_lease(engine.journal.path):
        pass


@pytest.mark.anyio
async def test_resolution_keeps_same_slot_closed_and_requires_separate_resume(tmp_path):
    runtime, engine, venue, _, feed, clock, operator = context(tmp_path)
    assert apply(operator, command(operator))["status"] == "APPLIED"
    runtime._claim()
    runtime.supervisor._claim()
    assert await runtime.cycle_once() == {"status": "SKIPPED", "reason": "SLOT_ALREADY_ATTEMPTED"}
    clock[0] += timedelta(minutes=15)
    runtime._publish("RUNNING")
    feed.publish("later", packet(clock[0]))
    engine.reconcile(venue.snapshot(clock[0]), now=clock[0])
    await runtime.supervisor._tick()
    assert (await runtime.cycle_once())["status"] == "SKIPPED" and engine.journal.report()["halted"]
    resume = command(operator, action="RESUME", cycle_slot=None, at=clock[0])
    assert apply(operator, resume, now=clock[0])["status"] == "APPLIED"
    await runtime.supervisor._tick()
    assert (await runtime.cycle_once())["status"] == "COMPLETE"
    report = engine.journal.report(now=clock[0])
    assert report["runtime"]["cycles"] == {"INTERRUPTED": 1, "COMPLETE": 1}
    assert report["runtime"]["resolved_cycles"] == 1 and venue.submit_count == 0
    runtime._publish("STOPPED")
    runtime.supervisor._finish("STOPPED")


@pytest.mark.anyio
async def test_unknown_model_receipt_cannot_be_resolved_or_retried(tmp_path):
    runtime, engine, _, _, _, _, operator = context(tmp_path, model=True)
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    engine.resume("Initial fixture account reviewed", now=NOW)
    await runtime.supervisor._tick()
    assert runtime.judgment.costs.begin(
        SLOT, packet(), now=NOW, expected_revision=operator.review()["revision"]
    )["invoke_model"]
    runtime._publish("STOPPED")
    runtime.supervisor._finish("STOPPED")
    engine.halt("Interrupted model", now=NOW)
    assert apply(operator, command(operator))["reason"] == "EXECUTION_MODEL_COST_UNKNOWN"
    report = engine.journal.report(now=NOW)
    assert (
        report["runtime"]["unresolved_cycles"] == 1
        and report["economics"]["unknown_calls"] == 1
        and report["halted"]
    )


@pytest.mark.anyio
async def test_known_judgment_and_terminal_order_allow_resolution_without_fill_release(
    tmp_path, monkeypatch
):
    runtime, engine, venue, _, _, _, operator = context(tmp_path, model=True)
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    engine.resume("Account reviewed before fixture model", now=NOW)
    await runtime.supervisor._tick()

    async def known(request, key):
        return JudgmentResult(
            decision=decision(),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="known-cycle", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", known)
    outcome = await runtime.judgment.decide(
        SLOT, packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    with engine.journal.write() as db:
        db.execute(
            "UPDATE execution_runtime_cycles SET packet_json=?", (outcome.packet.model_dump_json(),)
        )
    intent = engine.prepare(SLOT, outcome.result.decision, outcome.packet, now=NOW)
    assert (
        await engine.dispatch_async(intent.client_id, venue, now=NOW, packet=outcome.packet)
        == "OPEN"
    )
    runtime._publish("STOPPED")
    runtime.supervisor._finish("STOPPED")
    assert apply(operator, command(operator))["reason"] == "ORDER_ALREADY_IN_FLIGHT"
    # Explicit local fixture outcome; never a broker cancellation.
    venue.terminal(intent.client_id, "CANCELED", NOW)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    before = engine.journal.report(now=NOW)
    assert apply(operator, command(operator))["status"] == "APPLIED"
    after = engine.journal.report(now=NOW)
    assert (
        after["orders"] == before["orders"]
        and after["fills"] == before["fills"]
        and venue.submit_count == 1
    )
    assert after["economics"]["known_cost"] == "0.00015" and after["halted"]
    assert after["runtime"]["resolved_cycles"] == 1


def test_changed_resolved_claim_does_not_silently_remove_new_blocker(tmp_path):
    _, engine, _, _, _, _, operator = context(tmp_path)
    assert apply(operator, command(operator))["status"] == "APPLIED"
    with engine.journal.write() as db:
        db.execute("UPDATE execution_runtime_cycles SET owner='unexpected-change'")
    assert engine.journal.report(now=NOW)["runtime"]["unresolved_cycles"] == 1


def test_signed_http_resolution_uses_existing_transport_and_preserves_halt(tmp_path):
    _, engine, _, _, _, _, operator = context(tmp_path)
    key_path, token_path = tmp_path / "signing.key", tmp_path / "read.token"
    for path, value in ((key_path, KEY.hex()), (token_path, "72" * 32)):
        path.write_text(value + "\n")
        path.chmod(0o600)
    app = create_control_app(
        engine,
        ControlAPIConfig(origin="https://control.test"),
        operator_key_file=key_path,
        read_token_file=token_path,
        clock=lambda: NOW,
    )
    request = command(operator)
    with TestClient(
        app, base_url="https://control.test", headers={"Authorization": "Bearer " + "72" * 32}
    ) as client:
        before = client.get("/v1/review").json()
        assert before["runtime"]["unresolved_cycles"] == 1
        response = client.post(
            "/v1/commands",
            json={
                "command": request.model_dump(mode="json"),
                "signature": sign_command(request, KEY),
            },
        )
        assert response.status_code == 200 and response.json()["status"] == "APPLIED"
        review = client.get("/v1/review").json()
        assert review["runtime"]["resolved_cycles"] == 1 and review["halted"]
        replay = client.post(
            "/v1/commands",
            json={
                "command": request.model_dump(mode="json"),
                "signature": sign_command(request, KEY),
            },
        )
        assert replay.json()["replayed"]


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["fresh", "stale", "issue"])
async def test_owned_position_resolution_retains_risk_and_requires_fresh_supervision(
    tmp_path, monkeypatch, state
):
    runtime, engine, venue, _, _, _, operator = context(tmp_path, model=True)
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    engine.resume("Account evidence reviewed", now=NOW)
    await runtime.supervisor._tick()

    async def known(request, key):
        return JudgmentResult(
            decision=decision(),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="owned-entry", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", known)
    outcome = await runtime.judgment.decide(
        SLOT, packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    with engine.journal.write() as db:
        db.execute(
            "UPDATE execution_runtime_cycles SET packet_json=?", (outcome.packet.model_dump_json(),)
        )
    intent = engine.prepare(SLOT, outcome.result.decision, outcome.packet, now=NOW)
    assert (
        await engine.dispatch_async(intent.client_id, venue, now=NOW, packet=outcome.packet)
        == "OPEN"
    )
    venue.fill(intent.client_id, intent.quantity, Decimal(10), NOW, fill_id="owned")
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    engine.supervise(packet(), now=NOW)
    runtime._publish("STOPPED")
    runtime.supervisor._finish("STOPPED")
    if state != "fresh":
        with engine.journal.write() as db:
            saved = json.loads(
                db.execute("SELECT ledger_json FROM execution_control").fetchone()[0]
            )
            if state == "stale":
                saved["management"]["last_quote_at"] = (NOW - timedelta(seconds=91)).isoformat()
            else:
                saved["management"]["supervision_issue"] = "POSITION_QUOTE_MISSING"
            db.execute("UPDATE execution_control SET ledger_json=?", (json.dumps(saved),))
    before = engine.journal.report(now=NOW)
    result = apply(operator, command(operator))
    after = engine.journal.report(now=NOW)
    assert (
        after["ledger"] == before["ledger"]
        and after["orders"] == before["orders"]
        and after["halted"]
    )
    assert after["ledger"]["position"] is not None and venue.submit_count == 1
    assert result["status"] == ("APPLIED" if state == "fresh" else "REJECTED")
    if state != "fresh":
        assert result["reason"] == "FRESH_POSITION_SUPERVISION_REQUIRED"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change,reason",
    [
        ("packet", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
        ("cost", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
        ("identity", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
        ("decision", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
        ("audit", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
        ("policy", "JUDGMENT_CONFIGURATION_CHANGED"),
        ("violation", "EXECUTION_MODEL_EVIDENCE_VIOLATION"),
        ("cycle-decision", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
        ("counts", "EXECUTION_MODEL_DECISION_EVIDENCE_REQUIRED"),
    ],
)
async def test_resolution_requires_bound_model_policy_packet_usage_and_decision(
    tmp_path, monkeypatch, change, reason
):
    runtime, engine, _, _, _, _, operator = context(tmp_path, model=True)
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    engine.resume("Verified account", now=NOW)
    await runtime.supervisor._tick()

    async def known(request, key):
        return JudgmentResult(
            decision=decision("HOLD", None),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="known-hold", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", known)
    outcome = await runtime.judgment.decide(
        SLOT, packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    with engine.journal.write() as db:
        db.execute(
            "UPDATE execution_runtime_cycles SET packet_json=?", (outcome.packet.model_dump_json(),)
        )
        if change == "packet":
            db.execute("UPDATE execution_model_calls SET packet_hash=?", ("a" * 64,))
        elif change == "cost":
            db.execute("UPDATE execution_model_calls SET cost='0.00016'")
        elif change == "identity":
            db.execute("UPDATE execution_model_calls SET request_id='other'")
        elif change == "decision":
            db.execute("UPDATE execution_model_calls SET decision_hash=?", ("a" * 64,))
        elif change == "audit":
            db.execute("DELETE FROM execution_events WHERE kind='MODEL_JUDGMENT_RECORDED'")
        elif change == "policy":
            saved = json.loads(
                db.execute("SELECT policy_json FROM execution_cost_policy").fetchone()[0]
            )
            saved["model"] = "other"
            db.execute("UPDATE execution_cost_policy SET policy_json=?", (json.dumps(saved),))
        elif change == "cycle-decision":
            db.execute(
                "UPDATE execution_runtime_cycles SET decision_json=?",
                (decision().model_dump_json(),),
            )
        elif change == "counts":
            saved = json.loads(
                db.execute(
                    "SELECT payload FROM execution_events WHERE kind='MODEL_JUDGMENT_RECORDED'"
                ).fetchone()[0]
            )
            saved["result"]["counted_input_tokens"] = 999
            db.execute(
                "UPDATE execution_events SET payload=? WHERE kind='MODEL_JUDGMENT_RECORDED'",
                (json.dumps(saved),),
            )
        else:
            db.execute(
                "UPDATE execution_judgment_policy SET blocked_reason='MODEL_EVIDENCE_VIOLATION'"
            )
    runtime._publish("STOPPED")
    runtime.supervisor._finish("STOPPED")
    engine.halt("Interrupted after settled response", now=NOW)
    assert apply(operator, command(operator))["reason"] == reason
    assert engine.journal.report(now=NOW)["runtime"]["unresolved_cycles"] == 1


def test_missing_authority_rejects_resolution_before_mutation(tmp_path):
    _, engine, _, _, _, _, operator = context(tmp_path)
    from app.execution.restore import authority_path

    request = command(operator)
    authority_path(engine.journal.path).unlink()
    before = engine.journal.path.read_bytes()
    with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
        apply(operator, request)
    assert engine.journal.path.read_bytes() == before


def test_failed_runtime_still_requires_lifetime_lease_cleanup(tmp_path):
    _, engine, _, _, _, _, operator = context(tmp_path)
    with engine.journal.write() as db:
        db.execute("UPDATE execution_runtime SET status='FAILED'")
    with runtime_lease(engine.journal.path):
        assert apply(operator, command(operator))["reason"] == "PAPER_RUNTIME_RUNNING"
    assert apply(operator, command(operator))["status"] == "APPLIED"


@pytest.mark.parametrize(
    "action,targets",
    [
        ("HALT", {}),
        ("RESUME", {}),
        ("ACK_ALERT", {"alert_sequence": 1}),
        ("ABANDON_PREPARED", {"client_id": "prepared"}),
        ("ROTATE_KEY", {"replacement_fingerprint": "a" * 64}),
        ("REVOKE_KEY", {}),
    ],
)
def test_every_existing_action_keeps_legacy_canonical_signature(tmp_path, action, targets):
    *_, operator = context(tmp_path)
    request = command(operator, action=action, cycle_slot=None, **targets)
    legacy = request.model_dump(mode="json")
    del legacy["cycle_slot"]
    body = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
    assert sign_command(request, KEY) == hmac.new(KEY, body.encode(), hashlib.sha256).hexdigest()
