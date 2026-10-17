import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from app.config import Settings
from app.execution.cli import main
from app.execution.engine import ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal
from app.execution.operator import OperatorControl, sign_command
from app.execution.restore import authority_path
from tests.test_execution_operator import KEY, command
from tests.test_execution_rehearsal import NOW, decision, packet

KEY2 = b"second-offline-operator-key-32-bytes"
KEY3 = b"third-offline-operator-key-32-bytes!"


def fingerprint(key):
    return hashlib.sha256(key).hexdigest()


def request(operator, key, action, **updates):
    envelope = command(operator, action, **updates)
    return operator.apply(envelope, sign_command(envelope, key), now=NOW)


@pytest.fixture
def context(tmp_path):
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(tmp_path / "recovery.db", settings)
    venue = LocalFixtureVenue(Decimal(10))
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    OperatorControl.enroll(engine, KEY, now=NOW)
    return engine, venue, settings, OperatorControl(engine, KEY)


@pytest.fixture
def fenced(context):
    engine, venue, settings, operator = context
    assert engine.journal.enable_restore_fence(now=NOW)["status"] == "VERIFIED"
    return engine, venue, settings, operator


def test_rotation_retires_key_halts_and_requires_new_generation(fenced):
    engine, _, settings, operator = fenced
    pending = command(operator, "RESUME")
    result = request(operator, KEY, "ROTATE_KEY", replacement_fingerprint=fingerprint(KEY2))
    assert result["status"] == "APPLIED" and engine.journal.report()["halted"]
    with pytest.raises(ValueError, match="retired"):
        operator.review()
    with pytest.raises(ValueError):
        operator.apply(pending, sign_command(pending, KEY), now=NOW)
    with pytest.raises(ValueError):
        OperatorControl(engine, KEY)
    new = OperatorControl(ExecutionEngine(engine.journal.path, settings), KEY2)
    assert new.credential_generation == 2
    with pytest.raises(ValueError):
        new.apply(pending, sign_command(pending, KEY2), now=NOW)
    assert request(new, KEY2, "RESUME")["status"] == "APPLIED"
    assert engine.journal.report()["restore_fence"]["status"] == "VERIFIED"
    assert KEY2 not in engine.journal.path.read_bytes()


def test_revocation_blocks_all_commands_and_local_recovery_keeps_halt(fenced):
    engine, _, settings, operator = fenced
    before = command(operator)
    assert request(operator, KEY, "REVOKE_KEY")["status"] == "APPLIED"
    for action in ("HALT", "RESUME", "REVOKE_KEY"):
        with pytest.raises(ValueError):
            request(operator, KEY, action)
    with pytest.raises(ValueError):
        OperatorControl.enroll(engine, KEY, now=NOW)
    with pytest.raises(ValueError):
        OperatorControl.recover_revoked(engine, KEY, "retired", now=NOW)
    assert (
        OperatorControl.recover_revoked(engine, KEY2, "fresh capability after review", now=NOW) == 3
    )
    assert engine.journal.report()["halted"]
    new = OperatorControl(ExecutionEngine(engine.journal.path, settings), KEY2)
    with pytest.raises(ValueError):
        new.apply(before, sign_command(before, KEY2), now=NOW)
    assert request(new, KEY2, "RESUME")["status"] == "APPLIED"


def test_retired_credentials_never_revive_in_rotation_or_local_recovery(fenced):
    engine, _, _, operator = fenced
    assert (
        request(operator, KEY, "ROTATE_KEY", replacement_fingerprint=fingerprint(KEY2))["status"]
        == "APPLIED"
    )
    new = OperatorControl(engine, KEY2)
    for key in (KEY, KEY2):
        assert (
            request(new, KEY2, "ROTATE_KEY", replacement_fingerprint=fingerprint(key))["reason"]
            == "DIFFERENT_OPERATOR_KEY_REQUIRED"
        )
    request(new, KEY2, "REVOKE_KEY")
    for key in (KEY, KEY2):
        with pytest.raises(ValueError):
            OperatorControl.recover_revoked(engine, key, "cannot reuse", now=NOW)
    assert OperatorControl.recover_revoked(engine, KEY3, "new key", now=NOW) == 4


