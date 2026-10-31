"""Frozen target orchestration through the native governor; fills alone retire size."""

import json

from app.execution.engine import ExecutionBlocked
from app.options.lifecycle import OptionIntent, OptionLedger, TargetExitSchedule
from app.options.models import OptionProposal


def verify_binding(intent, approval):
    raw = approval.get("target_exit_schedule")
    schedule = TargetExitSchedule.model_validate(raw) if raw is not None else None
    if intent.target_exit_schedule != schedule or intent.target_exit_stage != approval.get(
        "target_exit_stage"
    ):
        raise ValueError("OPTION_TARGET_TERMS_CHANGED")
    if (schedule is not None or intent.target_exit_stage is not None) and approval.get(
        "origin"
    ) != "DETERMINISTIC":
        raise ValueError("OPTION_TARGET_DETERMINISTIC_ONLY")


def remaining(db, position, stage):
    """Return cumulative due minus verified sales of this entry, never order quantities."""
    schedule = position.target_exit_schedule
    if schedule is None or not 1 <= stage <= position.target_exit_stage <= len(schedule.steps):
        raise ExecutionBlocked("OPTION_TARGET_NOT_REACHED")
    if schedule.needs_entry_reference:
        from app.options.entry_reference import review_reference

        if review_reference(position)["status"] != "READY":
            raise ExecutionBlocked("OPTION_TARGET_ENTRY_REFERENCE_REQUIRED")
    row = db.execute(
        "SELECT * FROM execution_orders WHERE client_id=?", (position.entry_client_id,)
    ).fetchone()
    entry = OptionIntent.model_validate_json(row["intent_json"])
    verify_binding(entry, json.loads(row["approval_json"]))
    if entry.target_exit_schedule != schedule or row["status"] != "FILLED":
        raise ExecutionBlocked("OPTION_TARGET_COMPLETE_ENTRY_REQUIRED")
    # Reconciliation has already verified complete ownership and all fill histories.
    sold = sum(
        json.loads(r[0])["quantity"]
        for r in db.execute(
            "SELECT f.payload FROM execution_fills f JOIN execution_orders o USING(client_id) WHERE json_extract(o.intent_json,'$.closing_entry_client_id')=?",
            (position.entry_client_id,),
        )
    )
    return min(
        position.quantity, max(0, sum(s.quantity for s in schedule.steps[:stage]) - sold)
    ), sold


def review_close(engine, db, proposal, stage, origin):
    if engine.policy.target_exits is None or origin != "DETERMINISTIC":
        raise ExecutionBlocked("OPTION_TARGET_NOT_ENROLLED")
    if type(stage) is not int or not 1 <= stage <= 3 or proposal.action != "CLOSE":
        raise ExecutionBlocked("OPTION_TARGET_STAGE_INVALID")
    position = OptionLedger.model_validate_json(engine._control(db)["ledger_json"]).position
    if position is None:
        raise ExecutionBlocked("OPTION_TARGET_POSITION_REQUIRED")
    quantity, _ = remaining(db, position, stage)
    if quantity == 0 or proposal.close_quantity != quantity:
        raise ExecutionBlocked("OPTION_TARGET_QUANTITY_CHANGED")


async def tick(engine, quote, underlying, *, now, assessed):
    """Called only after independent reconciliation/protection, never by observer reads."""
    from app.options.engine import fingerprint

    with engine.journal.read() as db:
        position = OptionLedger.model_validate_json(engine._control(db)["ledger_json"]).position
        if (
            position is None
            or position.target_exit_schedule is None
            or not position.target_exit_stage
        ):
            return assessed
        if engine.policy.target_exits is None:
            raise ExecutionBlocked("OPTION_TARGET_NOT_ENROLLED")
        active = db.execute("SELECT * FROM execution_orders WHERE active_lock=1").fetchone()
        if active:
            intent = OptionIntent.model_validate_json(active["intent_json"])
            if (
                active["status"] != "PREPARED"
                or intent.target_exit_stage is None
                or intent.closing_entry_client_id != position.entry_client_id
            ):
                return {"status": "TARGET_EXIT_BLOCKED", "reason": "OPTION_ORDER_ALREADY_IN_FLIGHT"}
            client_id = intent.client_id
        else:
            client_id = None
        if db.execute(
            "SELECT 1 FROM execution_orders WHERE json_extract(intent_json,'$.closing_entry_client_id')=? AND attempted_at IS NOT NULL AND status IN ('REJECTED','CANCELED','EXPIRED') LIMIT 1",
            (position.entry_client_id,),
        ).fetchone():
            return {
                "status": "TARGET_EXIT_REVIEW_REQUIRED",
                "reason": "OPTION_EXIT_REVIEW_REQUIRED",
            }
        try:
            quantity, sold = remaining(db, position, position.target_exit_stage)
        except ExecutionBlocked as exc:
            return {"status": "TARGET_EXIT_BLOCKED", "reason": str(exc)}
    if not quantity:
        return assessed
    if client_id is None:
        proposal = OptionProposal(
            action="CLOSE",
            contract=position.contract,
            close_quantity=quantity,
            thesis="Frozen target schedule: stage " + str(position.target_exit_stage),
        )
        key = "target:" + fingerprint(
            {
                "entry": position.entry_client_id,
                "stage": position.target_exit_stage,
                "sold": sold,
                "quote": quote,
                "underlying": underlying,
                "now": now,
            }
        )
        prepared = engine.prepare(
            key, proposal, quote, underlying, now=now, target_exit_stage=position.target_exit_stage
        )
        if prepared["status"] != "PREPARED":
            return prepared
        client_id = prepared["client_id"]
    status = await engine.dispatch(client_id, quote, underlying, now=now)
    return {
        "status": status,
        "client_id": client_id,
        "target_exit_stage": position.target_exit_stage,
    }
