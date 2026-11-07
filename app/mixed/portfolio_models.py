"""Portfolio-bound model budgets and original receipts; model output grants no authority."""

from decimal import Decimal
from zoneinfo import ZoneInfo

from app.execution import economics
from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.portfolio_accounting import candidate_blockers, remaining_budget
from app.mixed.portfolio_execution import selection_account
from app.mixed.portfolio_protection import entry_guard
from app.mixed.portfolio_store import history
from app.options.engine import exact


def candidate_account(engine, db, underlying, now, *, exclude=None):
    from app.mixed.governor import _account
    from app.mixed.portfolio_execution import fresh

    c, snap = fresh(engine, db, engine.portfolio_policy, now)
    h = history(engine, db, engine.portfolio_policy, now, exclude=exclude)
    projection = reconstruct(h)
    account = _account(h, projection, True, bool(c["halted"]))
    budget = remaining_budget(h, projection, underlying)
    return account.model_copy(
        update={
            "daily_loss_available": budget,
            "total_loss_available": budget,
            "entry_blockers": candidate_blockers(h, projection, underlying, ""),
            "captured_at": snap.captured_at,
            "snapshot_id": snap.snapshot_id,
        }
    )


@exact
def admit_attempt(engine, db, source_key, input_hash, now, position_request):
    if position_request is not None:
        from app.mixed.portfolio_management import current, validate_admission

        validate_admission(engine, db, source_key, position_request, input_hash, now)
        account = current(engine, db, position_request.packet.play_id, now)[3]
    else:
        from app.mixed.entry import validate_admission

        validate_admission(engine, db, source_key, input_hash, now)
        entry_guard(engine, db, engine.portfolio_policy, now)
        account = selection_account(engine, db, now)
    h = history(engine, db, engine.portfolio_policy, now)
    projection = reconstruct(h)
    budget = (
        min(
            projection.daily_loss_available or Decimal(0),
            projection.total_loss_available or Decimal(0),
        )
        if position_request is not None
        else remaining_budget(h, projection, "")
    )
    policy = engine.policy.cost_policy
    summary = economics.summary(db, now)
    day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    window = engine.calendar.current_window(now)
    from datetime import timedelta

    if (
        account.entry_halted
        or account.entry_blockers
        or not account.budgets_known
        or window is None
        or (
            position_request is None
            and now >= window.closes_at - timedelta(minutes=engine.policy.entry_cutoff_minutes)
        )
        or policy.max_call_cost > budget
        or Decimal(summary["known_cost"]) + policy.max_call_cost > policy.total_budget
        or Decimal(summary["daily_cost"].get(day, "0")) + policy.max_call_cost > policy.daily_budget
    ):
        raise ExecutionBlocked("PORTFOLIO_MODEL_ADMISSION_BLOCKED")
    if (
        db.execute(
            "SELECT 1 FROM execution_model_calls WHERE source_key=?", (source_key,)
        ).fetchone()
        or db.execute(
            "SELECT 1 FROM execution_portfolio_decisions WHERE source_key=?", (source_key,)
        ).fetchone()
    ):
        raise ExecutionBlocked("OPTION_MODEL_SOURCE_ALREADY_ATTEMPTED")
    db.execute(
        "INSERT INTO execution_model_calls VALUES(?,?,?,NULL,NULL,NULL,NULL)",
        (source_key, input_hash, now.isoformat()),
    )
    engine.journal.event(
        db,
        now,
        "OPTION_MODEL_ATTEMPT_ADMITTED",
        {"source_key": source_key, "input_hash": input_hash},
    )
