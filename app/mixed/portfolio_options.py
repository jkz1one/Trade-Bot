"""Exact-play option review and reservation on the common portfolio owner."""

import json
from contextlib import nullcontext
from datetime import datetime, timedelta
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.portfolio_admission import admit_portfolio_option
from app.mixed.portfolio_execution import fresh, policy
from app.mixed.portfolio_protection import entry_guard
from app.mixed.portfolio_store import history, reserve
from app.options.engine import clock, exact, fingerprint
from app.options.lifecycle import OptionIntent
from app.options.models import OptionProposal, OptionQuote, UnderlyingQuote


@exact
def prepare(
    engine,
    source_key,
    proposal,
    quote,
    underlying,
    *,
    now,
    play_id=None,
    origin="DETERMINISTIC",
    target_exit_schedule=None,
    target_exit_stage=None,
    entry_time_protection=None,
    entry_premium_protection=None,
    entry_request=None,
    entry_result=None,
    scope_entry=None,
    ceiling=None,
    _db=None,
    **extra,
):
    now = clock(now)
    p = policy(engine)
    proposal = OptionProposal.model_validate(proposal.model_dump())
    quote = OptionQuote.model_validate(quote.model_dump()) if quote else None
    underlying = UnderlyingQuote.model_validate(underlying.model_dump()) if underlying else None
    from app.options.lifecycle import (
        EntryPremiumProtection,
        EntryTimeProtection,
        TargetExitSchedule,
    )

    target_exit_schedule = (
        TargetExitSchedule.model_validate(target_exit_schedule.model_dump())
        if target_exit_schedule is not None
        else None
    )
    entry_time_protection = (
        EntryTimeProtection.model_validate(entry_time_protection.model_dump())
        if entry_time_protection is not None
        else None
    )
    entry_premium_protection = (
        EntryPremiumProtection.model_validate(entry_premium_protection.model_dump())
        if entry_premium_protection is not None
        else None
    )
    if not isinstance(source_key, str) or not source_key.strip() or len(source_key) > 128:
        raise ValueError("Bounded source identity required")
    buying = proposal.action == "OPEN_LONG"
    paid = engine.policy.cost_policy is not None
    if (
        origin not in {"DETERMINISTIC", "PROTECTIVE", "MODEL", "POSITION_MODEL"}
        or any(v is not None for v in extra.values())
        or (entry_request is None) != (entry_result is None)
        or (
            buying
            and scope_entry is None
            and ((origin == "MODEL") != paid or paid != (entry_request is not None))
        )
        or (not buying and entry_request is not None)
        or (buying and origin == "POSITION_MODEL")
    ):
        raise ExecutionBlocked("PORTFOLIO_BOUND_OPTION_RECEIPT_REQUIRED")
    if entry_request is not None:
        from app.options.entry_judgment import EntryRequest, EntryResult

        entry_request = EntryRequest.model_validate(entry_request.model_dump())
        entry_result = EntryResult.model_validate(entry_result.model_dump())
        if entry_request.packet.portfolio_history is None:
            raise ExecutionBlocked("PORTFOLIO_MODEL_PACKET_REQUIRED")
    if scope_entry is not None:
        from app.options.scope_execution import ScopeExecutionRequest

        scope_entry = ScopeExecutionRequest.model_validate(scope_entry.model_dump())
        if not buying or origin != "DETERMINISTIC" or entry_request is not None or ceiling is None:
            raise ExecutionBlocked("PORTFOLIO_EXACT_SCOPE_RECEIPT_REQUIRED")
    if ceiling is not None:
        from app.options.models import OptionAdmission

        ceiling = OptionAdmission.model_validate(ceiling.model_dump())
    inputs = {
        "proposal": proposal.model_dump(mode="json"),
        "quote": quote.model_dump(mode="json") if quote else None,
        "underlying": underlying.model_dump(mode="json") if underlying else None,
        "play_id": play_id,
        "origin": origin,
        "health_management": engine.policy.health_management if buying else None,
        "scope_entry": scope_entry.model_dump(mode="json") if scope_entry else None,
        "ceiling": ceiling.model_dump(mode="json") if ceiling else None,
        "target_exit_schedule": target_exit_schedule.model_dump(mode="json")
        if target_exit_schedule
        else None,
        "entry_time_protection": entry_time_protection.model_dump(mode="json")
        if entry_time_protection
        else None,
        "entry_premium_protection": entry_premium_protection.model_dump(mode="json")
        if entry_premium_protection
        else None,
        "entry_request": entry_request.model_dump(mode="json") if entry_request else None,
        "entry_result": entry_result.model_dump(mode="json") if entry_result else None,
        "targets": target_exit_schedule.model_dump(mode="json") if target_exit_schedule else None,
        "target_exit_stage": target_exit_stage,
        "time_protection": entry_time_protection.model_dump(mode="json")
        if entry_time_protection
        else None,
        "premium_protection": entry_premium_protection.model_dump(mode="json")
        if entry_premium_protection
        else None,
    }
    digest = fingerprint(inputs)
    with nullcontext(_db) if _db is not None else engine.journal.write() as db:
        engine._control(db)
        old = db.execute(
            "SELECT * FROM execution_portfolio_decisions WHERE source_key=?", (source_key,)
        ).fetchone()
        if old:
            if old["fingerprint"] != digest:
                raise ExecutionBlocked("PORTFOLIO_SOURCE_CONFLICT")
            return json.loads(old["result_json"])
        output = {"status": "REJECTED", "client_id": None}
        from app.mixed.portfolio_store import control

        if control(engine, db, p)["snapshot_json"]:
            from app.mixed.portfolio_loss import refresh

            refresh(engine, db, p, now)
        db.execute("SAVEPOINT portfolio_option_admission")
        try:
            c, snap = fresh(engine, db, p, now)
            h = history(engine, db, p, now)
            session = engine._session(proposal.contract, now) if proposal.contract else None
            result = admit_portfolio_option(
                proposal,
                quote,
                underlying,
                h,
                session,
                now=now,
                reconciled=True,
                entry_halted=bool(c["halted"]),
                play_id=play_id,
            )
            output["admission"] = result.model_dump(mode="json")
            if result.outcome == "HOLD":
                output["status"] = "HOLD"
            elif result.outcome != "APPROVED":
                output["reason"] = ";".join(result.reasons)
            else:
                held = reconstruct(h).ledger.positions.get(play_id)
                lineage = carry = None
                scope_packet = None
                protection = entry_review = None
                management_deadline = result.valid_until
                if origin == "POSITION_MODEL":
                    from app.mixed.portfolio_management import close_guard

                    management_deadline = close_guard(
                        engine, db, source_key, play_id, quote, underlying, now
                    )
                if buying:
                    if target_exit_stage is not None:
                        raise ValueError("Target close stage requires an owned play")
                    entry_guard(engine, db, p, now)
                    from app.options.entry_lineage import selected_lineage
                    from app.options.shared_strategy import review_shared_entry

                    review_shared_entry(engine, db, source_key, proposal, quote, underlying, now)
                    from app.options.scope_arbitration import review_entry
                    from app.options.scope_execution import lineage as scope_lineage
                    from app.options.scope_execution import prepare_review

                    arbitration = review_entry(engine, db, source_key, proposal, quote, inputs, now)
                    if arbitration is not None:
                        inputs["scope_arbitration"] = arbitration
                    scope_packet = prepare_review(engine, db, source_key, inputs, scope_entry, now)
                    lineage = (
                        scope_lineage(scope_packet)
                        if scope_packet
                        else selected_lineage(db, source_key, quote.instrument)
                    )
                    if lineage is None:
                        raise ExecutionBlocked("ORIGINAL_PORTFOLIO_OPTION_SELECTION_REQUIRED")
                    from app.mixed.portfolio_loss import guard

                    guard(engine, db, p, now, lineage.family)
                    if entry_request is not None:
                        from app.options.entry_coordination import review_for_execution
                        from app.options.lifecycle import EntryProtection

                        entry_review = review_for_execution(
                            engine,
                            db,
                            source_key,
                            entry_request,
                            entry_result,
                            quote,
                            underlying,
                            now,
                        )
                        if entry_review.outcome != "ELIGIBLE" or entry_review.proposal != proposal:
                            raise ExecutionBlocked("PORTFOLIO_ORIGINAL_MODEL_PLAN_REQUIRED")
                        protection = EntryProtection(
                            packet_hash=entry_review.packet_hash,
                            plan_hash=fingerprint(entry_review.plan),
                            underlying_target=entry_review.plan.underlying_target,
                            exit_by=entry_review.exit_by,
                        )
                    if (lineage.family == "SCOPE") != (scope_packet is not None):
                        raise ExecutionBlocked("PORTFOLIO_SCOPE_NATIVE_RECEIPT_REQUIRED")
                    from app.options.swing_execution import prepare_terms

                    carry = prepare_terms(engine, db, source_key, proposal)
                    exit_at = min(
                        session.closes_at - timedelta(minutes=engine.policy.exit_cutoff_minutes),
                        proposal.contract.last_trading_at
                        - timedelta(seconds=engine.policy.expiry_guard_seconds),
                    )
                    if carry is not None:
                        exit_at = carry.exit_at
                    if protection is not None:
                        exit_at = min(exit_at, protection.exit_by)
                    if entry_time_protection is not None:
                        if (
                            engine.policy.entry_time_protection is None
                            or origin != "DETERMINISTIC"
                            or entry_time_protection.exit_by <= now
                        ):
                            raise ValueError("Time protection not enrolled")
                        exit_at = min(exit_at, entry_time_protection.exit_by)
                    if entry_premium_protection is not None and (
                        engine.policy.entry_premium_protection is None
                        or origin != "DETERMINISTIC"
                        or entry_premium_protection.maximum_loss_fraction
                        > engine.policy.premium_catastrophe_fraction
                    ):
                        raise ValueError("Premium protection not enrolled or widened")
                    if target_exit_schedule is not None:
                        if (
                            engine.policy.target_exits is None
                            or origin != "DETERMINISTIC"
                            or target_exit_schedule.version != engine.policy.target_exits
                            or (
                                target_exit_schedule.needs_entry_reference
                                and engine.policy.target_entry_reference is None
                            )
                            or (
                                target_exit_schedule.has_stops
                                and engine.policy.target_stops is None
                            )
                            or target_exit_schedule.entry_quantity
                            != (ceiling.quantity if ceiling else result.quantity)
                        ):
                            raise ValueError("Exact native target schedule required")
                        target_exit_schedule.check_direction(
                            proposal.contract.right,
                            underlying.ask if proposal.contract.right == "CALL" else underlying.bid,
                        )
                        target_exit_schedule.check_stops(
                            proposal.contract.right, proposal.underlying_invalidation
                        )
                    stop = proposal.underlying_invalidation
                else:
                    if held is None or not hasattr(held, "contract"):
                        raise ValueError("Exact option play required")
                    exit_at = held.exit_at
                    stop = held.original_underlying_invalidation
                    if result.quantity < held.quantity:
                        from app.mixed.portfolio_protection import assess_option

                        if (
                            engine.policy.partial_closes != "whole-contract-v1"
                            or assess_option(engine, play_id, quote, underlying, now=now, _db=db)[
                                "status"
                            ]
                            != "HEALTHY"
                        ):
                            raise ExecutionBlocked("PORTFOLIO_PARTIAL_OPTION_PROTECTION_REQUIRED")
                    if target_exit_stage is not None:
                        from app.mixed.portfolio_targets import review_close

                        review_close(engine, db, play_id, proposal, target_exit_stage, origin, now)
                    if any(
                        v is not None
                        for v in (
                            target_exit_schedule,
                            entry_time_protection,
                            entry_premium_protection,
                        )
                    ):
                        raise ValueError("Close cannot replace original entry protection")
                paid_scope_deadline = result.valid_until
                if inputs.get("scope_paid_review") is not None:
                    paid_scope_deadline = min(
                        datetime.fromisoformat(inputs["scope_paid_review"]["valid_until"]),
                        datetime.fromisoformat(inputs["scope_arbitration"]["model_valid_until"]),
                    )
                quantity = result.quantity
                debit, loss = result.entry_debit, result.full_premium_loss
                if ceiling is not None:
                    if (
                        ceiling.outcome != "APPROVED"
                        or ceiling.contract_id != proposal.contract.contract_id
                        or ceiling.quantity > result.quantity
                        or ceiling.limit_price != result.limit_price
                        or ceiling.entry_debit > result.entry_debit
                        or ceiling.full_premium_loss > result.full_premium_loss
                        or not ceiling.approved_at <= now < ceiling.valid_until
                    ):
                        raise ExecutionBlocked("PORTFOLIO_ORIGINAL_ENTRY_CEILING_CHANGED")
                    quantity, debit, loss = (
                        ceiling.quantity,
                        ceiling.entry_debit,
                        ceiling.full_premium_loss,
                    )
                value = OptionIntent(
                    client_id="option-" + uuid4().hex,
                    source_key=source_key,
                    instrument=quote.instrument,
                    side="BUY" if buying else "SELL",
                    quantity=quantity,
                    limit_price=result.limit_price,
                    approved_entry_debit=debit,
                    approved_full_premium_loss=loss,
                    prepared_at=now,
                    approval_expires_at=min(
                        result.valid_until,
                        paid_scope_deadline,
                        management_deadline,
                        ceiling.valid_until if ceiling else result.valid_until,
                        exit_at if buying else result.valid_until,
                        entry_request.packet.valid_until if entry_request else result.valid_until,
                        snap.captured_at + timedelta(seconds=engine.limits.account_max_age_seconds),
                    ),
                    order_expires_at=min(session.closes_at, exit_at)
                    if buying
                    else session.closes_at,
                    exit_at=exit_at,
                    original_underlying_invalidation=stop,
                    thesis=proposal.thesis,
                    entry_lineage=lineage,
                    entry_protection=protection,
                    swing_carry=carry,
                    closing_entry_client_id=play_id,
                    requested_close_quantity=proposal.close_quantity,
                    target_exit_schedule=target_exit_schedule,
                    target_exit_stage=target_exit_stage,
                    entry_time_protection=entry_time_protection,
                    entry_premium_protection=entry_premium_protection,
                    health_management=engine.policy.health_management if buying else None,
                    trade_floor=engine.policy.trade_floor if buying else None,
                    premium_trail=engine.policy.premium_trail if buying else None,
                )
                approval = {
                    "inputs": inputs,
                    "history": h.model_dump(mode="json"),
                    "session": session.model_dump(mode="json"),
                    "admission": result.model_dump(mode="json"),
                    "entry_lineage": lineage.model_dump(mode="json") if lineage else None,
                }
                reserve(engine, db, p, value, approval, now)
                if scope_packet is not None or inputs.get("scope_arbitration") is not None:
                    # Retain the existing Scope receipt contract alongside the
                    # native portfolio order; this creates no second reservation.
                    db.execute(
                        "INSERT INTO execution_option_decisions VALUES(?,?,?,?)",
                        (
                            source_key,
                            digest,
                            json.dumps(inputs, sort_keys=True),
                            json.dumps({"status": "PREPARED", "client_id": value.client_id}),
                        ),
                    )
                    if scope_packet is not None:
                        from app.options.scope_execution import consume

                        consume(engine, db, value, scope_packet, now)
                    if inputs.get("scope_arbitration") is not None:
                        engine.journal.event(
                            db,
                            now,
                            "SHARED_SCOPE_ENTRY_SELECTED",
                            inputs["scope_arbitration"],
                            value.client_id,
                        )
                output.update(
                    status="PREPARED",
                    client_id=value.client_id,
                    play_id=value.client_id if buying else play_id,
                )
        except (ValueError, ExecutionBlocked) as exc:
            db.execute("ROLLBACK TO portfolio_option_admission")
            output.update(status="REJECTED", client_id=None, reason=str(exc))
        finally:
            db.execute("RELEASE portfolio_option_admission")
        db.execute(
            "INSERT INTO execution_portfolio_decisions VALUES(?,?,?)",
            (source_key, digest, json.dumps(output, sort_keys=True)),
        )
        engine.journal.event(
            db, now, "PORTFOLIO_PROPOSAL_RECORDED", {"source_key": source_key, **output}
        )
        return output


