"""Frozen broader-entry PAPER coordination on the existing single-owner journal."""

import json
from datetime import datetime
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.options import entry_judgment as judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import EntryOpportunity, EntryPacket, review_entry_plan


def review_for_execution(engine, db, key, request, result, quote, underlying, now, *, exclude=None):
    """Require the full durable receipt, settled cost and fresh admission, never a projection."""
    result = judgment.validate_result(request, result)
    strategy = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    model = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    evidence = json.loads(row[0]) if row and row[0] else {}
    config = json.loads(strategy[0]) if strategy else {}
    if (
        result.error is not None
        or result.plan.action != "ENTER"
        or request.packet.cycle_key != key
        or request.packet.limits != engine._effective_limits()
        or request.configuration.costs != engine.policy.cost_policy
        or config.get("entry_model") != request.configuration.model_dump(mode="json")
        or evidence.get("entry_request") != request.model_dump(mode="json")
        or evidence.get("entry_result") != result.model_dump(mode="json")
        or evidence.get("entry_timely") is not True
        or model is None
        or model["cost"] is None
        or model["packet_hash"] != fingerprint(judgment.request_content(request))
        or model["decision_hash"] != fingerprint(result.plan)
        or model["usage_json"] != result.usage.model_dump_json()
        or not request.packet.as_of
        <= datetime.fromisoformat(evidence["entry_completed_at"])
        < request.packet.valid_until
    ):
        raise ExecutionBlocked("FULL_SETTLED_ENTRY_RECEIPT_REQUIRED")
    for o in request.packet.opportunities:
        if o.session != engine._session(o.candidate.instrument.contract, now):
            raise ExecutionBlocked("ENTRY_SESSION_BINDING_CHANGED")
    return review_entry_plan(
        request.packet,
        result.plan,
        quote=quote,
        underlying=underlying,
        account=engine._account(db, now, exclude=exclude),
        now=now,
    )


