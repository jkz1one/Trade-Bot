"""Signed, revision-bound reset preserves independent accounting and risk history."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_option_admission import NOW
from test_option_execution import owned
from test_option_loss_control import attempt, ready, trade

from app.options.engine import OptionExecution
from app.options.lifecycle import NativeLossPolicy
from app.options.observer import OptionObserver
from app.options.operator import OptionsControl, sign
from app.options.operator_cli import review, submit
from app.options.operator_inbox import CommandInbox, save
from app.options.operator_models import OptionsCommand

KEY = b"r" * 32
POLICY = NativeLossPolicy(max_consecutive_losses=1, cooldown_seconds=1800)
AFTER = NOW + timedelta(minutes=30)


def request(engine, at=AFTER, **changes):
    with engine.journal.read() as db:
        binding = db.execute("SELECT * FROM execution_operator").fetchone()
        values = {
            "journal_id": binding["journal_id"],
            "population_id": engine.limits.population_id,
            "credential_generation": binding["generation"],
            "command_id": uuid4().hex,
            "actor": "fixture-reviewer",
            "action": "RESET_LOSS_LOCK",
            "reason": "Reviewed completed losses and expired cooldown",
            "expected_revision": engine.journal.revision(db),
            "issued_at": at,
            "expires_at": at + timedelta(seconds=60),
        }
    return OptionsCommand(**(values | changes))


def apply(engine, command, at=AFTER):
    return OptionsControl(engine, KEY).apply(command, sign(command, KEY), now=at)


def lock(engine, venue, data, at=AFTER):
    OptionsControl.enroll(engine, KEY, now=NOW)
    trade(engine, venue, data, "loss", NOW)
    assert engine.refresh_loss_control(now=NOW)["locked"]
    ready(engine, venue, data, at)


def accounting(engine):
    with engine.journal.read() as db:
        return {
            table: [tuple(r) for r in db.execute("SELECT * FROM " + table)]
            for table in (
                "execution_option_loss_outcomes",
                "execution_fills",
                "execution_model_calls",
                "execution_option_receipts",
            )
        } | {"ledger": db.execute("SELECT ledger_json FROM execution_control").fetchone()[0]}


def test_reset_exact_boundary_preserves_history_halt_and_replays_read_only(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        lock(engine, venue, data)
        assert apply(engine, request(engine, action="HALT"))["status"] == "APPLIED"
        before = accounting(engine)
        command = request(engine)
        result = apply(engine, command)
        assert result["status"] == "APPLIED"
        state = engine.journal.report(now=AFTER)
        assert state["halted"]
        assert not state["loss_control"]["locked"]
        assert state["loss_control"]["consecutive_losses"] == 0
        assert state["loss_control"]["consumed_entries"] == 1
        assert accounting(engine) == before
        snapshot = engine.journal.path.read_bytes()
        replay = apply(engine, command, AFTER + timedelta(days=1))
        assert replay == result | {"replayed": True}
        assert engine.journal.path.read_bytes() == snapshot
        assert engine.refresh_loss_control(now=AFTER)["consecutive_losses"] == 0
        with engine.journal.read() as db:
            payload = json.loads(
                db.execute(
                    "SELECT payload FROM execution_events WHERE kind='NATIVE_LOSS_REVIEWED_RESET'"
                ).fetchone()[0]
            )
        assert payload["actor"] == command.actor
        assert payload["prior_state"]["consecutive_losses"] == 1
        assert payload["command_id"] == command.command_id
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, policy, venue, now=AFTER) as reopened:
        assert not reopened.refresh_loss_control(now=AFTER)["locked"]
        assert reopened.journal.report(now=AFTER)["halted"]


def test_next_loss_counts_once_after_reset(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        lock(engine, venue, data)
        assert apply(engine, request(engine))["status"] == "APPLIED"
        trade(engine, venue, data, "next", AFTER)
        state = engine.refresh_loss_control(now=AFTER)
        assert state["locked"] and state["consecutive_losses"] == 1
        assert state["consumed_entries"] == 2
        assert "NATIVE_LOSS_LOCKED" in attempt(engine, data, "blocked", AFTER)["reason"]


@pytest.mark.parametrize(
    "failure",
    [
        "cooldown",
        "stale_revision",
        "stale_account",
        "unknown_cost",
        "runtime_busy",
        "expired",
        "future",
    ],
)
def test_rejected_reset_preserves_lock_and_accounting(tmp_path, failure):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        at = AFTER - timedelta(seconds=1) if failure == "cooldown" else AFTER
        lock(engine, venue, data, at)
        if failure == "unknown_cost":
            with engine.journal.write() as db:
                db.execute(
                    "INSERT INTO execution_model_calls(source_key,packet_hash,started_at) VALUES('unknown','hash',?)",
                    (NOW.isoformat(),),
                )
        if failure == "runtime_busy":
            engine._option_runtime = SimpleNamespace(task=SimpleNamespace(done=lambda: False))
        command = request(engine, at)
        if failure == "stale_revision":
            assert apply(engine, request(engine, at, action="HALT"), at)["status"] == "APPLIED"
        if failure == "stale_account":
            at += timedelta(seconds=30)
        if failure == "expired":
            at += timedelta(seconds=60)
        if failure == "future":
            command = request(engine, at + timedelta(seconds=1))
        before = accounting(engine)
        result = apply(engine, command, at)
        assert result["status"] == "REJECTED", result
        expected = {
            "cooldown": "NATIVE_LOSS_COOLDOWN",
            "stale_revision": "OPTION_REVIEW_REVISION_CHANGED",
            "stale_account": "OPTION_RECOVERY_EVIDENCE_REQUIRED",
            "unknown_cost": "OPTION_RECOVERY_EVIDENCE_REQUIRED",
            "runtime_busy": "OPTION_RUNTIME_CYCLE_IN_PROGRESS",
            "expired": "COMMAND_EXPIRED",
            "future": "COMMAND_FROM_FUTURE",
        }
        assert expected[failure] in result["reason"]
        assert engine.journal.report(now=at)["loss_control"]["locked"]
        assert accounting(engine) == before
        assert venue.submit_count == 2


@pytest.mark.parametrize("enrolled", [False, True])
def test_reset_cannot_enroll_or_clear_an_unlocked_streak(tmp_path, enrolled):
    with owned(tmp_path, **({"loss_control": POLICY} if enrolled else {})) as (engine, _, _):
        OptionsControl.enroll(engine, KEY, now=NOW)
        result = apply(engine, request(engine, NOW), NOW)
        assert result["status"] == "REJECTED"
        assert result["reason"] == (
            "NATIVE_LOSS_RESET_REQUIRES_LOCK" if enrolled else "NATIVE_LOSS_NOT_ENROLLED"
        )


def test_reset_authentication_and_atomic_rollback(tmp_path, monkeypatch):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        lock(engine, venue, data)
        command = request(engine)
        before = engine.journal.path.read_bytes()
        with pytest.raises(ValueError):
            OptionsControl(engine, KEY).apply(command, "0" * 64, now=AFTER)
        assert engine.journal.path.read_bytes() == before
        event = engine.journal.event

        def fail(db, now, kind, payload):
            if kind == "OPTIONS_OPERATOR_COMMAND":
                raise RuntimeError("fixture receipt failure")
            return event(db, now, kind, payload)

        monkeypatch.setattr(engine.journal, "event", fail)
        with pytest.raises(RuntimeError, match="receipt failure"):
            apply(engine, command)
        assert engine.journal.path.read_bytes() == before
        monkeypatch.setattr(engine.journal, "event", event)
        assert apply(engine, command)["status"] == "APPLIED"


def test_consumed_outcome_corruption_cannot_be_reset(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        lock(engine, venue, data)
        with engine.journal.write() as db:
            db.execute("UPDATE execution_option_loss_outcomes SET outcome_hash='changed'")
        result = apply(engine, request(engine))
        assert result["status"] == "REJECTED"
        assert result["reason"] == "NATIVE_LOSS_OUTCOME_CHANGED"
        assert engine.journal.report(now=AFTER)["loss_control"]["locked"]


def test_reset_does_not_shortcut_first_loss_cooldown(tmp_path):
    policy = POLICY.model_copy(update={"max_consecutive_losses": 2})
    with owned(tmp_path, loss_control=policy) as (engine, venue, data):
        OptionsControl.enroll(engine, KEY, now=NOW)
        trade(engine, venue, data, "first", NOW)
        engine.refresh_loss_control(now=NOW)
        result = apply(engine, request(engine, NOW), NOW)
        assert result["reason"] == "NATIVE_LOSS_RESET_REQUIRES_LOCK"
        assert engine.journal.report(now=NOW)["loss_control"]["consecutive_losses"] == 1


def test_other_population_cannot_use_signed_reset(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with owned(first, loss_control=POLICY) as (engine, venue, data):
        lock(engine, venue, data)
        command = request(engine)
        with owned(second, loss_control=POLICY) as (other, other_venue, other_data):
            lock(other, other_venue, other_data)
            before = other.journal.path.read_bytes()
            with pytest.raises(ValueError, match="binding mismatch"):
                apply(other, command)
            assert other.journal.path.read_bytes() == before
            assert apply(engine, command)["status"] == "APPLIED"
            assert other.journal.report(now=AFTER)["loss_control"]["locked"]


def test_review_submit_inbox_and_observer_are_bound_to_stored_loss_state(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        lock(engine, venue, data)
        key = tmp_path / "operator.key"
        key.write_text(KEY.hex())
        key.chmod(0o600)
        for name in ("operator-inbox", "operator-receipts"):
            (tmp_path / name).mkdir(mode=0o700)
        before = engine.journal.path.read_bytes()
        observed = OptionObserver(
            engine.journal.path, engine.limits.population_id, clock=lambda: AFTER
        ).report()
        reviewed = review(engine.journal.path, engine.limits.population_id, key, now=AFTER)
        assert reviewed["evidence"]["loss_control"] == observed["loss_control"]
        assert observed["loss_control"]["locked"]
        artifact = tmp_path / "review.json"
        save(artifact, reviewed)
        queued = submit(
            engine.journal.path,
            artifact,
            key,
            "RESET_LOSS_LOCK",
            "reviewer",
            "Reviewed loss history",
            now=AFTER,
        )
        assert engine.journal.path.read_bytes() == before
        assert CommandInbox(engine, key).poll(now=AFTER) is None
        from pathlib import Path

        result = json.loads(Path(queued["receipt_file"]).read_text())["result"]
        assert result["status"] == "APPLIED"
        assert not engine.journal.report(now=AFTER)["loss_control"]["locked"]
