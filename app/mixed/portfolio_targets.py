"""Original target schedules and trade floors bound to exact portfolio receipts."""

import json
from decimal import ROUND_CEILING, Decimal

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.portfolio_accounting import play_id
from app.mixed.portfolio_store import control, history, intent
from app.options.engine import exact, fingerprint
from app.options.governor import _tick_price
from app.options.lifecycle import OptionPosition


def protected_position(engine, db, identity, now):
    p = reconstruct(history(engine, db, engine.portfolio_policy, now)).ledger.positions.get(
        identity
    )
    saved = json.loads(control(engine, db, engine.portfolio_policy)["protection_json"]).get(
        identity
    )
    if not isinstance(p, OptionPosition) or saved is None:
        raise ExecutionBlocked("EXACT_SUPERVISED_OPTION_PLAY_REQUIRED")
    managed = OptionPosition.model_validate(saved["position"])
    if (
        managed.entry_client_id != identity
        or managed.quantity != p.quantity
        or managed.basis != p.basis
    ):
        raise ExecutionBlocked("PORTFOLIO_PROTECTION_REASSESSMENT_REQUIRED")
    return managed


@exact
def remaining(db, position, stage):
    schedule = position.target_exit_schedule
    if (
        schedule is None
        or type(stage) is not int
        or not 1 <= stage <= position.target_exit_stage <= len(schedule.steps)
    ):
        raise ExecutionBlocked("OPTION_TARGET_NOT_REACHED")
    if schedule.needs_entry_reference:
        from app.options.entry_reference import review_reference

        if review_reference(position)["status"] != "READY":
            raise ExecutionBlocked("OPTION_TARGET_ENTRY_REFERENCE_REQUIRED")
    row = db.execute(
        "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (position.entry_client_id,)
    ).fetchone()
    entry = intent(row)
    if row["status"] != "FILLED" or entry.target_exit_schedule != schedule:
        raise ExecutionBlocked("OPTION_TARGET_COMPLETE_ENTRY_REQUIRED")
    sold = sum(
        json.loads(r[0])["filled_quantity"]
        for r in db.execute(
            "SELECT observation_json FROM execution_portfolio_orders WHERE play_id=? AND json_extract(intent_json,'$.side')='SELL' AND observation_json IS NOT NULL",
            (position.entry_client_id,),
        )
    )
    return min(
        position.quantity, max(0, sum(s.quantity for s in schedule.steps[:stage]) - sold)
    ), sold


def review_close(engine, db, identity, proposal, stage, origin, now):
    if engine.policy.target_exits is None or origin != "DETERMINISTIC":
        raise ExecutionBlocked("OPTION_TARGET_NOT_ENROLLED")
    p = protected_position(engine, db, identity, now)
    quantity, _ = remaining(db, p, stage)
    if (
        proposal.action != "CLOSE"
        or proposal.contract != p.contract
        or not quantity
        or proposal.close_quantity != quantity
    ):
        raise ExecutionBlocked("OPTION_TARGET_QUANTITY_CHANGED")


async def tick(engine, identity, quote, underlying, now, assessed):
    from app.options.models import OptionProposal

    with engine.journal.read() as db:
        p = protected_position(engine, db, identity, now)
        if not p.target_exit_schedule or not p.target_exit_stage:
            return assessed
        if db.execute(
            "SELECT 1 FROM execution_portfolio_orders WHERE active_play=?", (identity,)
        ).fetchone():
            return {"status": "TARGET_EXIT_BLOCKED", "reason": "PLAY_ORDER_UNRESOLVED"}
        if db.execute(
            "SELECT 1 FROM execution_portfolio_orders WHERE play_id=? AND json_extract(intent_json,'$.side')='SELL' AND attempted_at IS NOT NULL AND status IN ('REJECTED','CANCELED','EXPIRED')",
            (identity,),
        ).fetchone():
            return {"status": "TARGET_EXIT_REVIEW_REQUIRED", "reason": "PLAY_EXIT_REVIEW_REQUIRED"}
        quantity, sold = remaining(db, p, p.target_exit_stage)
    if not quantity:
        return assessed
    key = "target:" + fingerprint(
        {
            "play_id": identity,
            "stage": p.target_exit_stage,
            "sold": sold,
            "quote": quote,
            "now": now,
        }
    )
    prepared = engine.prepare(
        key,
        OptionProposal(
            action="CLOSE",
            contract=p.contract,
            close_quantity=quantity,
            thesis="Frozen target schedule: stage " + str(p.target_exit_stage),
        ),
        quote,
        underlying,
        now=now,
        play_id=identity,
        target_exit_stage=p.target_exit_stage,
    )
    if prepared["status"] != "PREPARED":
        return prepared
    return {
        **assessed,
        "status": await engine.dispatch(prepared["client_id"], quote, underlying, now=now),
        "client_id": prepared["client_id"],
    }


@exact
def refresh_floor(engine, db, p, now):
    """Same native floor semantics: execution/model costs, explicit data/host exclusion."""
    state = p.trade_floor
    if state is None:
        return p
    h = history(engine, db, engine.portfolio_policy, now)
    entry = db.execute(
        "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (p.entry_client_id,)
    ).fetchone()
    reasons = []
    if entry["status"] != "FILLED":
        reasons.append("COMPLETE_ORIGINAL_ENTRY_REQUIRED")
    if db.execute(
        "SELECT 1 FROM execution_portfolio_orders WHERE play_id=? AND active_play IS NOT NULL",
        (p.entry_client_id,),
    ).fetchone():
        reasons.append("UNRESOLVED_POSITION_ORDER")
    events = [
        e for e in h.events if hasattr(e, "intent") and play_id(e.intent) == p.entry_client_id
    ]
    costs = [
        c
        for c in h.costs
        if c.entry_client_id == p.entry_client_id and c.kind not in {"DATA", "HOST", "OPERATING"}
    ]
    if any(c.amount is None for c in costs):
        reasons.append("MODEL_COST_UNKNOWN")
    changes = {"reasons": tuple(reasons)}
    if not reasons and p.target_exit_stage:
        original = sum(
            e.fill.quantity * e.fill.price * p.contract.multiplier
            for e in events
            if e.intent.side == "BUY"
        )
        sales = sum(
            e.fill.quantity * e.fill.price * p.contract.multiplier
            for e in events
            if e.intent.side == "SELL"
        )
        charged = sum(e.fill.fee for e in events) + sum(c.amount for c in costs)
        reserve = p.quantity * (
            engine.limits.exit_fee_per_contract + engine.limits.exit_fee_per_order
        )
        fraction = (Decimal(0), Decimal(".10"), Decimal(".25"))[p.target_exit_stage - 1]
        required = max(Decimal(0), original * (1 + fraction) + charged + reserve - sales)
        price = _tick_price(
            required / (p.quantity * p.contract.multiplier), p.contract, ROUND_CEILING
        )
        changes.update(
            minimum_exit_fill_price=max(state.minimum_exit_fill_price or Decimal(0), price),
            reference_stage=max(state.reference_stage, p.target_exit_stage),
            evidence_hash=fingerprint({"events": events, "costs": costs}),
        )
    return p.model_copy(update={"trade_floor": state.model_copy(update=changes)})
