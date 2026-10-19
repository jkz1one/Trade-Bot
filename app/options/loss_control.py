"""Opt-in native PAPER loss cooldown and sticky lock, within the owning journal."""

import json
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, StrictBool

from app.execution.engine import ExecutionBlocked
from app.options.attribution import order_attribution
from app.options.engine import clock, fingerprint
from app.options.lifecycle import TERMINAL, NativeLossPolicy, OptionIntent, OptionObservation
from app.options.models import OptionRecord
from app.options.position_outcome import native_position_outcome


class FamilyLossState(OptionRecord):
    family: Literal["DEGEN", "SWING", "SCOPE"]
    consecutive_losses: int = Field(strict=True, ge=0)
    locked: StrictBool
    cooldown_until: datetime | None = None
    consumed_entries: int = Field(strict=True, ge=0, le=200)
    reasons: tuple[str, ...] = ()


class LossState(OptionRecord):
    consecutive_losses: int = Field(strict=True, ge=0)
    locked: StrictBool
    cooldown_until: datetime | None = None
    last_checked_at: datetime
    consumed_entries: int = Field(strict=True, ge=0, le=200)
    reasons: tuple[str, ...] = ()
    families: tuple[FamilyLossState, ...] = Field(
        default=(), max_length=3, exclude_if=lambda v: not v
    )


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
    if tuple(s.family for s in state.families) != tuple(p.family for p in policy.families):
        raise ValueError("Frozen family loss state mismatch")
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
    state = LossState(
        consecutive_losses=0,
        locked=False,
        last_checked_at=now,
        consumed_entries=0,
        families=tuple(
            FamilyLossState(family=p.family, consecutive_losses=0, locked=False, consumed_entries=0)
            for p in engine.policy.loss_control.families
        ),
    )
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
    old = LossState.model_validate({k: view[k] for k in LossState.model_fields if k in view})
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
        record = outcome_record(outcome, policy)
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
    family_states = {s.family: s for s in old.families}
    family_rules = {p.family: p for p in policy.families}
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
        family = record.get("entry_lineage", {}).get("family")
        if family in family_states:
            state = family_states[family]
            rule = family_rules[family]
            changes = {"consumed_entries": state.consumed_entries + 1}
            if record["outcome"] == "LOSS":
                losses = state.consecutive_losses + 1
                deadline = now + timedelta(seconds=rule.cooldown_seconds)
                changes.update(
                    consecutive_losses=losses,
                    locked=state.locked or losses >= rule.max_consecutive_losses,
                    cooldown_until=max(state.cooldown_until, deadline)
                    if state.cooldown_until
                    else deadline,
                )
            elif not state.locked:
                changes["consecutive_losses"] = 0
            family_states[family] = state.model_copy(update=changes)
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
        families=tuple(
            s.model_copy(update={"reasons": family_reasons(s, now)}) for s in family_states.values()
        ),
    )
    if state != old:
        db.execute(
            "UPDATE execution_option_loss_control SET state_json=? WHERE id=1",
            (state.model_dump_json(),),
        )
        engine.journal.event(db, now, "NATIVE_LOSS_CONTROL_REVIEWED", state.model_dump(mode="json"))
    return stored_state(db)


def family_reasons(state, now):
    reasons = []
    if state.locked:
        reasons.append("NATIVE_FAMILY_LOCKED:" + state.family)
    if state.cooldown_until and now < clock(state.cooldown_until):
        reasons.append("NATIVE_FAMILY_COOLDOWN:" + state.family)
    return tuple(reasons)


def guard_entry(
    engine, db, proposal, now, *, exclude=None, source_key=None, quote=None, lineage=None
):
    if proposal.action != "OPEN_LONG" or engine.policy.loss_control is None:
        return
    state = refresh(engine, db, now, exclude=exclude)
    if state["reasons"]:
        raise ExecutionBlocked(";".join(state["reasons"]))
    if engine.policy.loss_control.families:
        from app.options.entry_lineage import selected_lineage

        lineage = lineage or (
            selected_lineage(db, source_key, quote.instrument) if source_key and quote else None
        )
        if lineage is None:
            raise ExecutionBlocked("NATIVE_FAMILY_LINEAGE_REQUIRED")
        family = next((s for s in state["families"] if s["family"] == lineage.family), None)
        if family and family["reasons"]:
            raise ExecutionBlocked(";".join(family["reasons"]))


