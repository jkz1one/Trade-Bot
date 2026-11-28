import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.config import Settings
from app.execution.cli import main
from app.execution.engine import ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal
from app.execution.operator import OperatorCommand, OperatorControl, sign_command
from tests.test_execution_rehearsal import NOW, decision, packet

KEY = b"offline-test-operator-key-32-bytes!"


@pytest.fixture
def context(tmp_path):
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(tmp_path / "operator.db", settings)
    venue = LocalFixtureVenue(Decimal(10))
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    OperatorControl.enroll(engine, KEY, now=NOW)
    return engine, venue, settings, OperatorControl(engine, KEY)


def command(operator, action="HALT", at=NOW, **updates):
    return OperatorCommand(
        **{
            "journal_id": operator.journal_id,
            "command_id": str(uuid4()),
            "actor": "fixture-operator",
            "action": action,
            "reason": "Reviewed saved fixture evidence",
            "expected_revision": operator.review()["revision"],
            "issued_at": at,
            "expires_at": at + timedelta(minutes=1),
            "credential_generation": operator.credential_generation,
            **updates,
        }
    )


def apply(operator, request, at=NOW):
    return operator.apply(request, sign_command(request, KEY), now=at)


def test_key_enrollment_is_explicit_immutable_and_secret_not_in_audit(context):
    engine, _, settings, operator = context
    revision = operator.review()["revision"]
    assert OperatorControl.enroll(engine, KEY, now=NOW) == operator.journal_id
    assert operator.review()["revision"] == revision
    for key in (b"short", b"x" * 32):
        with pytest.raises(ValueError):
            OperatorControl(engine, key)
        with pytest.raises(ValueError):
            OperatorControl.enroll(engine, key, now=NOW)
    reopened = ExecutionEngine(engine.journal.path, settings)
    assert OperatorControl(reopened, KEY).journal_id == operator.journal_id
    assert KEY not in engine.journal.path.read_bytes()
    assert "key_hash" not in json.dumps(operator.review())


@pytest.mark.parametrize("signature", ["", "x" * 64, "0" * 64, "é" * 64, None])
def test_invalid_signatures_never_mutate(context, signature):
    engine, _, _, operator = context
    original = engine.journal.path.read_bytes()
    with pytest.raises(ValueError, match="authentication"):
        operator.apply(command(operator), signature, now=NOW)
    assert engine.journal.path.read_bytes() == original


def test_signed_envelope_cannot_be_tampered_or_cross_journal(context, tmp_path):
    engine, _, settings, operator = context
    request = command(operator)
    signature = sign_command(request, KEY)
    with pytest.raises(ValueError, match="authentication"):
        operator.apply(request.model_copy(update={"action": "RESUME"}), signature, now=NOW)
    foreign = ExecutionEngine(tmp_path / "other.db", settings)
    OperatorControl.enroll(foreign, KEY, now=NOW)
    control = OperatorControl(foreign, KEY)
    with pytest.raises(ValueError, match="binding"):
        control.apply(request, signature, now=NOW)
    assert not engine.journal.report()["halted"] and not foreign.journal.report()["halted"]


@pytest.mark.parametrize(
    "updates",
    [
        {"actor": " "},
        {"reason": " "},
        {"action": "PLACE_ORDER"},
        {"client_id": "order"},
        {"alert_sequence": 1},
        {"action": "ACK_ALERT"},
        {"action": "ABANDON_PREPARED"},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"expires_at": NOW},
        {"expires_at": NOW + timedelta(seconds=301)},
        {"issued_at": NOW.replace(tzinfo=None)},
    ],
)
def test_command_contract_rejects_unbounded_or_wrong_authority(context, updates):
    operator = context[3]
    with pytest.raises(ValueError):
        command(operator, **updates)
    # Even model_copy cannot bypass post-parse validation in the signer.
    with pytest.raises(ValueError):
        sign_command(command(operator).model_copy(update=updates), KEY)