def test_rotation_and_revocation_safety_when_review_changes(fenced):
    engine, venue, _, operator = fenced
    rotate = command(operator, "ROTATE_KEY", replacement_fingerprint=fingerprint(KEY2))
    revoke = command(operator, "REVOKE_KEY")
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    assert (
        operator.apply(rotate, sign_command(rotate, KEY), now=NOW)["reason"]
        == "OPERATOR_REVIEW_STALE"
    )
    assert operator.apply(revoke, sign_command(revoke, KEY), now=NOW)["status"] == "APPLIED"


def test_credential_receipt_failure_rolls_back_retirement_and_authority(fenced):
    engine, _, _, operator = fenced
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_fail_command BEFORE INSERT ON execution_commands BEGIN SELECT RAISE(ABORT,'fixture receipt failed'); END"
        )
    before = engine.journal.report()
    guard = authority_path(engine.journal.path).read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        request(operator, KEY, "ROTATE_KEY", replacement_fingerprint=fingerprint(KEY2))
    assert engine.journal.report() == before
    assert authority_path(engine.journal.path).read_bytes() == guard
    assert OperatorControl(engine, KEY).credential_generation == 1
    with engine.journal.read() as db:
        assert not db.execute("SELECT * FROM execution_retired_keys").fetchall()


def test_competing_rotations_accept_only_one_current_credential(fenced):
    engine, _, _, operator = fenced
    envelopes = [
        command(operator, "ROTATE_KEY", replacement_fingerprint=fingerprint(k))
        for k in (KEY2, KEY3)
    ]

    def attempt(envelope):
        try:
            return operator.apply(envelope, sign_command(envelope, KEY), now=NOW)["status"]
        except ValueError:
            return "AUTHENTICATION_REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, envelopes))
    assert sorted(results) == ["APPLIED", "AUTHENTICATION_REJECTED"]
    assert engine.journal.report()["halted"]


def test_fence_is_explicit_idempotent_private_and_read_only(fenced):
    engine, _, settings, _ = fenced
    original = engine.journal.report()["restore_fence"]
    assert engine.journal.enable_restore_fence(now=NOW) == original
    guard_path = authority_path(engine.journal.path)
    assert guard_path.stat().st_mode & 0o777 == 0o600
    before = (engine.journal.path.read_bytes(), guard_path.read_bytes())
    assert ExecutionJournal(engine.journal.path).report()["restore_fence"] == original
    assert before == (engine.journal.path.read_bytes(), guard_path.read_bytes())
    restarted = ExecutionEngine(engine.journal.path, settings)
    current = restarted.journal.report()["restore_fence"]
    assert current["status"] == "VERIFIED" and current["generation"] > original["generation"]
    with pytest.raises(ValueError, match="read-only"):
        ExecutionJournal(engine.journal.path).enable_restore_fence(now=NOW)


def test_journal_only_restore_cannot_undo_revocation_or_recreate_authority(fenced):
    engine, venue, settings, operator = fenced
    older = engine.journal.path.read_bytes()
    request(operator, KEY, "REVOKE_KEY")
    current_guard = authority_path(engine.journal.path).read_bytes()
    engine.journal.path.write_bytes(older)
    report = ExecutionJournal(engine.journal.path).report()
    assert report["restore_fence"]["status"] == "BLOCKED"
    with pytest.raises(ValueError, match="RESTORED_OR_CHANGED"):
        ExecutionEngine(engine.journal.path, settings)
    for operation in (
        lambda: engine.reconcile(venue.snapshot(NOW), now=NOW),
        lambda: engine.prepare("cannot-enter", decision(), packet(), now=NOW),
        lambda: engine.halt("cannot rewrite stale journal", now=NOW),
        lambda: engine.journal.enable_restore_fence(now=NOW),
        lambda: request(operator, KEY, "RESUME"),
        lambda: OperatorControl.recover_revoked(engine, KEY2, "cannot trust restore", now=NOW),
    ):
        with pytest.raises(ValueError, match="RESTORED_OR_CHANGED"):
            operation()
    assert engine.journal.path.read_bytes() == older
    assert authority_path(engine.journal.path).read_bytes() == current_guard


