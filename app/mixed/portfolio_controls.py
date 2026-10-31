"""Signed, revision-bound portfolio settings and reviewed recovery on one owner."""

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.portfolio_execution import fresh, policy
from app.mixed.portfolio_protection import entry_guard
from app.mixed.portfolio_store import control, history
from app.options.loss_control import stored_state


def revision(engine, db, expected):
    engine._control(db)
    if type(expected) is not int or engine.journal.revision(db) != expected:
        raise ExecutionBlocked("OPTION_REVIEW_REVISION_CHANGED")


def set_limit(engine, db, command, now):
    if engine.portfolio_policy is None:
        raise ExecutionBlocked("PORTFOLIO_NOT_ENROLLED")
    revision(engine, db, command.expected_revision)
    if type(command.max_plays) is not int or command.max_plays not in (0, 1, 2):
        raise ExecutionBlocked("PORTFOLIO_LIMIT_INVALID")
    previous = control(engine, db, policy(engine))["limit_value"]
    db.execute(
        "UPDATE execution_portfolio_control SET limit_value=? WHERE id=1", (command.max_plays,)
    )
    engine.journal.event(
        db,
        now,
        "PORTFOLIO_LIMIT_CHANGED",
        {
            "from": previous,
            "to": command.max_plays,
            "command_id": command.command_id,
            "actor": command.actor,
            "reason": command.reason,
            "expected_revision": command.expected_revision,
        },
    )


def recoverable(engine, db, now, *, flat=False):
    p = policy(engine)
    fresh(engine, db, p, now)
    result = reconstruct(history(engine, db, p, now))
    if (
        db.execute(
            "SELECT 1 FROM execution_portfolio_orders WHERE active_play IS NOT NULL"
        ).fetchone()
        or result.unknown_cost_ids
        or db.execute("SELECT 1 FROM execution_model_calls WHERE cost IS NULL").fetchone()
        or (flat and result.ledger.positions)
    ):
        raise ExecutionBlocked("OPTION_RECOVERY_EVIDENCE_REQUIRED")
    if not flat:
        entry_guard(engine, db, p, now)
    return result


def resume(engine, db, reason, *, expected_revision, now):
    revision(engine, db, expected_revision)
    recoverable(engine, db, now)
    db.execute("UPDATE execution_control SET halted=0,halt_reason=NULL WHERE id=1")
    engine.journal.event(
        db,
        now,
        "OPTION_REVIEWED_RESUME",
        {"reason": reason, "expected_revision": expected_revision},
    )


def reset_reviewed(engine, db, command, now):
    from app.mixed.portfolio_loss import refresh

    revision(engine, db, command.expected_revision)
    previous = stored_state(db)
    if previous is None:
        raise ExecutionBlocked("NATIVE_LOSS_NOT_ENROLLED")
    result = recoverable(engine, db, now, flat=True)
    if not result.daily_loss_available or not result.total_loss_available:
        raise ExecutionBlocked("OPTION_RECOVERY_EVIDENCE_REQUIRED")
    current = refresh(engine, db, policy(engine), now)
    if current.consumed_entries != previous["consumed_entries"]:
        raise ExecutionBlocked("NATIVE_LOSS_NEW_OUTCOME_REQUIRES_REVIEW")
    target = command.loss_family
    selected = (
        current
        if target is None
        else next((f for f in current.families if f.family == target), None)
    )
    if selected is None or not selected.locked:
        raise ExecutionBlocked("NATIVE_LOSS_RESET_REQUIRES_LOCK")
    expected = {"NATIVE_LOSS_LOCKED"} if target is None else {"NATIVE_FAMILY_LOCKED:" + target}
    if (
        set(selected.reasons) != expected
        or selected.cooldown_until is None
        or now < selected.cooldown_until
    ):
        raise ExecutionBlocked("NATIVE_LOSS_RESET_EVIDENCE_REQUIRED")
    cleared = {"locked": False, "consecutive_losses": 0, "reasons": ()}
    updated = current.model_copy(
        update=cleared
        if target is None
        else {
            "families": tuple(
                f.model_copy(update=cleared) if f.family == target else f for f in current.families
            )
        }
    )
    db.execute(
        "UPDATE execution_option_loss_control SET state_json=? WHERE id=1",
        (updated.model_dump_json(),),
    )
    engine.journal.event(
        db,
        now,
        "NATIVE_LOSS_REVIEWED_RESET",
        {
            "command_id": command.command_id,
            "actor": command.actor,
            "reason": command.reason,
            "loss_family": target,
            "prior_state": current.model_dump(mode="json"),
            "state": updated.model_dump(mode="json"),
        },
    )
