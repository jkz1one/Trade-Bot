"""Opt-in native PAPER loss cooldown and sticky lock, within the owning journal."""

import json
from datetime import datetime, timedelta

from pydantic import Field, StrictBool

from app.execution.engine import ExecutionBlocked
from app.options.attribution import order_attribution
from app.options.engine import clock, fingerprint
from app.options.lifecycle import TERMINAL, NativeLossPolicy, OptionIntent, OptionObservation
from app.options.models import OptionRecord
from app.options.position_outcome import native_position_outcome


class LossState(OptionRecord):
    consecutive_losses: int = Field(strict=True, ge=0)
    locked: StrictBool
    cooldown_until: datetime | None = None
    last_checked_at: datetime
    consumed_entries: int = Field(strict=True, ge=0, le=200)
    reasons: tuple[str, ...] = ()


def stored_state(db):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_loss_control'"
    ).fetchone():
        return None
    row = db.execute("SELECT * FROM execution_option_loss_control WHERE id=1").fetchone()
    if row is None:
        raise ValueError("Native loss enrollment is incomplete")
    policy = NativeLossPolicy.model_validate_json(row["policy_json"])
    state = LossState.model_validate_json(row["state_json"])
    return {
        "policy": policy.model_dump(mode="json"),
        **state.model_dump(mode="json"),
        "execution_authority": False,
        "live_enabled": False,
    }


def enroll(engine, db, now, *, create):
    policy = engine.policy.loss_control.model_dump_json()
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_loss_control'"
    ).fetchone()
    if not create:
        if not exists:
            raise ExecutionBlocked("NATIVE_LOSS_ENROLLMENT_MISSING")
        row = db.execute(
            "SELECT policy_json FROM execution_option_loss_control WHERE id=1"
        ).fetchone()
        if row is None or row[0] != policy:
            raise ExecutionBlocked("FROZEN_NATIVE_LOSS_POLICY_MISMATCH")
        stored_state(db)
        return
    if exists or db.execute("SELECT 1 FROM execution_orders LIMIT 1").fetchone():
        raise ExecutionBlocked("NATIVE_LOSS_REQUIRES_NEW_COHORT")
    db.execute(
        "CREATE TABLE execution_option_loss_control(id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL,state_json TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE execution_option_loss_outcomes(entry_client_id TEXT PRIMARY KEY,outcome_hash TEXT NOT NULL,record_json TEXT NOT NULL)"
    )
    state = LossState(consecutive_losses=0, locked=False, last_checked_at=now, consumed_entries=0)
    db.execute(
        "INSERT INTO execution_option_loss_control VALUES(1,?,?)", (policy, state.model_dump_json())
    )
    engine.journal.event(db, now, "NATIVE_LOSS_CONTROL_ENROLLED", json.loads(policy))


