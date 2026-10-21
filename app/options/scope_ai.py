"""Shared fixed-plan Scope selection, paid receipt binding and native attribution."""

import asyncio
import json
from datetime import datetime
from decimal import Context, Decimal, localcontext
from types import SimpleNamespace

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint


def validate_stored(db, key, evidence, policy):
    """Recheck the complete original model protocol, never a projected choice."""
    from app.options import entry_judgment as judgment
    from app.options.lifecycle import OptionExecutionPolicy

    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    owner = OptionExecutionPolicy.model_validate(
        json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )["policy"]
    )
    request = judgment.EntryRequest.model_validate(evidence["entry_request"])
    result = judgment.validate_result(
        request, judgment.EntryResult.model_validate(evidence["entry_result"])
    )
    call = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    scope = request.packet.scope.model_dump(mode="json") if request.packet.scope else None
    completed = datetime.fromisoformat(evidence["entry_completed_at"])
    if (
        policy.version != "shared-scope-entry-v1"
        or owner.scope_arbitration != policy.version
        or request.configuration.entry_policy.scope_selection is None
        or config.get("entry_model") != request.configuration.model_dump(mode="json")
        or request.configuration.costs != owner.cost_policy
        or request.packet.cycle_key != key
        or scope != evidence.get("scope_candidate")
        or [o.candidate.model_dump(mode="json") for o in request.packet.opportunities]
        != evidence["candidates"]
        or result.error is not None
        or result.plan.action != "ENTER"
        or evidence.get("entry_timely") is not True
        or not request.packet.as_of <= completed < request.packet.valid_until
        or call is None
        or call["cost"] is None
        or result.usage is None
        or call["packet_hash"] != fingerprint(judgment.request_content(request))
        or call["decision_hash"] != fingerprint(result.plan)
        or json.loads(call["usage_json"] or "null") != result.usage.model_dump(mode="json")
        or call["request_id"] != result.usage.request_id
    ):
        raise ExecutionBlocked("SHARED_SCOPE_FULL_PAID_RECEIPT_REQUIRED")
    with localcontext(Context(prec=192)):
        amount = (
            result.usage.input_tokens * owner.cost_policy.input_per_million
            + result.usage.output_tokens * owner.cost_policy.output_per_million
        ) / 1_000_000
    if Decimal(call["cost"]) != amount or amount > owner.cost_policy.max_call_cost:
        raise ExecutionBlocked("SHARED_SCOPE_MODEL_COST_CHANGED")
    return request, result


async def choose_after_usage(c, key, evidence, request, result):
    from app.options.entry_judgment import request_content
    from app.options.scope_arbitration import ScopeCycleInput, execute_scope, selection
    from app.options.scope_reapproval import review_paid_scope

    # Validate even a forged local worker response before a refresh or selection.
    with c.engine.journal.read() as db:
        validate_stored(db, key, evidence, c.scope_policy)
    if not result.plan.scope:
        evidence["candidate_id"] = result.plan.candidate_id
        evidence["scope_arbitration"] = selection(c.scope_policy, key, evidence)
        c._pending_evidence(key, evidence)
        return None
    # Reader receives only the selected play. It cannot supply balances or terms.
    remaining = (request.packet.valid_until - c.now()).total_seconds()
    if remaining <= 0:
        raise ExecutionBlocked("SCOPE_ORIGINAL_PLAN_EXPIRED")
    try:
        async with asyncio.timeout(remaining):
            fresh = await c.scope_refresh(request.packet.scope.binding.play_key)
    except TimeoutError:
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "SCOPE_FRESH_EVIDENCE_TIMEOUT"}
        )
    fresh = ScopeCycleInput.model_validate(fresh.model_dump(warnings=False))
    if fresh.play_key != request.packet.scope.binding.play_key:
        raise ExecutionBlocked("SHARED_SCOPE_REFRESH_PLAY_CHANGED")
    with c.engine.journal.read() as db:
        revision = c.engine.journal.revision(db)
    action = "paid:" + key
    receipt = c.scope_book.review_admission(
        action,
        fresh.play_key,
        expected_revision=revision,
        now=c.now(),
        frame=fresh.frame,
        context=fresh.context,
        underlying=fresh.underlying,
    )
    evidence["scope_fresh_review"] = {
        "action_key": action,
        "revision": receipt["revision"],
        "play_key": fresh.play_key,
        "record_hash": fingerprint(receipt["record"]),
        "status": receipt["record"]["status"],
        "admission_review": receipt["record"]["admission_review"],
    }
    c._pending_evidence(key, evidence)
    if not receipt["record"]["admission_review"]["eligible"]:
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "SCOPE_POST_COST_ADMISSION_REJECTED"}
        )
    evidence["scope_fresh_candidate"] = c.scope_book.entry_selection(
        fresh.play_key, expected_revision=receipt["revision"], now=c.now()
    )
    with c.engine.journal.read() as db:
        evidence["scope_paid_review"] = review_paid_scope(
            c.engine,
            db,
            c.scope_policy.watch,
            original_action_key=request.packet.scope.binding.action_key,
            play_key=fresh.play_key,
            expected_revision=receipt["revision"],
            model_source_key=key,
            request_hash=fingerprint(request_content(request)),
            decision_hash=fingerprint(result.plan),
            now=c.now(),
        )
    evidence["scope_arbitration"] = selection(c.scope_policy, key, evidence)
    c._pending_evidence(key, evidence)
    return await execute_scope(c, key, SimpleNamespace(scope=fresh), evidence)