@pytest.mark.parametrize(
    "at,reason",
    [
        (NOW - timedelta(seconds=1), "COMMAND_FROM_FUTURE"),
        (NOW + timedelta(minutes=1), "COMMAND_EXPIRED"),
    ],
)
def test_expired_or_future_requests_get_durable_rejected_receipt(context, at, reason):
    engine, _, settings, operator = context
    request = command(operator)
    result = apply(operator, request, at)
    assert result["status"] == "REJECTED" and result["reason"] == reason
    assert not operator.review()["halted"]
    restarted = OperatorControl(ExecutionEngine(engine.journal.path, settings), KEY)
    assert apply(restarted, request, NOW + timedelta(days=1))["replayed"]
    assert not restarted.review()["halted"]


def test_halt_allows_changed_review_but_resume_requires_exact_revision(context):
    engine, venue, _, operator = context
    halt = command(operator)
    engine.reconcile(venue.snapshot(NOW + timedelta(seconds=1)), now=NOW + timedelta(seconds=1))
    assert apply(operator, halt)["status"] == "APPLIED"
    resume = command(operator, "RESUME")
    engine.reconcile(venue.snapshot(NOW + timedelta(seconds=2)), now=NOW + timedelta(seconds=2))
    result = apply(operator, resume, NOW + timedelta(seconds=2))
    assert result["reason"] == "OPERATOR_REVIEW_STALE" and operator.review()["halted"]
    assert (
        apply(
            operator,
            command(operator, "RESUME", at=NOW + timedelta(seconds=2)),
            NOW + timedelta(seconds=2),
        )["status"]
        == "APPLIED"
    )


def test_replay_does_not_rehalt_after_later_recovery_and_conflicts_rejected(context):
    _, _, _, operator = context
    halt = command(operator)
    result = apply(operator, halt)
    assert apply(operator, command(operator, "RESUME"))["status"] == "APPLIED"
    state = operator.review()
    assert apply(operator, halt, NOW + timedelta(days=1)) == {**result, "replayed": True}
    assert operator.review() == state
    with pytest.raises(ValueError, match="identity conflict"):
        apply(operator, halt.model_copy(update={"reason": "different content"}))


def test_concurrent_identical_requests_apply_once_and_distinct_stale_reviews_serialize(context):
    _, _, _, operator = context
    request = command(operator)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(operator, request), range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert sum(e["kind"] == "MANUAL_HALT" for e in operator.review()["events"]) == 1
    requests = [command(operator, "RESUME"), command(operator, "RESUME")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda r: apply(operator, r), requests))
    assert sorted(r["status"] for r in results) == ["APPLIED", "REJECTED"]
    assert any(r["reason"] == "OPERATOR_REVIEW_STALE" for r in results)


def test_command_receipt_failure_rolls_back_action_event_and_alert(context):
    engine, _, _, operator = context
    request = command(operator)
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON execution_commands BEGIN SELECT RAISE(ABORT,'fixture storage failure'); END"
        )
    state = operator.review()
    with pytest.raises(sqlite3.IntegrityError):
        apply(operator, request)
    assert operator.review() == state
    with engine.journal.write() as db:
        db.execute("DROP TRIGGER fail_receipt")
    assert apply(operator, request)["status"] == "APPLIED"


def test_uncertain_order_cannot_be_abandoned_or_resumed_and_ack_is_not_recovery(context):
    engine, venue, settings, operator = context
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    venue.lose_next_ack = True
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet()) == "UNKNOWN"
    assert (
        apply(operator, command(operator, "ABANDON_PREPARED", client_id=intent.client_id))["reason"]
        == "ATTEMPTED_ORDER_REQUIRES_RECONCILIATION"
    )
    assert apply(operator, command(operator, "RESUME"))["reason"] == "ORDER_ALREADY_IN_FLIGHT"
    alert = engine.journal.alerts()[0]
    assert alert["kind"] == "ATTEMPT_UNCERTAIN"
    ack = command(operator, "ACK_ALERT", alert_sequence=alert["event_sequence"])
    assert apply(operator, ack)["status"] == "APPLIED"
    report = operator.review()
    assert (
        report["halted"] and report["orders"][0]["active"] and report["unacknowledged_alerts"] == 0
    )
    assert report["alerts"][0]["actor"] == ack.actor
    engine = ExecutionEngine(engine.journal.path, settings)
    operator = OperatorControl(engine, KEY)
    assert apply(operator, ack)["replayed"]
    assert (
        engine.dispatch(intent.client_id, venue, now=NOW) == "UNKNOWN" and venue.submit_count == 1
    )
    # Complete terminal venue evidence, not alert acknowledgment, releases ownership.
    venue.terminal(intent.client_id, "CANCELED", NOW)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    assert operator.review()["halted"]
    assert apply(operator, command(operator, "RESUME"))["status"] == "APPLIED"