async def run_entry_cycle(c, key, candidates, scans, account, quotes, underlyings, evidence):
    """One durable slot, one bounded child, no replay after interruption or uncertainty."""
    at = c.now()
    try:
        secret = c._model_secret()
    except (OSError, ValueError):
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "PRIVATE_MODEL_KEY_UNAVAILABLE"}
        )
    config = judgment.configuration(c.engine.policy.cost_policy, c.judgment_limits, c.entry_policy)
    scan_by_symbol = {s.symbol: s for s in scans}
    opportunities = []
    for candidate in candidates:
        scan = scan_by_symbol[candidate.symbol]
        quote, underlying = (
            quotes[candidate.instrument.instrument_id],
            underlyings[candidate.symbol],
        )
        opportunities.append(
            EntryOpportunity(
                candidate=candidate,
                scan=scan,
                quote=quote,
                underlying=underlying,
                session=c.engine._session(candidate.instrument.contract, at),
                evidence_ids=tuple(fingerprint(x) for x in (scan, quote, underlying)),
            )
        )
    as_of = scans[0].evaluated_at
    packet = EntryPacket(
        decision_id=fingerprint(
            {"population": c.engine.limits.population_id, "cycle": key, "configuration": config}
        ),
        cycle_key=key,
        model_configuration_hash=fingerprint(config),
        as_of=as_of,
        valid_until=min(
            *(o.candidate.admission.valid_until for o in opportunities),
            datetime.fromtimestamp((int(as_of.timestamp()) // 300 + 1) * 300, tz=as_of.tzinfo),
        ),
        account=account,
        limits=c.engine._effective_limits(),
        policy=c.entry_policy,
        opportunities=tuple(opportunities),
    )
    request = judgment.create_request(packet, config, request_id=uuid4().hex, now=at)
    if len(request.model_dump_json().encode()) > judgment.MAX_REQUEST_BYTES:
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "MODEL_PACKET_CAPACITY_EXCEEDED"}
        )
    evidence["entry_request"] = request.model_dump(mode="json")
    evidence["model_input_hash"] = fingerprint(judgment.request_content(request))
    # Full request precedes cost admission. A crash at either boundary leaves a
    # retained STARTED slot; reopening interrupts it and never retries the call.
    c._pending_evidence(key, {**evidence, "status": "MODEL_PENDING"})
    c.engine.begin_model_attempt(key, evidence["model_input_hash"], now=at)
    try:
        result = await c._model_run(request, secret, broad=True)
        result = judgment.EntryResult.model_validate(result.model_dump(warnings=False))
        evidence["entry_result"] = result.model_dump(mode="json")
        completed = c.now()
        evidence["entry_completed_at"] = completed.isoformat()
        evidence["entry_timely"] = (
            c._model_timely(request, at, completed) and at <= completed < packet.valid_until
        )
        c._pending_evidence(key, evidence)
        if (
            result.request_id != request.request_id
            or result.packet_hash != fingerprint(packet)
            or result.configuration_hash != fingerprint(config)
            or result.plan.packet_hash != fingerprint(packet)
            or result.plan.decision_id != packet.decision_id
            or result.usage is None
            or result.usage.model != config.costs.model
            or completed < at
        ):
            raise ValueError("Unknown or foreign model usage")
    except Exception as exc:  # noqa: BLE001 -- private error text is not evidence
        c._model_halt("OPTION_MODEL_COST_UNKNOWN", c.now())
        return c._finish(
            key,
            {
                **evidence,
                "status": "HOLD",
                "reason": "OPTION_MODEL_COST_UNKNOWN",
                "model_error_class": type(exc).__name__,
            },
        )
    # Settle trustworthy usage even for rejected/late geometry. Never discard a
    # known charge because its model proposal cannot be used.
    c.engine.record_entry_usage(key, result.usage, result.plan, now=completed)
    coherent = (
        result.counted_input_tokens == result.usage.input_tokens
        and result.usage.input_tokens <= config.limits.max_input_tokens
        and result.usage.output_tokens <= config.limits.max_output_tokens
    )
    if not coherent:
        c._model_halt("OPTION_MODEL_EVIDENCE_REJECTED", completed)
    if (
        result.error is not None
        or not coherent
        or not evidence["entry_timely"]
        or result.plan.action == "HOLD"
    ):
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "ENTRY_MODEL_HOLD_OR_REJECTED"}
        )
    selected = next((x for x in candidates if x.candidate_id == result.plan.candidate_id), None)
    if selected is None:
        c._model_halt("OPTION_MODEL_EVIDENCE_REJECTED", completed)
        return c._finish(key, {**evidence, "status": "HOLD", "reason": "UNKNOWN_ENTRY_CANDIDATE"})
    quotes, underlyings = c._execution_market(quotes, underlyings)
    quote, underlying = quotes[selected.instrument.instrument_id], underlyings[selected.symbol]
    with c.engine.journal.read() as db:
        c._bound(db)
        review = review_for_execution(
            c.engine, db, key, request, result, quote, underlying, c.now()
        )
    evidence["entry_review"] = review.model_dump(mode="json")
    c._pending_evidence(key, evidence)
    if review.outcome != "ELIGIBLE":
        return c._finish(key, {**evidence, "status": "HOLD", "reason": ";".join(review.reasons)})
    prepared = c.engine.prepare(
        key,
        review.proposal,
        quote,
        underlying,
        now=c.now(),
        origin="MODEL",
        entry_request=request,
        entry_result=result,
    )
    evidence["prepared"] = prepared
    if prepared["status"] != "PREPARED":
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "FRESH_ENTRY_ADMISSION_REJECTED"}
        )
    status = await c.engine.dispatch(prepared["client_id"], quote, underlying, now=c.now())
    return c._finish(
        key,
        {
            **evidence,
            "status": status,
            "client_id": prepared["client_id"],
            "candidate_id": selected.candidate_id,
        },
    )