def paid_review_for_prepare(engine, db, key, evidence, now):
    from app.options.entry_judgment import request_content
    from app.options.scope_arbitration import configuration
    from app.options.scope_reapproval import review_paid_scope

    policy = configuration(db)
    request, result = validate_stored(db, key, evidence, policy)
    if not result.plan.scope or not request.packet.as_of <= now < request.packet.valid_until:
        raise ExecutionBlocked("SHARED_SCOPE_FIXED_SELECTION_OR_DEADLINE_REQUIRED")
    fresh = evidence["scope_fresh_candidate"]
    review = review_paid_scope(
        engine,
        db,
        policy.watch,
        original_action_key=request.packet.scope.binding.action_key,
        play_key=request.packet.scope.binding.play_key,
        expected_revision=fresh["binding"]["revision"],
        model_source_key=key,
        request_hash=fingerprint(request_content(request)),
        decision_hash=fingerprint(result.plan),
        now=now,
    )
    if review != evidence.get("scope_paid_review"):
        raise ExecutionBlocked("SHARED_SCOPE_POST_COST_REVIEW_CHANGED")
    return review


def verify_paid_entry(db, intent, approval, evidence, policy):
    """Historical equivalent after reservation/consumption, with no current-state refresh."""
    key = approval["scope_arbitration"]["cycle_key"]
    request, result = validate_stored(db, key, evidence, policy)
    if intent.entry_lineage is None or intent.entry_lineage.family != "SCOPE":
        if "scope_paid_review" in approval:
            raise ValueError("SHARED_SCOPE_PAID_RECEIPT_FOREIGN_FAMILY")
        if request.packet.policy.scope_selection == "scope-fixed-shortlist-v1" and (
            approval.get("entry_request") != request.model_dump(mode="json")
            or approval.get("entry_result") != result.model_dump(mode="json")
        ):
            raise ValueError("SHARED_SCOPE_SHORTLIST_RECEIPT_CHANGED")
        return
    from app.options.entry_judgment import request_content
    from app.options.lifecycle import OptionExecutionPolicy
    from app.options.models import OptionLimits
    from app.options.scope_reapproval import _charge, _historical, compare_terms, review_receipt

    if not result.plan.scope:
        raise ValueError("SHARED_SCOPE_FIXED_SELECTION_REQUIRED")
    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    engine = SimpleNamespace(
        policy=OptionExecutionPolicy.model_validate(config["policy"]),
        limits=OptionLimits.model_validate(config["limits"]),
    )
    old = _historical(engine, db, policy.watch, request.packet.scope.binding.action_key)
    fresh = _historical(
        engine, db, policy.watch, evidence["scope_fresh_candidate"]["binding"]["action_key"]
    )
    if old != evidence["scope_candidate"] or fresh != evidence["scope_fresh_candidate"]:
        raise ValueError("SHARED_SCOPE_REAPPROVAL_PACKETS_CHANGED")
    deadline = compare_terms(old, fresh, now=intent.prepared_at)
    charge = _charge(
        engine,
        db,
        key,
        fingerprint(request_content(request)),
        fingerprint(result.plan),
        old,
        fresh,
        intent.prepared_at,
    )
    review = review_receipt(old, fresh, deadline, charge)
    if (
        review != evidence.get("scope_paid_review")
        or review != approval.get("scope_paid_review")
        or intent.source_key != review["fresh_source_key"]
        or intent.approval_expires_at > min(deadline, request.packet.valid_until)
    ):
        raise ValueError("SHARED_SCOPE_PAID_ENTRY_CHANGED")


def attributed_scope_entry(db, key, policy):
    """Map the paid cycle to its exact native buy, never matching only by contract."""
    from app.options.attribution import DecisionAttribution, order_attribution
    from app.options.scope_arbitration import configuration

    if policy.scope_arbitration != "shared-scope-entry-v1":
        return None
    rows = db.execute(
        "SELECT * FROM execution_orders WHERE json_extract(approval_json,'$.scope_paid_review') IS NOT NULL "
        "AND (source_key=? OR json_extract(approval_json,'$.scope_arbitration.cycle_key')=?)",
        (key, key),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("SHARED_SCOPE_PAID_ENTRY_AMBIGUOUS")
    row = rows[0]
    approval = json.loads(row["approval_json"])
    cycle = approval["scope_arbitration"]["cycle_key"]
    evidence = json.loads(
        db.execute(
            "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (cycle,)
        ).fetchone()[0]
    )
    request, result = validate_stored(db, cycle, evidence, configuration(db))
    order = order_attribution(db, row)
    decision = db.execute(
        "SELECT inputs_json,result_json FROM execution_option_decisions WHERE source_key=?",
        (row["source_key"],),
    ).fetchone()
    if (
        decision is None
        or json.loads(decision[1]).get("client_id") != row["client_id"]
        or json.loads(decision[0]).get("scope_paid_review") != approval["scope_paid_review"]
    ):
        raise ValueError("SHARED_SCOPE_PAID_DECISION_CHANGED")
    call = db.execute(
        "SELECT cost FROM execution_model_calls WHERE source_key=?", (cycle,)
    ).fetchone()
    return DecisionAttribution(
        role="ENTRY",
        source_key=key,
        packet_hash=fingerprint(request.packet),
        proposal_hash=fingerprint(result.plan),
        proposal_action=result.plan.action,
        thesis=result.plan.thesis,
        uncertainty=result.plan.uncertainty,
        entry_client_id=row["client_id"],
        model_attempted=True,
        model_cost=call[0],
        cost_status="CONFIGURED_ESTIMATE",
        application_status="PREPARED",
        review_outcome="ELIGIBLE",
        **{
            k: v
            for k, v in order.items()
            if k not in {"source_key", "origin", "entry_client_id", "execution_authority"}
        },
    )