def model_family_reasons(engine, db, source_key, state):
    """Do not pay for entry advice when no stored candidate has an unpaused family.

    A mixed packet can still yield a paused choice; preparation independently rejects
    it and its charge remains in the common ledger. No packet or model result is edited.
    """
    if not engine.policy.loss_control.families:
        return []
    from app.options.observer import _json
    from app.options.selection import SwingCandidate, parse_candidate

    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_opportunities'"
    ).fetchone():
        return ["NATIVE_FAMILY_MODEL_CANDIDATES_REQUIRED"]
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (source_key,)
    ).fetchone()
    try:
        candidates = _json(row[0])["candidates"] if row else []
        if (
            not isinstance(candidates, list)
            or not 1 <= len(candidates) <= 100
            or any(not isinstance(c, dict) for c in candidates)
        ):
            return ["NATIVE_FAMILY_MODEL_CANDIDATES_REQUIRED"]
        families = {
            "SWING" if isinstance(parse_candidate(c), SwingCandidate) else "DEGEN"
            for c in candidates
        }
    except (ValueError, TypeError, KeyError):
        return ["NATIVE_FAMILY_MODEL_CANDIDATES_REQUIRED"]
    paused = {s["family"] for s in state["families"] if s["reasons"]}
    return ["NATIVE_FAMILY_MODEL_ENTRY_PAUSED"] if families <= paused else []


def reset_reviewed(engine, db, command, now):
    """Called only inside the authenticated operator's fenced transaction."""
    engine._control(db)
    if engine.journal.revision(db) != command.expected_revision:
        raise ExecutionBlocked("OPTION_REVIEW_REVISION_CHANGED")
    if engine.policy.loss_control is None:
        raise ExecutionBlocked("NATIVE_LOSS_NOT_ENROLLED")
    previous = stored_state(db)
    target = command.loss_family
    selected = (
        previous
        if target is None
        else next((s for s in previous.get("families", ()) if s["family"] == target), None)
        if previous
        else None
    )
    if selected is None or not selected["locked"]:
        raise ExecutionBlocked("NATIVE_LOSS_RESET_REQUIRES_LOCK")
    account = engine._account(db, now)
    if (
        account.entry_blockers
        or account.working_orders
        or account.position is not None
        or not account.complete
        or account.unsupported_exposure
        or account.daily_loss_available <= 0
        or account.total_loss_available <= 0
        or not account.budgets_known
        or db.execute("SELECT 1 FROM execution_model_calls WHERE cost IS NULL LIMIT 1").fetchone()
        or not timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=engine.limits.account_max_age_seconds)
    ):
        raise ExecutionBlocked("OPTION_RECOVERY_EVIDENCE_REQUIRED")
    current = refresh(engine, db, now)
    if current["consumed_entries"] != previous["consumed_entries"]:
        raise ExecutionBlocked("NATIVE_LOSS_NEW_OUTCOME_REQUIRES_REVIEW")
    if target is None:
        selected = current
        expected = {"NATIVE_LOSS_LOCKED"}
    else:
        if set(current["reasons"]) - {"NATIVE_LOSS_LOCKED", "NATIVE_LOSS_COOLDOWN"}:
            raise ExecutionBlocked(";".join(current["reasons"]))
        selected = next(s for s in current["families"] if s["family"] == target)
        expected = {"NATIVE_FAMILY_LOCKED:" + target}
    if set(selected["reasons"]) != expected:
        raise ExecutionBlocked(";".join(selected["reasons"]) or "NATIVE_LOSS_RESET_REQUIRES_LOCK")
    if selected["cooldown_until"] is None or now < clock(
        datetime.fromisoformat(selected["cooldown_until"])
    ):
        raise ExecutionBlocked("NATIVE_LOSS_COOLDOWN")
    state = LossState.model_validate(
        {k: current[k] for k in LossState.model_fields if k in current}
    )
    cleared = {"locked": False, "consecutive_losses": 0, "reasons": ()}
    state = (
        state.model_copy(update=cleared)
        if target is None
        else state.model_copy(
            update={
                "families": tuple(
                    s.model_copy(update=cleared) if s.family == target else s
                    for s in state.families
                )
            }
        )
    )
    db.execute(
        "UPDATE execution_option_loss_control SET state_json=? WHERE id=1",
        (state.model_dump_json(),),
    )
    engine.journal.event(
        db,
        now,
        "NATIVE_LOSS_REVIEWED_RESET",
        {
            **({"loss_family": target} if target is not None else {}),
            "command_id": command.command_id,
            "actor": command.actor,
            "reason": command.reason,
            "expected_revision": command.expected_revision,
            "population_id": engine.limits.population_id,
            **(
                {"session_date": now.astimezone(ZoneInfo("America/New_York")).date().isoformat()}
                if target == "SCOPE"
                else {}
            ),
            "prior_state": current,
            "state": state.model_dump(mode="json"),
        },
    )


def outcome_record(outcome, policy):
    """Canonical economic record shared by owned consumption and read-only export."""
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
    if policy.families:
        from app.options.lifecycle import EntryLineage

        if "entry_lineage" not in outcome:
            raise ExecutionBlocked("NATIVE_FAMILY_LINEAGE_REQUIRED")
        record["entry_lineage"] = EntryLineage.model_validate(outcome["entry_lineage"]).model_dump(
            mode="json"
        )
    return record