def refresh(engine, db, now, *, exclude=None):
    engine._control(db)
    policy = engine.policy.loss_control
    if policy is None:
        raise ExecutionBlocked("NATIVE_LOSS_NOT_ENROLLED")
    view = stored_state(db)
    if view is None or view["policy"] != policy.model_dump(mode="json"):
        raise ExecutionBlocked("FROZEN_NATIVE_LOSS_POLICY_MISMATCH")
    old = LossState.model_validate({k: view[k] for k in LossState.model_fields})
    if now < clock(old.last_checked_at):
        raise ExecutionBlocked("NATIVE_LOSS_CLOCK_REWOUND")
    rows = db.execute("SELECT * FROM execution_orders ORDER BY rowid LIMIT 2001").fetchall()
    if len(rows) > 2000:
        raise ExecutionBlocked("NATIVE_LOSS_CAPACITY_EXCEEDED")
    buys = [(r, OptionIntent.model_validate_json(r["intent_json"])) for r in rows]
    buys = [(r, i) for r, i in buys if i.side == "BUY"]
    if len(buys) > 200:
        raise ExecutionBlocked("NATIVE_LOSS_CAPACITY_EXCEEDED")
    saved = {
        r["entry_client_id"]: r
        for r in db.execute("SELECT * FROM execution_option_loss_outcomes LIMIT 201")
    }
    if len(saved) != old.consumed_entries or set(saved) - {i.client_id for _, i in buys}:
        raise ExecutionBlocked("NATIVE_LOSS_HISTORY_CHANGED")
    complete, reasons = [], []
    for row, intent in buys:
        if intent.client_id == exclude:
            if row["status"] != "PREPARED" or row["attempted_at"] is not None:
                raise ExecutionBlocked("NATIVE_LOSS_EXCLUSION_INVALID")
            continue
        order_attribution(db, row)
        observation = (
            OptionObservation.model_validate_json(row["observation_json"])
            if row["observation_json"]
            else None
        )
        quantity = observation.filled_quantity if observation else 0
        if not quantity and row["status"] in TERMINAL - {"FILLED"}:
            if intent.client_id in saved:
                raise ExecutionBlocked("NATIVE_LOSS_HISTORY_CHANGED")
            continue
        outcome = native_position_outcome(db, intent.client_id, engine.limits.population_id)
        if outcome["status"] != "COMPLETE":
            reasons.append("NATIVE_LOSS_OUTCOME_PENDING")
            continue
        closed_at = clock(datetime.fromisoformat(outcome["closed_at"]))
        if closed_at > now:
            raise ExecutionBlocked("NATIVE_LOSS_FUTURE_OUTCOME")
        # A later attempt or unrelated cost may add diagnostic context; bind the
        # economic outcome and its exact attributed calls/fills/settlements only.
        record = {
            key: outcome[key]
            for key in (
                "entry_client_id",
                "population_id",
                "closed_at",
                "outcome",
                "entry_quantity",
                "exit_quantity",
                "settlement_quantity",
                "entry_premium",
                "exit_premium",
                "settlement_cash",
                "execution_fees",
                "known_model_cost",
                "net_after_known_execution_and_model_costs",
                "model_calls",
                "fill_ids",
                "settlements",
            )
        }
        digest = fingerprint(record)
        prior = saved.get(intent.client_id)
        if prior and (
            prior["outcome_hash"] != digest
            or fingerprint(json.loads(prior["record_json"])) != digest
        ):
            raise ExecutionBlocked("NATIVE_LOSS_OUTCOME_CHANGED")
        if prior is None:
            complete.append((closed_at, intent.client_id, digest, record))
    if complete and saved:
        latest = max(
            clock(datetime.fromisoformat(json.loads(r["record_json"])["closed_at"]))
            for r in saved.values()
        )
        if min(row[0] for row in complete) < latest:
            raise ExecutionBlocked("NATIVE_LOSS_HISTORY_ORDER_CHANGED")
    count, locked, until = old.consecutive_losses, old.locked, old.cooldown_until
    # No partial consumption across an unresolved earlier outcome.
    if reasons:
        complete = []
    for _, entry_id, digest, record in sorted(complete, key=lambda item: item[0]):
        if record["outcome"] == "LOSS":
            count += 1
            locked = locked or count >= policy.max_consecutive_losses
            deadline = now + timedelta(seconds=policy.cooldown_seconds)
            until = max(until, deadline) if until else deadline
        elif not locked:
            count = 0
        db.execute(
            "INSERT INTO execution_option_loss_outcomes VALUES(?,?,?)",
            (entry_id, digest, json.dumps(record, sort_keys=True)),
        )
        engine.journal.event(
            db,
            now,
            "NATIVE_LOSS_OUTCOME_CONSUMED",
            {"entry_client_id": entry_id, "outcome_hash": digest, "outcome": record["outcome"]},
        )
    if locked:
        reasons.append("NATIVE_LOSS_LOCKED")
    if until and now < clock(until):
        reasons.append("NATIVE_LOSS_COOLDOWN")
    state = LossState(
        consecutive_losses=count,
        locked=locked,
        cooldown_until=until,
        last_checked_at=now,
        consumed_entries=len(saved) + len(complete),
        reasons=tuple(sorted(set(reasons))),
    )
    if state != old:
        db.execute(
            "UPDATE execution_option_loss_control SET state_json=? WHERE id=1",
            (state.model_dump_json(),),
        )
        engine.journal.event(db, now, "NATIVE_LOSS_CONTROL_REVIEWED", state.model_dump(mode="json"))
    return stored_state(db)


def guard_entry(engine, db, proposal, now, *, exclude=None):
    if proposal.action != "OPEN_LONG" or engine.policy.loss_control is None:
        return
    state = refresh(engine, db, now, exclude=exclude)
    if state["reasons"]:
        raise ExecutionBlocked(";".join(state["reasons"]))