def test_unattempted_abandonment_and_alert_target_checks(context):
    engine, _, _, operator = context
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    assert (
        apply(operator, command(operator, "ABANDON_PREPARED", client_id=intent.client_id))["status"]
        == "APPLIED"
    )
    row = operator.review()["orders"][0]
    assert row["status"] == "EXPIRED" and not row["active"] and row["attempted_at"] is None
    assert (
        apply(operator, command(operator, "ACK_ALERT", alert_sequence=999))["reason"]
        == "ALERT_NOT_FOUND"
    )
    apply(operator, command(operator))
    sequence = operator.review()["alerts"][0]["event_sequence"]
    assert (
        apply(operator, command(operator, "ACK_ALERT", alert_sequence=sequence))["status"]
        == "APPLIED"
    )
    assert (
        apply(operator, command(operator, "ACK_ALERT", alert_sequence=sequence))["reason"]
        == "ALERT_ALREADY_ACKNOWLEDGED"
    )


def test_stale_snapshot_and_config_cannot_be_waived_by_signed_resume(context):
    engine, _, _, operator = context
    apply(operator, command(operator))
    later = NOW + timedelta(seconds=91)
    assert (
        apply(operator, command(operator, "RESUME", at=later), later)["reason"]
        == "STALE_EXECUTION_SNAPSHOT"
    )
    engine.settings.live_enabled = True
    assert (
        apply(operator, command(operator, "RESUME"))["reason"] == "EXECUTION_CONFIGURATION_CHANGED"
    )
    assert apply(operator, command(operator))["status"] == "APPLIED"


def test_partial_position_requires_fresh_supervision_and_alerts_deduplicate(context):
    engine, venue, _, operator = context
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet()) == "OPEN"
    half = intent.quantity / 2
    venue.fill(intent.client_id, half, Decimal(10), NOW, fill_id="buy")
    venue.terminal(intent.client_id, "CANCELED", NOW)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    apply(operator, command(operator))
    assert (
        apply(operator, command(operator, "RESUME"))["reason"]
        == "FRESH_POSITION_SUPERVISION_REQUIRED"
    )
    p = packet(NOW, "9.4", "9.41")
    assert engine.supervise(p, now=NOW)["status"] == "EXIT_REQUIRED"
    count = operator.review()["unacknowledged_alerts"]
    engine.supervise(p, now=NOW)
    assert operator.review()["unacknowledged_alerts"] == count
    assert apply(operator, command(operator, "RESUME"))["status"] == "APPLIED"
    assert operator.review()["ledger"]["management"]["exit_reason"] == "INVALIDATION"
    later = NOW + timedelta(seconds=91)
    assert engine.reconcile(venue.snapshot(later), now=later)["reconciled"]
    engine.halt("review current position", now=later)
    assert (
        apply(operator, command(operator, "RESUME", at=later), later)["reason"]
        == "FRESH_POSITION_SUPERVISION_REQUIRED"
    )
    assert engine.supervise(p, now=later)["status"] == "BLOCKED"
    count = operator.review()["unacknowledged_alerts"]
    engine.supervise(p, now=later)
    assert operator.review()["unacknowledged_alerts"] == count
    fresh = packet(later, "9.4", "9.41")
    engine.supervise(fresh, now=later)
    assert apply(operator, command(operator, "RESUME", at=later), later)["status"] == "APPLIED"
    assert engine.prepare_protective_exit(fresh, now=later).side == "SELL"