def test_restored_prepared_intent_cannot_repeat_accepted_order(fenced):
    engine, venue, settings, _ = fenced
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    older = engine.journal.path.read_bytes()
    venue.lose_next_ack = True
    assert engine.dispatch(intent.client_id, venue, now=NOW, packet=packet()) == "UNKNOWN"
    engine.journal.path.write_bytes(older)
    with pytest.raises(ValueError, match="RESTORED_OR_CHANGED"):
        engine.dispatch(intent.client_id, venue, now=NOW, packet=packet())
    assert venue.submit_count == 1
    with pytest.raises(ValueError):
        ExecutionEngine(engine.journal.path, settings)


def test_restore_before_fence_enrollment_is_detected_by_retained_sidecar(context):
    engine, _, settings, _ = context
    older = engine.journal.path.read_bytes()
    engine.journal.enable_restore_fence(now=NOW)
    engine.journal.path.write_bytes(older)
    assert engine.journal.report()["restore_fence"]["reason"] == "RESTORE_FENCE_BINDING_MISSING"
    with pytest.raises(ValueError, match="BINDING_MISSING"):
        ExecutionEngine(engine.journal.path, settings)


@pytest.mark.parametrize("which", ["authority", "journal"])
def test_missing_file_is_never_silently_recreated(fenced, which):
    engine, _, settings, _ = fenced
    target = authority_path(engine.journal.path) if which == "authority" else engine.journal.path
    target.unlink()
    with pytest.raises((ValueError, sqlite3.Error)):
        engine.halt("missing proof", now=NOW)
    with pytest.raises(ValueError):
        ExecutionEngine(engine.journal.path, settings)
    assert not target.exists()


def test_same_revision_state_tampering_and_foreign_authority_are_detected(
    fenced, context, tmp_path
):
    engine, _, _, _ = fenced
    guard = authority_path(engine.journal.path)
    original = engine.journal.path.read_bytes()
    with sqlite3.connect(engine.journal.path) as db:
        db.execute("UPDATE execution_control SET halted=1,halt_reason='untracked change'")
    assert (
        engine.journal.report()["restore_fence"]["reason"]
        == "RESTORED_OR_CHANGED_EXECUTION_JOURNAL"
    )
    engine.journal.path.write_bytes(original)
    # Even a valid authority belonging to another journal cannot be adopted.
    foreign_path = tmp_path / "foreign.db"
    foreign = ExecutionEngine(foreign_path, context[2])
    foreign.journal.enable_restore_fence(now=NOW)
    guard.write_bytes(authority_path(foreign_path).read_bytes())
    assert (
        engine.journal.report()["restore_fence"]["reason"] == "RESTORE_AUTHORITY_BINDING_MISMATCH"
    )
    with pytest.raises(ValueError):
        engine.halt("foreign authority", now=NOW)


def test_authority_update_failure_rolls_back_both_files(fenced):
    engine, _, _, _ = fenced
    guard = authority_path(engine.journal.path)
    with sqlite3.connect(guard) as db:
        db.execute(
            "CREATE TRIGGER fail_advance BEFORE UPDATE ON restore_authority BEGIN SELECT RAISE(ABORT,'authority failed'); END"
        )
    before = (engine.journal.path.read_bytes(), guard.read_bytes())
    with pytest.raises(sqlite3.IntegrityError):
        engine.halt("cannot commit one half", now=NOW)
    assert before == (engine.journal.path.read_bytes(), guard.read_bytes())
    assert engine.journal.report()["restore_fence"]["status"] == "VERIFIED"


