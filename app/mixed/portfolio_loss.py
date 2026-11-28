"""Full-cost completed-play outcomes and the existing account/family loss controls."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.portfolio_accounting import intent_identity, play_id
from app.mixed.portfolio_store import history
from app.options.engine import exact, fingerprint
from app.options.loss_control import LossState, family_reasons, stored_state

ZERO = Decimal(0)


@exact
def outcomes(h):
    projection = reconstruct(h)
    occupied = {c.play_id for c in projection.commitments}
    values = {}
    for event in sorted(
        h.events, key=lambda e: e.fill.sequence if hasattr(e, "fill") else e.receipt.sequence
    ):
        if hasattr(event, "intent"):
            i = event.intent
            f = event.fill
            identity = play_id(i)
            if i.side == "BUY" and identity not in values:
                values[identity] = {
                    "entry": i,
                    "opened_at": f.occurred_at,
                    "entry_sequence": f.sequence,
                    "closed_at": None,
                    "cash": ZERO,
                    "fees": ZERO,
                    "fill_ids": [],
                    "receipts": [],
                    "model_cost": ZERO,
                    "operating_cost": ZERO,
                    "cost_ids": [],
                    "unknown": False,
                }
            if identity not in values:
                raise ValueError("Portfolio outcome missing original entry")
            value = values[identity]
            multiplier = (
                i.instrument.contract.multiplier if hasattr(i.instrument, "contract") else 1
            )
            value["cash"] += (
                1 if i.side == "SELL" else -1
            ) * f.quantity * f.price * multiplier - f.fee
            value["fees"] += f.fee
            value["fill_ids"].append(f.fill_id)
            if i.side == "SELL":
                value["closed_at"] = f.occurred_at
        elif event.receipt.kind != "FUNDS_SETTLED":
            value = values[event.play_id]
            value["cash"] += event.receipt.cash_change
            value["closed_at"] = event.receipt.occurred_at
            value["receipts"].append(event.receipt.receipt_id)
    ordered = sorted(
        values.items(), key=lambda item: (item[1]["opened_at"], item[1]["entry_sequence"])
    )
    resolutions = {c.cost_id: c.amount for c in h.cost_resolutions}
    for cost in h.costs:
        identity = cost.entry_client_id
        if cost.kind in {"DATA", "HOST", "OPERATING"} or identity is None:
            # Preserve the prior first-held/next-filled rule, now with explicit,
            # stable order. Allocate each shared account charge exactly once.
            identity = next(
                (
                    k
                    for k, v in ordered
                    if v["opened_at"] <= cost.occurred_at
                    and (
                        k in occupied
                        or v["closed_at"] is None
                        or cost.occurred_at <= v["closed_at"]
                    )
                ),
                None,
            )
            if identity is None:
                identity = next((k for k, v in ordered if v["opened_at"] >= cost.occurred_at), None)
        if identity not in values:
            continue
        value = values[identity]
        amount = resolutions.get(cost.cost_id, cost.amount)
        value["cost_ids"].append(cost.cost_id)
        if amount is None:
            value["unknown"] = True
        else:
            value[
                "operating_cost" if cost.kind in {"DATA", "HOST", "OPERATING"} else "model_cost"
            ] += amount
    results = []
    for identity, value in ordered:
        if identity in occupied or value["closed_at"] is None:
            continue
        net = (
            None
            if value["unknown"]
            else value["cash"] - value["operating_cost"] - value["model_cost"]
        )
        results.append(
            {
                "version": "portfolio-loss-outcome-v2",
                "entry_client_id": identity,
                "family": intent_identity(value["entry"])[2],
                "closed_at": value["closed_at"].isoformat(),
                "outcome": None
                if net is None
                else "LOSS"
                if net < 0
                else "WIN"
                if net > 0
                else "FLAT",
                "net_after_all_costs": str(net) if net is not None else None,
                "operating_cost": str(value["operating_cost"]),
                "model_cost": str(value["model_cost"]),
                "execution_fees": str(value["fees"]),
                "fill_ids": value["fill_ids"],
                "receipts": value["receipts"],
                "cost_ids": value["cost_ids"],
            }
        )
    return results


@exact
def refresh(engine, db, p, now):
    saved = stored_state(db)
    if saved is None or saved["policy"] != engine.policy.loss_control.model_dump(mode="json"):
        raise ExecutionBlocked("FROZEN_NATIVE_LOSS_POLICY_MISMATCH")
    old = LossState.model_validate({k: saved[k] for k in LossState.model_fields if k in saved})
    if now < old.last_checked_at:
        raise ExecutionBlocked("NATIVE_LOSS_CLOCK_REWOUND")
    rows = {
        r["entry_client_id"]: r for r in db.execute("SELECT * FROM execution_option_loss_outcomes")
    }
    if len(rows) != old.consumed_entries:
        raise ValueError("PORTFOLIO_LOSS_HISTORY_CHANGED")
    completed = outcomes(history(engine, db, p, now))
    records = {r["entry_client_id"]: r for r in completed}
    if set(rows) - set(records):
        raise ValueError("PORTFOLIO_LOSS_OUTCOME_DISAPPEARED")
    pending = []
    reasons = []
    for record in completed:
        identity = record["entry_client_id"]
        digest = fingerprint(record)
        if identity in rows:
            if (
                rows[identity]["outcome_hash"] != digest
                or fingerprint(json.loads(rows[identity]["record_json"])) != digest
            ):
                raise ValueError("PORTFOLIO_LOSS_OUTCOME_CHANGED")
        elif record["outcome"] is None:
            reasons.append("NATIVE_LOSS_OUTCOME_PENDING")
        else:
            pending.append(record)
    if (
        pending
        and db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_option_opportunities'"
        ).fetchone()
    ):
        # Entry attribution is not final while a paid cycle can still reserve an
        # order. Never consume a closed outcome and later move that cost to a
        # different play when the same cycle completes.
        for row in db.execute(
            "SELECT c.started_at FROM execution_model_calls c JOIN execution_option_opportunities o ON o.cycle_key=c.source_key WHERE o.status='STARTED'"
        ):
            if any(
                datetime.fromisoformat(row[0]) <= datetime.fromisoformat(r["closed_at"])
                for r in pending
            ):
                reasons.append("NATIVE_LOSS_OUTCOME_PENDING")
                break
    if reasons:
        pending = []
    pending.sort(key=lambda r: (r["closed_at"], r["entry_client_id"]))
    if (
        rows
        and pending
        and min(r["closed_at"] for r in pending)
        < max(json.loads(r["record_json"])["closed_at"] for r in rows.values())
    ):
        raise ValueError("PORTFOLIO_LOSS_HISTORY_ORDER_CHANGED")
    rule = engine.policy.loss_control
    families = {f.family: f for f in old.families}
    rules = {f.family: f for f in rule.families}
    count, locked, until = old.consecutive_losses, old.locked, old.cooldown_until
    for record in pending:
        if datetime.fromisoformat(record["closed_at"]) > now:
            raise ValueError("PORTFOLIO_FUTURE_LOSS_OUTCOME")
        if record["outcome"] == "LOSS":
            count += 1
            locked = locked or count >= rule.max_consecutive_losses
            deadline = now + timedelta(seconds=rule.cooldown_seconds)
            until = max(until, deadline) if until else deadline
        elif not locked:
            count = 0
        family = record["family"]
        if family in families:
            state = families[family]
            fr = rules[family]
            changes = {"consumed_entries": state.consumed_entries + 1}
            if record["outcome"] == "LOSS":
                losses = state.consecutive_losses + 1
                deadline = now + timedelta(seconds=fr.cooldown_seconds)
                changes.update(
                    consecutive_losses=losses,
                    locked=state.locked or losses >= fr.max_consecutive_losses,
                    cooldown_until=max(state.cooldown_until, deadline)
                    if state.cooldown_until
                    else deadline,
                )
            elif not state.locked:
                changes["consecutive_losses"] = 0
            families[family] = state.model_copy(update=changes)
        db.execute(
            "INSERT INTO execution_option_loss_outcomes VALUES(?,?,?)",
            (record["entry_client_id"], fingerprint(record), json.dumps(record, sort_keys=True)),
        )
        engine.journal.event(
            db,
            now,
            "NATIVE_LOSS_OUTCOME_CONSUMED",
            {
                "entry_client_id": record["entry_client_id"],
                "outcome": record["outcome"],
                "outcome_hash": fingerprint(record),
            },
        )
    if locked:
        reasons.append("NATIVE_LOSS_LOCKED")
    if until and now < until:
        reasons.append("NATIVE_LOSS_COOLDOWN")
    state = LossState(
        consecutive_losses=count,
        locked=locked,
        cooldown_until=until,
        last_checked_at=now,
        consumed_entries=len(rows) + len(pending),
        reasons=tuple(sorted(set(reasons))),
        families=tuple(
            f.model_copy(update={"reasons": family_reasons(f, now)}) for f in families.values()
        ),
    )
    db.execute(
        "UPDATE execution_option_loss_control SET state_json=? WHERE id=1",
        (state.model_dump_json(),),
    )
    return state


def guard(engine, db, p, now, family):
    state = refresh(engine, db, p, now)
    reasons = (
        *state.reasons,
        *(r for f in state.families if f.family == family for r in f.reasons),
    )
    if reasons:
        raise ExecutionBlocked(";".join(dict.fromkeys(reasons)))