def test_alert_pages_preserve_all_pending_events_and_read_only_report(context):
    engine, _, _, operator = context
    for n in range(105):
        engine.halt(f"fixture incident {n}", now=NOW)
    report = operator.review()
    assert report["unacknowledged_alerts"] == 105 and len(report["alerts"]) == 100
    page1 = engine.journal.alerts(limit=60)
    page2 = engine.journal.alerts(after=page1[-1]["event_sequence"], limit=60)
    assert len(page1 + page2) == 105
    original = engine.journal.path.read_bytes()
    assert ExecutionJournal(engine.journal.path).report() == {
        k: v for k, v in report.items() if not k.startswith("operator_")
    }
    # review adds only a caller-side journal identity; underlying report omits it.
    assert engine.journal.path.read_bytes() == original


def test_cli_saved_recovery_is_offline_and_never_overwrites(tmp_path, capsys):
    path = tmp_path / "operator-cli.db"
    assert main(["operator-run", "--db", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "OK" and not report["halted"] and not report["network_calls"]
    assert not report["live_enabled"] and len(report["orders"]) == 1
    assert report["orders"][0]["status"] == "CANCELED" and not report["fills"]
    assert report["unacknowledged_alerts"] == 0
    original = path.read_bytes()
    assert main(["operator-run", "--db", str(path)]) == 1
    assert path.read_bytes() == original


def test_alert_and_acknowledgment_storage_failures_roll_back(context):
    engine, _, _, operator = context
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER fail_alert BEFORE INSERT ON execution_alerts BEGIN SELECT RAISE(ABORT,'alert persistence failed'); END"
        )
    original = operator.review()
    with pytest.raises(sqlite3.IntegrityError):
        apply(operator, command(operator))
    assert operator.review() == original
    with engine.journal.write() as db:
        db.execute("DROP TRIGGER fail_alert")
    apply(operator, command(operator))
    sequence = operator.review()["alerts"][0]["event_sequence"]
    request = command(operator, "ACK_ALERT", alert_sequence=sequence)
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON execution_commands BEGIN SELECT RAISE(ABORT,'receipt persistence failed'); END"
        )
    original = operator.review()
    with pytest.raises(sqlite3.IntegrityError):
        apply(operator, request)
    assert operator.review() == original and original["unacknowledged_alerts"] == 1


def test_binding_is_rechecked_at_application_and_mac_not_persisted(context):
    engine, _, _, operator = context
    request = command(operator)
    signature = sign_command(request, KEY)
    apply(operator, request)
    assert signature.encode() not in engine.journal.path.read_bytes()
    with engine.journal.write() as db:
        db.execute("UPDATE execution_operator SET journal_id='changed-binding' WHERE id=1")
    with pytest.raises(ValueError, match="binding"):
        operator.apply(request, signature, now=NOW)


def test_reports_for_prior_journals_remain_read_only_without_silent_enrollment(context):
    engine, _, settings, _ = context
    with engine.journal.write() as db:
        for table in ("execution_alerts", "execution_commands", "execution_operator"):
            db.execute("DROP TABLE " + table)
    original = engine.journal.path.read_bytes()
    report = ExecutionJournal(engine.journal.path).report()
    assert report["alerts"] == [] and report["unacknowledged_alerts"] == 0
    assert engine.journal.path.read_bytes() == original
    reopened = ExecutionEngine(engine.journal.path, settings)
    with pytest.raises(ValueError, match="authentication"):
        OperatorControl(reopened, KEY)
    OperatorControl.enroll(reopened, KEY, now=NOW)
    assert OperatorControl(reopened, KEY).review()["revision"] > report["revision"]


def test_late_fills_invalidate_old_operator_review(context):
    engine, venue, _, operator = context
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    venue.lose_next_ack = True
    engine.dispatch(intent.client_id, venue, now=NOW, packet=packet())
    request = command(operator, "RESUME")
    venue.fill(intent.client_id, intent.quantity, Decimal(10), NOW, fill_id="late-buy")
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["new_fills"] == 1
    result = apply(operator, request)
    assert result["reason"] == "OPERATOR_REVIEW_STALE"
    assert operator.review()["halted"] and operator.review()["ledger"]["position"]