@exact
def begin(engine, client_id, quote, underlying, now):
    from app.mixed.portfolio_store import intent as stored_intent

    p = policy(engine)
    with engine.journal.write() as db:
        engine._control(db)
        row = db.execute(
            "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (client_id,)
        ).fetchone()
        if row is None or row["asset"] != "OPTION":
            raise ExecutionBlocked("UNKNOWN_OPTION_INTENT")
        if row["status"] != "PREPARED" or row["attempted_at"]:
            return row["status"]
        value = stored_intent(row)
        try:
            c, _ = fresh(engine, db, p, now)
            if not value.prepared_at <= now < value.approval_expires_at:
                raise ExecutionBlocked("ORIGINAL_APPROVAL_EXPIRED")
            a = json.loads(row["approval_json"])
            proposal = OptionProposal.model_validate(a["inputs"]["proposal"])
            if a["inputs"]["origin"] == "POSITION_MODEL":
                from app.mixed.portfolio_management import close_guard

                close_guard(
                    engine,
                    db,
                    value.source_key,
                    value.closing_entry_client_id,
                    quote,
                    underlying,
                    now,
                    exclude=client_id,
                )
            h = history(engine, db, p, now, exclude=client_id)
            if value.side == "BUY":
                from app.mixed.portfolio_loss import guard

                guard(engine, db, p, now, value.entry_lineage.family)
                entry_guard(engine, db, p, now)
                from app.options.entry_lineage import selected_lineage
                from app.options.shared_strategy import review_shared_entry

                review_shared_entry(engine, db, value.source_key, proposal, quote, underlying, now)

                if selected_lineage(db, value.source_key, value.instrument) != value.entry_lineage:
                    raise ValueError("Original portfolio option selection changed")
                if a["inputs"].get("scope_entry") is not None:
                    from app.options.scope_execution import dispatch_review

                    dispatch_review(engine, db, value, a, quote, underlying, now)
                if a["inputs"].get("scope_arbitration") is not None:
                    from app.options.scope_arbitration import verify_entry

                    verify_entry(db, value, a["inputs"])
                if a["inputs"].get("entry_request") is not None:
                    from app.options.entry_coordination import review_for_execution
                    from app.options.entry_judgment import EntryRequest, EntryResult

                    request = EntryRequest.model_validate(a["inputs"]["entry_request"])
                    result = EntryResult.model_validate(a["inputs"]["entry_result"])
                    review = review_for_execution(
                        engine,
                        db,
                        value.source_key,
                        request,
                        result,
                        quote,
                        underlying,
                        now,
                        exclude=client_id,
                    )
                    if review.outcome != "ELIGIBLE" or review.proposal != proposal:
                        raise ExecutionBlocked("PORTFOLIO_ORIGINAL_MODEL_PLAN_REQUIRED")
            else:
                held = reconstruct(h).ledger.positions.get(value.closing_entry_client_id)
                if held is None:
                    raise ExecutionBlocked("EXACT_HELD_OPTION_PLAY_REQUIRED")
                if value.quantity < held.quantity:
                    from app.mixed.portfolio_protection import assess_option

                    if (
                        engine.policy.partial_closes != "whole-contract-v1"
                        or assess_option(
                            engine,
                            value.closing_entry_client_id,
                            quote,
                            underlying,
                            now=now,
                            _db=db,
                        )["status"]
                        != "HEALTHY"
                    ):
                        raise ExecutionBlocked("PORTFOLIO_PARTIAL_OPTION_PROTECTION_REQUIRED")
                if value.target_exit_stage is not None:
                    from app.mixed.portfolio_targets import review_close

                    review_close(
                        engine,
                        db,
                        value.closing_entry_client_id,
                        proposal,
                        value.target_exit_stage,
                        a["inputs"]["origin"],
                        now,
                    )
            result = admit_portfolio_option(
                proposal,
                quote,
                underlying,
                h,
                engine._session(value.instrument.contract, now),
                now=now,
                reconciled=True,
                entry_halted=bool(c["halted"]),
                play_id=value.closing_entry_client_id,
            )
            if (
                result.outcome != "APPROVED"
                or result.quantity < value.quantity
                or (
                    result.limit_price > value.limit_price
                    if value.side == "BUY"
                    else result.limit_price < value.limit_price
                )
            ):
                raise ExecutionBlocked("FRESH_PORTFOLIO_OPTION_ADMISSION_REQUIRED")
        except (ValueError, ExecutionBlocked) as exc:
            db.execute(
                "UPDATE execution_portfolio_orders SET status='REJECTED',active_play=NULL WHERE client_id=?",
                (client_id,),
            )
            engine.journal.event(
                db,
                now,
                "PORTFOLIO_DISPATCH_REJECTED",
                {"play_id": row["play_id"], "reason": str(exc)},
                client_id,
            )
            return "REJECTED"
        db.execute(
            "UPDATE execution_portfolio_orders SET status='SUBMITTING',attempted_at=? WHERE client_id=?",
            (now.isoformat(), client_id),
        )
        engine.journal.event(
            db,
            now,
            "PORTFOLIO_ATTEMPT_STARTED",
            {
                "play_id": row["play_id"],
                "quote": quote.model_dump(mode="json"),
                "underlying": underlying.model_dump(mode="json") if underlying else None,
            },
            client_id,
        )
        return value


async def dispatch(engine, client_id, quote, underlying=None, *, now):
    import time

    from app.mixed.portfolio_execution import submit

    started = time.monotonic()
    now = clock(now)
    quote = OptionQuote.model_validate(quote.model_dump())
    underlying = UnderlyingQuote.model_validate(underlying.model_dump()) if underlying else None
    value = begin(engine, client_id, quote, underlying, now)
    if not isinstance(value, OptionIntent):
        return value
    return await submit(engine, value, now, started)
