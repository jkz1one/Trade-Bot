"""Opt-in durable management on one native PAPER owner. No broker transport."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.options import position_judgment as judgment
from app.options.degen import scan_degen
from app.options.engine import clock, exact, fingerprint
from app.options.lifecycle import OptionIntent, OptionPosition, PositionExitProtection
from app.options.models import OptionQuote, UnderlyingQuote
from app.options.position_reasoning import PositionPacket, review_position_plan


def _bound_request(engine, db, key, request):
    request = judgment.PositionRequest.model_validate(request.model_dump(warnings=False))
    c = getattr(engine, "_degen_owner", None)
    if c is None or c.position_policy is None:
        raise ExecutionBlocked("FROZEN_POSITION_MODEL_REQUIRED")
    ledger = c._bound(db)
    row = db.execute(
        "SELECT * FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    evidence = json.loads(row["result_json"]) if row and row["result_json"] else {}
    config = json.loads(c._frozen)
    packet = request.packet
    if (
        row is None
        or row["status"] != "STARTED"
        or key != "degen:" + str(int(packet.as_of.timestamp()) // 300)
        or packet.cycle_key != "position:" + key.split(":")[1]
        or packet.limits != engine._effective_limits()
        or packet.execution_policy != engine.policy
        or packet.session != engine._session(packet.position.contract, packet.as_of)
        or config.get("position_model") != request.configuration.model_dump(mode="json")
        or evidence.get("position_request") != request.model_dump(mode="json")
    ):
        raise ExecutionBlocked("FULL_FROZEN_POSITION_REQUEST_REQUIRED")
    entry = db.execute(
        "SELECT intent_json FROM execution_orders WHERE client_id=?",
        (packet.position.entry_client_id,),
    ).fetchone()
    if entry is None or OptionIntent.model_validate_json(entry[0]) != packet.entry:
        raise ExecutionBlocked("POSITION_ENTRY_CHANGED")
    return ledger, evidence


def validate_admission(engine, db, key, request, input_hash, now):
    ledger, _ = _bound_request(engine, db, key, request)
    packet = request.packet
    if (
        ledger.position != packet.position
        or engine.journal.revision(db) != packet.position_revision
        or input_hash != fingerprint(judgment.request_content(request))
        or not packet.as_of <= now < packet.valid_until
    ):
        raise ExecutionBlocked("POSITION_ADMISSION_REVISION_CHANGED")
    review = review_position_plan(
        packet,
        judgment.maintain(packet),
        position=ledger.position,
        position_revision=packet.position_revision,
        account=engine._account(db, now),
        quote=packet.quote,
        underlying=packet.underlying,
        now=now,
    )
    if review.outcome != "MAINTAIN":
        raise ExecutionBlocked("POSITION_MODEL_ADMISSION_BLOCKED")


def review_for_execution(engine, db, key, request, result, quote, underlying, now, *, exclude=None):
    """Match full stored result and settled cost, then review current owned truth."""
    now = clock(now)
    quote = (
        OptionQuote.model_validate(quote.model_dump(warnings=False)) if quote is not None else None
    )
    underlying = (
        UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
        if underlying is not None
        else None
    )
    ledger, evidence = _bound_request(engine, db, key, request)
    result = judgment.validate_result(request, result)
    model = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    if (
        result.error is not None
        or evidence.get("position_result") != result.model_dump(mode="json")
        or evidence.get("position_timely") is not True
        or model is None
        or model["cost"] is None
        or model["packet_hash"] != fingerprint(judgment.request_content(request))
        or model["decision_hash"] != fingerprint(result.plan)
        or model["usage_json"] != result.usage.model_dump_json()
        or not request.packet.as_of
        <= datetime.fromisoformat(evidence["position_completed_at"])
        < request.packet.valid_until
    ):
        raise ExecutionBlocked("FULL_SETTLED_POSITION_RECEIPT_REQUIRED")
    if exclude is not None:
        decision = db.execute(
            "SELECT * FROM execution_option_decisions WHERE source_key=?", (key,)
        ).fetchone()
        consumed = json.loads(decision["result_json"]) if decision else {}
        inputs = json.loads(decision["inputs_json"]) if decision else {}
        if (
            consumed.get("client_id") != exclude
            or consumed.get("status") != "PREPARED"
            or inputs.get("position_request") != request.model_dump(mode="json")
            or inputs.get("position_result") != result.model_dump(mode="json")
        ):
            raise ExecutionBlocked("POSITION_REVISION_CONSUMPTION_REQUIRED")
    # These callers hold the owner's write transaction. Fresh protection must
    # survive a discretionary rejection or a later rebound, including dispatch races.
    if ledger.position is not None:
        protected = engine._assess_owned(db, ledger, quote, underlying, now)
        if protected != ledger.position and (
            protected.exit_reason
            or protected.supervision_issue
            or protected.trade_floor is not None
            or engine.policy.health_management is not None
        ):
            ledger = ledger.model_copy(update={"position": protected})
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1", (ledger.model_dump_json(),)
            )
            if protected.supervision_issue:
                engine._halt(db, protected.supervision_issue, now)
            engine.journal.event(
                db,
                now,
                "OPTION_MANAGEMENT_PROTECTION_RECHECKED",
                {
                    "source_key": key,
                    "exit_reason": protected.exit_reason,
                    "issue": protected.supervision_issue,
                    "position": protected.model_dump(mode="json"),
                },
            )
    # The captured journal revision is immutable in the admitted request. Model cost
    # and heartbeat writes may advance the global sequence; the position itself may not change.
    return review_position_plan(
        request.packet,
        result.plan,
        position=ledger.position,
        position_revision=request.packet.position_revision,
        account=engine._account(db, now, exclude=exclude),
        quote=quote,
        underlying=underlying,
        now=now,
    )


@exact
def apply_position_plan(c, key, request, result, quote, underlying, *, now):
    """Atomic consumption plus stop mutation or native close preparation; no dispatch."""
    inputs = {
        "position_request": request.model_dump(mode="json"),
        "position_result": result.model_dump(mode="json"),
    }
    digest = fingerprint(inputs)
    with c.engine.journal.write() as db:
        ledger = c._bound(db)
        prior = db.execute(
            "SELECT * FROM execution_option_decisions WHERE source_key=?", (key,)
        ).fetchone()
        if prior:
            if prior["fingerprint"] != digest:
                raise ExecutionBlocked("POSITION_SOURCE_IDENTITY_CONFLICT")
            return json.loads(prior["result_json"])
        if db.execute(
            "SELECT 1 FROM execution_option_decisions WHERE json_extract(inputs_json,'$.position_request.packet.position_revision')=?",
            (request.packet.position_revision,),
        ).fetchone():
            raise ExecutionBlocked("POSITION_REVISION_ALREADY_CONSUMED")
        review = review_for_execution(c.engine, db, key, request, result, quote, underlying, now)
        output = {
            "status": review.outcome,
            "position_review": review.model_dump(mode="json"),
            "client_id": None,
        }
        if review.outcome == "ELIGIBLE":
            if review.plan.action == "TIGHTEN":
                position = OptionPosition.model_validate(
                    ledger.position.model_dump()
                    | {"tightened_underlying_invalidation": review.tightened_invalidation}
                )
                db.execute(
                    "UPDATE execution_control SET ledger_json=? WHERE id=1",
                    (ledger.model_copy(update={"position": position}).model_dump_json(),),
                )
                c.engine.journal.event(
                    db,
                    now,
                    "OPTION_INVALIDATION_TIGHTENED",
                    {"price": str(review.tightened_invalidation), "source_key": key},
                )
                output["status"] = "TIGHTENED"
            elif review.plan.action == "EXIT_ALL":
                admission, p = review.admission, ledger.position
                intent = OptionIntent(
                    client_id="option-" + uuid4().hex,
                    source_key=key,
                    instrument=quote.instrument,
                    side="SELL",
                    closing_entry_client_id=p.entry_client_id,
                    quantity=admission.quantity,
                    limit_price=admission.limit_price,
                    approved_entry_debit=0,
                    approved_full_premium_loss=0,
                    prepared_at=now,
                    approval_expires_at=admission.valid_until,
                    order_expires_at=request.packet.session.closes_at,
                    exit_at=p.exit_at,
                    original_underlying_invalidation=p.original_underlying_invalidation,
                    thesis=review.plan.thesis,
                    position_protection=PositionExitProtection(
                        packet_hash=review.packet_hash,
                        plan_hash=fingerprint(review.plan),
                        entry_client_id=p.entry_client_id,
                        position_revision=request.packet.position_revision,
                    ),
                )
                approval = {
                    **inputs,
                    "origin": "POSITION_MODEL",
                    "closing_entry_client_id": p.entry_client_id,
                    "proposal": review.proposal.model_dump(mode="json"),
                    "quote": quote.model_dump(mode="json"),
                    "underlying": underlying.model_dump(mode="json"),
                    "account": c.engine._account(db, now).model_dump(mode="json"),
                    "admission": admission.model_dump(mode="json"),
                    "effective_limits": c.engine._effective_limits().model_dump(mode="json"),
                }
                db.execute(
                    "INSERT INTO execution_orders VALUES(?,?,?,?,?,'PREPARED',1,NULL,NULL,NULL)",
                    (
                        intent.client_id,
                        key,
                        digest,
                        intent.model_dump_json(),
                        json.dumps(approval, sort_keys=True),
                    ),
                )
                output.update(status="PREPARED", client_id=intent.client_id)
        # MAINTAIN/rejection are terminal for this admitted revision too. A later
        # completed slot can receive a new revision, never a second callback here.
        db.execute(
            "INSERT INTO execution_option_decisions VALUES(?,?,?,?)",
            (key, digest, json.dumps(inputs, sort_keys=True), json.dumps(output, sort_keys=True)),
        )
        c.engine.journal.event(
            db,
            now,
            "OPTION_POSITION_PLAN_CONSUMED",
            {"source_key": key, "position_revision": request.packet.position_revision, **output},
        )
        return output


async def run_position_cycle(c, key, frame):
    at = c.now()
    evidence = {"entry_allowed": False}
    try:
        secret = c._model_secret()
        histories = [h for h in frame.histories if h.symbol in c.policy.symbols]
        if len({h.symbol for h in histories}) != len(histories):
            raise ValueError("Unique management context required")
        config = judgment.configuration(
            c.engine.policy.cost_policy, c.judgment_limits, c.position_policy
        )
        with c.engine.journal.read() as db:
            ledger = c._bound(db)
            p = ledger.position
            if p is None:
                raise ValueError("Exact owned position required")
            history = [h for h in histories if h.symbol == p.contract.underlying]
            if (
                len(history) != 1
                or len(c._position_quotes) != 1
                or len(c._position_underlyings) != 1
            ):
                raise ValueError("Current held contract/context required")
            scan = scan_degen(history[0], c.policy, c.engine.calendar.current_window(at), now=at)
            entry = OptionIntent.model_validate_json(
                db.execute(
                    "SELECT intent_json FROM execution_orders WHERE client_id=?",
                    (p.entry_client_id,),
                ).fetchone()[0]
            )
            account = c.engine._account(db, at)
            q, u = c._position_quotes[0], c._position_underlyings[0]
            packet = PositionPacket(
                decision_id=fingerprint(
                    {
                        "population": c.engine.limits.population_id,
                        "cycle": key,
                        "configuration": config,
                    }
                ),
                cycle_key="position:" + key.split(":")[1],
                model_configuration_hash=fingerprint(config),
                as_of=at,
                valid_until=min(
                    at + timedelta(seconds=c.position_policy.max_lease_seconds),
                    datetime.fromtimestamp((int(at.timestamp()) // 300 + 1) * 300, tz=at.tzinfo),
                    p.exit_at,
                    p.contract.last_trading_at
                    - timedelta(seconds=c.engine.policy.expiry_guard_seconds),
                ),
                position_revision=c.engine.journal.revision(db),
                position=p,
                entry=entry,
                account=account,
                quote=q,
                underlying=u,
                scan=scan,
                session=c.engine._session(p.contract, at),
                limits=c.engine._effective_limits(),
                execution_policy=c.engine.policy,
                policy=c.position_policy,
                evidence_ids=tuple(fingerprint(x) for x in (p, entry, account, q, u, scan)),
            )
        request = judgment.create_request(packet, config, request_id=uuid4().hex, now=at)
        if len(request.model_dump_json().encode()) > judgment.MAX_REQUEST_BYTES:
            raise ValueError("Position request capacity exceeded")
    except (OSError, ValueError, ExecutionBlocked):
        return c._finish(
            key, {**evidence, "status": "HELD", "reason": "POSITION_PREFLIGHT_UNAVAILABLE"}
        )
    evidence["position_request"] = request.model_dump(mode="json")
    evidence["model_input_hash"] = fingerprint(judgment.request_content(request))
    c._pending_evidence(key, {**evidence, "status": "MODEL_PENDING"})
    try:
        c.engine.begin_model_attempt(
            key, evidence["model_input_hash"], now=at, position_request=request
        )
    except ExecutionBlocked as exc:
        return c._finish(key, {**evidence, "status": "HELD", "reason": str(exc)})
    try:
        result = (
            await c.replay_model.run(request)
            if c.replay_model is not None
            else await judgment.run_position_process(request, secret)
        )
        result = judgment.PositionResult.model_validate(result.model_dump(warnings=False))
        completed = c.now()
        evidence.update(
            position_result=result.model_dump(mode="json"),
            position_completed_at=completed.isoformat(),
            position_timely=c._model_timely(request, at, completed)
            and at <= completed < packet.valid_until,
        )
        c._pending_evidence(key, evidence)
        if (
            result.request_id != request.request_id
            or result.packet_hash != fingerprint(packet)
            or result.configuration_hash != fingerprint(config)
            or result.plan.packet_hash != fingerprint(packet)
            or result.plan.decision_id != packet.decision_id
            or result.plan.entry_client_id != p.entry_client_id
            or result.plan.position_revision != packet.position_revision
            or result.usage is None
            or result.usage.model != config.costs.model
            or completed < at
        ):
            raise ValueError("Unknown or foreign management usage")
    except Exception as exc:  # noqa: BLE001 -- never echo private provider errors
        c._model_halt("OPTION_MODEL_COST_UNKNOWN", c.now())
        evidence["management"] = await c.supervise(c._position_quotes, c._position_underlyings)
        return c._finish(
            key,
            {
                **evidence,
                "status": "HELD",
                "reason": "OPTION_MODEL_COST_UNKNOWN",
                "model_error_class": type(exc).__name__,
            },
        )
    c.engine.record_position_usage(key, result.usage, result.plan, now=completed)
    coherent = (
        result.counted_input_tokens == result.usage.input_tokens
        and result.usage.input_tokens <= config.limits.max_input_tokens
        and result.usage.output_tokens <= config.limits.max_output_tokens
    )
    if not coherent:
        c._model_halt("OPTION_MODEL_EVIDENCE_REJECTED", completed)
    # Independent protection runs even for paid MAINTAIN, invalid output or unknown costs.
    protection = await c.supervise(c._position_quotes, c._position_underlyings)
    evidence["management"] = protection
    if result.error is not None or not coherent or not evidence["position_timely"]:
        return c._finish(
            key, {**evidence, "status": "HELD", "reason": "POSITION_MODEL_MAINTAIN_OR_REJECTED"}
        )
    quote = c._position_quotes[0] if c._position_quotes else None
    underlying = c._position_underlyings[0] if c._position_underlyings else None
    applied = apply_position_plan(c, key, request, result, quote, underlying, now=c.now())
    evidence["position_action"] = applied
    c._pending_evidence(key, evidence)
    if applied["status"] != "PREPARED":
        return c._finish(key, {**evidence, "status": applied["status"]})
    status = await c.engine.dispatch(applied["client_id"], quote, underlying, now=c.now())
    if status == "REJECTED":
        evidence["management"] = await c.supervise(c._position_quotes, c._position_underlyings)
    return c._finish(key, {**evidence, "status": status, "client_id": applied["client_id"]})