@pytest.mark.parametrize("which", ["main", "authority"])
def test_wal_mode_fails_closed_without_changing_persistent_mode(fenced, which):
    engine, _, _, _ = fenced
    target = engine.journal.path if which == "main" else authority_path(engine.journal.path)
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    assert (
        engine.journal.report()["restore_fence"]["reason"]
        == "RESTORE_FENCE_REQUIRES_DELETE_JOURNAL"
    )
    with pytest.raises(ValueError, match="DELETE_JOURNAL"):
        engine.halt("unsupported transaction mode", now=NOW)
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_concurrent_writes_and_exception_rollback_keep_pair_consistent(fenced):
    engine, _, _, _ = fenced
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda n: engine.halt(f"fixture halt {n}", now=NOW), range(6)))
    assert engine.journal.report()["restore_fence"]["status"] == "VERIFIED"
    before = engine.journal.report()
    with pytest.raises(RuntimeError), engine.journal.write() as db:
        db.execute("UPDATE execution_control SET halted=0")
        raise RuntimeError("cancel transaction")
    assert engine.journal.report() == before


def test_actual_child_crash_before_two_file_commit_recovers_pair(fenced):
    engine, _, settings, _ = fenced
    script = """
import os, sys
from datetime import datetime
from app.config import Settings
from app.execution.engine import ExecutionEngine
from app.execution.restore import advance
engine = ExecutionEngine(sys.argv[1], Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10))
with engine.journal.write() as db:
    db.execute("UPDATE execution_control SET halted=1,halt_reason='uncommitted crash'")
    advance(db)
    os._exit(97)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(engine.journal.path)],
        cwd=os.getcwd(),
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 97, result.stderr.decode()
    restarted = ExecutionEngine(engine.journal.path, settings)
    report = restarted.journal.report()
    assert report["restore_fence"]["status"] == "VERIFIED" and not report["halted"]


def test_unfenced_journals_and_both_file_rollback_limit_are_explicit(context):
    engine, _, _, operator = context
    assert engine.journal.report()["restore_fence"]["status"] == "UNFENCED"
    engine.journal.enable_restore_fence(now=NOW)
    guard = authority_path(engine.journal.path)
    older = (engine.journal.path.read_bytes(), guard.read_bytes())
    request(operator, KEY, "REVOKE_KEY")
    engine.journal.path.write_bytes(older[0])
    guard.write_bytes(older[1])
    # Local retained state cannot prove time if BOTH files are rolled back.
    assert engine.journal.report()["restore_fence"]["status"] == "VERIFIED"


@pytest.mark.parametrize(
    "updates",
    [
        {"action": "ROTATE_KEY"},
        {"replacement_fingerprint": "0" * 64},
        {"action": "ROTATE_KEY", "replacement_fingerprint": "x" * 64},
        {"credential_generation": 0},
        {"credential_generation": True},
    ],
)
def test_credential_contract_is_revalidated(context, updates):
    with pytest.raises(ValueError):
        command(context[3], **updates)


def test_recovery_cli_persists_known_current_pair_and_refuses_overwrite(tmp_path, capsys):
    path = tmp_path / "recovery-cli.db"
    assert main(["recovery-run", "--db", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "OK" and report["restored_journal_blocked"]
    assert not report["live_enabled"] and not report["network_calls"] and not report["halted"]
    assert report["restore_fence"]["status"] == "VERIFIED"
    assert report["orders"][0]["status"] == "CANCELED" and not report["fills"]
    guard = authority_path(path)
    before = (path.read_bytes(), guard.read_bytes())
    assert ExecutionJournal(path).report()["restore_fence"] == report["restore_fence"]
    assert before == (path.read_bytes(), guard.read_bytes())
    assert main(["recovery-run", "--db", str(path)]) == 1
    assert before == (path.read_bytes(), guard.read_bytes())


def test_failed_fence_initialization_is_not_silently_rebound(context):
    engine, _, settings, _ = context
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_fail_event BEFORE INSERT ON execution_events BEGIN SELECT RAISE(ABORT,'fixture initialization failed'); END"
        )
    before = engine.journal.path.read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        engine.journal.enable_restore_fence(now=NOW)
    assert engine.journal.path.read_bytes() == before
    assert authority_path(engine.journal.path).exists()
    assert engine.journal.report()["restore_fence"]["status"] == "BLOCKED"
    with pytest.raises(ValueError):
        engine.journal.enable_restore_fence(now=NOW)
    with pytest.raises(ValueError):
        ExecutionEngine(engine.journal.path, settings)
