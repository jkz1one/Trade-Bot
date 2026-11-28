"""Read-only post-cost Scope reapproval evidence; never native entry authority.

An original selection cannot be refreshed in place after a paid call. This
review binds both immutable watch actions and the intervening settled charge,
retains original ceilings/deadline, and requires the latest owned admission.
The coordinator must separately bind its complete model request/result and
atomically consume this evidence; deterministic v1 does not do so.
"""

import json
from datetime import datetime
from decimal import Context, Decimal, localcontext

from app.execution.economics import UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.options.engine import clock, fingerprint
from app.options.scope_entry import packet_from_record, select_entry, verify_binding
from app.options.scope_execution import lineage

# Admission-dependent diagnostics may refresh; trading terms may not.
LOCKED_PACKET = (
    "choice",
    "geometry",
    "instrument",
    "proposal",
    "entry_time_protection",
    "effective_limits",
    "session",
)
LOCKED_MANAGEMENT = (
    "version",
    "reference_commit",
    "contract_id",
    "geometry",
    "policy",
    "owner_maximum_loss_fraction",
    "source_estimated_premium_stop_fraction",
    "entry_premium_protection",
    "admitted_quantity",
    "scale_profile",
    "source_allocation",
    "target_exit_schedule",
)


def _historical(engine, db, policy, action_key):
    row = db.execute(
        "SELECT request_hash,result_json FROM execution_option_scope_watch_actions WHERE action_key=?",
        (action_key,),
    ).fetchone()
    if row is None:
        raise ExecutionBlocked("SCOPE_REAPPROVAL_ORIGINAL_REQUIRED")
    receipt = json.loads(row["result_json"])
    record = receipt["record"]
    event = db.execute(
        "SELECT kind,occurred_at,payload FROM execution_events WHERE sequence=?",
        (receipt["revision"],),
    ).fetchone()
    if (
        event is None
        or event["kind"] != "SCOPE_WATCH_ACTION"
        or json.loads(event["payload"]) != {"action_key": action_key, "record": record}
        or receipt.get("authority") is not False
        or receipt.get("live_enabled") is not False
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_ORIGINAL_CHANGED")
    verify_binding(
        db,
        record,
        policy,
        engine.policy,
        engine.limits,
        {
            "action_key": action_key,
            "sequence": receipt["revision"],
            "recorded_at": event["occurred_at"],
        },
        json.loads,
    )
    return packet_from_record(record, policy, engine.policy, engine.limits)


def _charge(engine, db, source_key, request_hash, decision_hash, original, fresh, now):
    policy = engine.policy.cost_policy
    row = db.execute(
        "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
    ).fetchone()
    if policy is None or row is None or row["cost"] is None or row["usage_json"] is None:
        raise ExecutionBlocked("SCOPE_REAPPROVAL_SETTLED_COST_REQUIRED")
    usage = UsageEvidence.model_validate_json(row["usage_json"])
    with localcontext(Context(prec=192)):
        cost = (
            usage.input_tokens * policy.input_per_million
            + usage.output_tokens * policy.output_per_million
        ) / 1_000_000
    if (
        row["packet_hash"] != request_hash
        or row["decision_hash"] != decision_hash
        or usage.request_id != row["request_id"]
        or usage.model != policy.model
        or Decimal(row["cost"]) != cost
        or cost > policy.max_call_cost
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_COST_CHANGED")
    events = db.execute(
        "SELECT sequence,kind,occurred_at,payload FROM execution_events "
        "WHERE kind IN ('OPTION_MODEL_ATTEMPT_ADMITTED','OPTION_MODEL_USAGE_RECORDED') "
        "AND json_extract(payload,'$.source_key')=? ORDER BY sequence",
        (source_key,),
    ).fetchall()
    if len(events) != 2:
        raise ExecutionBlocked("SCOPE_REAPPROVAL_COST_AUDIT_REQUIRED")
    attempt, settled = events
    start, end = (clock(datetime.fromisoformat(e["occurred_at"])) for e in events)
    if (
        attempt["kind"] != "OPTION_MODEL_ATTEMPT_ADMITTED"
        or settled["kind"] != "OPTION_MODEL_USAGE_RECORDED"
        or not original["binding"]["revision"]
        < attempt["sequence"]
        < settled["sequence"]
        < fresh["binding"]["revision"]
        or json.loads(attempt["payload"]) != {"source_key": source_key, "input_hash": request_hash}
        or json.loads(settled["payload"])
        != {"source_key": source_key, "usage": usage.model_dump(mode="json"), "cost": row["cost"]}
        or start != clock(datetime.fromisoformat(row["started_at"]))
        or not datetime.fromisoformat(original["binding"]["evaluated_at"])
        <= start
        <= end
        <= datetime.fromisoformat(fresh["binding"]["evaluated_at"])
        <= now
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_COST_ORDER_CHANGED")
    return {
        "source_key": source_key,
        "request_hash": request_hash,
        "decision_hash": decision_hash,
        "usage": usage.model_dump(mode="json"),
        "cost": str(cost),
        "attempt_revision": attempt["sequence"],
        "settled_revision": settled["sequence"],
    }


def compare_terms(original, fresh, *, now):
    """Compare already verified projections; this alone cannot validate stored authority."""
    now = clock(now)
    old, new = original["binding"], fresh["binding"]
    if (
        any(
            old[k] != new[k]
            for k in (
                "population_id",
                "account_id",
                "play_key",
                "original_call_hash",
                "policy_hash",
                "owner_hash",
            )
        )
        or old["action_key"] == new["action_key"]
        or old["revision"] >= new["revision"]
        or any(original[k] != fresh[k] for k in LOCKED_PACKET)
        or any(original["management"][k] != fresh["management"][k] for k in LOCKED_MANAGEMENT)
        or original["execution_blockers"]
        or fresh["execution_blockers"]
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_ORIGINAL_TERMS_CHANGED")
    deadline = min(
        datetime.fromisoformat(old["valid_until"]), datetime.fromisoformat(new["valid_until"])
    )
    if (
        not datetime.fromisoformat(old["evaluated_at"])
        <= datetime.fromisoformat(new["evaluated_at"])
        <= now
        < deadline
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_ORIGINAL_DEADLINE_EXPIRED")
    before, after = original["admission"], fresh["admission"]
    if (
        after["quantity"] != before["quantity"]
        or any(
            Decimal(after[k]) > Decimal(before[k])
            for k in ("limit_price", "entry_debit", "full_premium_loss", "reserved_exit_fees")
        )
        or Decimal(after["minimum_exit_cash_change"]) < Decimal(before["minimum_exit_cash_change"])
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_ORIGINAL_CEILING_EXCEEDED")
    for field in ("quote", "underlying"):
        if any(
            datetime.fromisoformat(fresh[field][k]) < datetime.fromisoformat(original[field][k])
            for k in ("source_at", "received_at")
        ):
            raise ExecutionBlocked("SCOPE_REAPPROVAL_MARKET_TIME_REGRESSION")
    if datetime.fromisoformat(fresh["account"]["captured_at"]) < datetime.fromisoformat(
        original["account"]["captured_at"]
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_ACCOUNT_TIME_REGRESSION")
    return deadline


def review_paid_scope(
    engine,
    db,
    policy,
    *,
    original_action_key,
    play_key,
    expected_revision,
    model_source_key,
    request_hash,
    decision_hash,
    now,
):
    """Read within one journal transaction. Writes nothing and grants no order authority.

    Callers must obtain a NEW owned admission after usage settlement; a changed
    journal revision is never waived. Request/decision hashes must come from the
    retained full model protocol, not free-form output. This diagnostic does not
    attest that protocol or associate a cycle's charge with a native trade outcome.
    """
    now = clock(now)
    original = _historical(engine, db, policy, original_action_key)
    fresh = select_entry(engine, db, policy, play_key, expected_revision, now)
    deadline = compare_terms(original, fresh, now=now)
    charge = _charge(
        engine, db, model_source_key, request_hash, decision_hash, original, fresh, now
    )
    if engine.portfolio_policy is not None:
        from app.mixed.portfolio_models import candidate_account

        account = candidate_account(engine, db, "SPX", now)
    else:
        account = engine._account(db, now)
    if (
        account.entry_halted
        or account.entry_blockers
        or not account.budgets_known
        or account.position is not None
        or account.working_orders
        or account.model_dump(mode="json") != fresh["account"]
    ):
        raise ExecutionBlocked("SCOPE_REAPPROVAL_POST_COST_ACCOUNT_REQUIRED")
    return review_receipt(original, fresh, deadline, charge)


def review_receipt(original, fresh, deadline, charge):
    body = {
        "version": "scope-post-cost-review-v1",
        "authority": False,
        "live_enabled": False,
        "status": "REVIEWED",
        "original_packet_hash": fingerprint(original),
        "fresh_packet_hash": fingerprint(fresh),
        "original_binding": original["binding"],
        "fresh_binding": fresh["binding"],
        "valid_until": deadline.isoformat(),
        "original_source_key": lineage(original).opportunity_key,
        "fresh_source_key": lineage(fresh).opportunity_key,
        "model_charge": charge,
        "account_hash": fingerprint(fresh["account"]),
    }
    return {**body, "review_hash": fingerprint(body)}
