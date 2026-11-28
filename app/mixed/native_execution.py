"""Stock preparation and bounded dispatch owned by the exact native option engine."""

import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.mixed.governor import admit_stock
from app.mixed.models import StockProposal
from app.mixed.native_store import history, position, verify_order
from app.mixed.stock_models import StockIntent, StockQuote
from app.options.engine import clock, exact, fingerprint
from app.options.models import SessionWindow
from app.options.process import run_option_process


def enrolled(engine):
    from app.options.engine import OptionExecution

    if type(engine) is not OptionExecution or engine.policy.mixed_owner is None or engine._closed:
        raise ExecutionBlocked("MIXED_NATIVE_OWNER_REQUIRED")


def session(engine, instrument, now):
    w = engine.calendar.current_window(now)
    if w is None:
        return None
    return SessionWindow(
        source=engine.limits.session_source,
        underlying=instrument.symbol,
        opens_at=w.opens_at,
        entry_cutoff_at=w.closes_at - timedelta(minutes=engine.policy.entry_cutoff_minutes),
        closes_at=w.closes_at,
    )


def review(engine, db, proposal, quote, now, *, exclude=None):
    account = engine._account(db, now, exclude=exclude, closing=proposal.action == "CLOSE")
    if (
        not timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=engine.limits.account_max_age_seconds)
    ):
        raise ExecutionBlocked("STOCK_ACCOUNT_STALE")
    h = history(engine, db, as_of=now, exclude=exclude)
    window = session(engine, proposal.instrument, now) if proposal.instrument else None
    result = admit_stock(
        proposal, quote, h, window, now=now, reconciled=True, entry_halted=account.entry_halted
    )
    if proposal.action == "OPEN_LONG":
        if account.entry_blockers:
            raise ExecutionBlocked(";".join(account.entry_blockers))
        if proposal.carry is not None:
            from app.mixed.carry import review_entry

            try:
                review_entry(
                    engine.policy.mixed_owner.stock_carry,
                    engine.calendar,
                    proposal,
                    now,
                    engine.policy.mixed_owner.stocks.max_receive_lag_seconds,
                )
            except ValueError as exc:
                raise ExecutionBlocked(str(exc)) from exc
        elif window is not None and proposal.exit_at > window.closes_at - timedelta(
            minutes=engine.policy.exit_cutoff_minutes
        ):
            raise ExecutionBlocked("STOCK_CARRY_NOT_ENROLLED")
        from app.options.loss_control import refresh

        state = refresh(engine, db, now, exclude=exclude)
        reasons = (
            *state["reasons"],
            *(r for f in state["families"] if f["family"] == proposal.family for r in f["reasons"]),
        )
        if reasons:
            raise ExecutionBlocked(";".join(reasons))
    if result.outcome == "APPROVED":
        result = result.model_copy(
            update={
                "approval_expires_at": min(
                    result.approval_expires_at,
                    account.captured_at + timedelta(seconds=engine.limits.account_max_age_seconds),
                )
            }
        )
    return result, account, window


@exact
def prepare(engine, source_key, proposal, quote, *, now, origin, close_quantity, _db=None):
    enrolled(engine)
    now = clock(now)
    proposal = StockProposal.model_validate(proposal.model_dump(warnings=False))
    quote = StockQuote.model_validate(quote.model_dump(warnings=False)) if quote else None
    if (
        not isinstance(source_key, str)
        or not source_key.strip()
        or len(source_key) > 128
        or origin
        not in (
            {"DETERMINISTIC", "PROTECTIVE", "MODEL", "POSITION_MODEL"}
            if engine.policy.mixed_owner.reasoning is not None
            else {"DETERMINISTIC", "PROTECTIVE"}
        )
    ):
        raise ValueError("Bounded native stock source and model-off origin required")
    if close_quantity is not None:
        from app.mixed.stock_models import _shares

        close_quantity = _shares(close_quantity)
        if (
            proposal.action != "CLOSE"
            or close_quantity <= 0
            or close_quantity % engine.policy.mixed_owner.stocks.share_step
        ):
            raise ValueError("Exact partial stock close ceiling required")
    inputs = {
        "proposal": proposal.model_dump(mode="json"),
        "quote": quote.model_dump(mode="json") if quote else None,
        "origin": origin,
        "close_quantity": str(close_quantity) if close_quantity is not None else None,
    }
    if (
        proposal.action == "OPEN_LONG"
        and engine.policy.mixed_owner.reasoning is not None
        and origin != "MODEL"
    ):
        raise ExecutionBlocked("MIXED_PAID_STOCK_ORIGIN_REQUIRED")
    if origin == "POSITION_MODEL":
        if proposal.action != "CLOSE" or close_quantity is not None:
            raise ValueError("Management closes only the full native position")
        from app.mixed.position import stored

        with nullcontext(_db) if _db is not None else engine.journal.read() as db:
            request, result, _, _ = stored(db, source_key, usable=True)
        inputs.update(
            position_request=request.model_dump(mode="json"),
            position_result=result.model_dump(mode="json"),
        )
    digest = fingerprint(inputs)
    with nullcontext(_db) if _db is not None else engine.journal.write() as db:
        engine._control(db)
        old = db.execute(
            "SELECT * FROM execution_stock_decisions WHERE source_key=?", (source_key,)
        ).fetchone()
        if old:
            if old["fingerprint"] != digest:
                raise ExecutionBlocked("STOCK_SOURCE_IDENTITY_CONFLICT")
            return json.loads(old["result_json"])
        if db.execute(
            "SELECT 1 FROM execution_option_decisions WHERE source_key=?", (source_key,)
        ).fetchone():
            raise ExecutionBlocked("MIXED_SOURCE_IDENTITY_CONFLICT")
        output = {"status": "REJECTED", "client_id": None}
        result = None
        try:
            from app.mixed.selection import guard_stock

            ceiling = guard_stock(engine, db, source_key, proposal, quote, now)
            deadline = None
            if origin == "POSITION_MODEL":
                from app.mixed.position import close_guard

                deadline = close_guard(engine, db, source_key, proposal, quote, now)
            result, account, w = review(engine, db, proposal, quote, now)
            if deadline is not None and result.outcome == "APPROVED":
                result = result.model_copy(
                    update={"approval_expires_at": min(result.approval_expires_at, deadline)}
                )
            if (
                ceiling is not None
                and result.outcome == "APPROVED"
                and (
                    result.quantity > Decimal(ceiling["quantity"])
                    or result.limit_price > Decimal(ceiling["limit_price"])
                )
            ):
                raise ExecutionBlocked("STOCK_ORIGINAL_SELECTION_CEILING_EXCEEDED")
            if ceiling is not None and result.outcome == "APPROVED":
                result = result.model_copy(
                    update={
                        "approval_expires_at": min(
                            result.approval_expires_at,
                            clock(datetime.fromisoformat(ceiling["approval_expires_at"])),
                        )
                    }
                )
            output["admission"] = result.model_dump(mode="json")
            if result.outcome == "HOLD":
                output["status"] = "HOLD"
            elif result.outcome != "APPROVED":
                output["reason"] = ";".join(result.reasons)
            else:
                held = position(engine, db)
                if close_quantity is not None and (held is None or close_quantity > held.quantity):
                    raise ExecutionBlocked("STOCK_PARTIAL_CLOSE_UNOWNED")
                if close_quantity is not None and held and close_quantity < held.quantity:
                    from app.mixed.native_protection import assess_owned

                    if assess_owned(engine, db, quote, now)["status"] != "HEALTHY":
                        raise ExecutionBlocked("STOCK_MANDATORY_EXIT_REQUIRES_REMAINDER")
                qty = (
                    min(result.quantity, close_quantity)
                    if close_quantity is not None
                    else result.quantity
                )
                revision = engine.journal.revision(db)
                if proposal.action == "OPEN_LONG":
                    fields = {
                        "instrument": proposal.instrument,
                        "side": "BUY",
                        "quantity": qty,
                        "limit_price": result.limit_price,
                        "approved_entry_debit": result.entry_debit,
                        "reserved_exit_fee": result.reserved_exit_fee,
                        "exit_at": proposal.exit_at,
                        "carry": proposal.carry,
                        "original_invalidation": proposal.original_invalidation,
                        "original_target": proposal.original_target,
                        "family": proposal.family,
                        "source_hash": proposal.source_hash,
                        "source_at": proposal.source_at,
                        "source_valid_until": proposal.valid_until,
                        "thesis": proposal.thesis,
                    }
                else:
                    fields = held.entry.model_dump(exclude={"approval_hash"})
                    fields.update(
                        side="SELL",
                        quantity=qty,
                        limit_price=result.limit_price,
                        approved_entry_debit=Decimal(0),
                        reserved_exit_fee=Decimal(0),
                        closing_entry_client_id=held.entry.client_id,
                    )
                fields.update(
                    client_id="stock-" + uuid4().hex,
                    source_key=source_key,
                    prepared_at=now,
                    approval_expires_at=result.approval_expires_at,
                    order_expires_at=min(w.closes_at, proposal.exit_at)
                    if proposal.action == "OPEN_LONG"
                    else w.closes_at,
                    account_revision=revision,
                    approval_hash="0" * 64,
                )
                intent = StockIntent.model_validate(fields)
                approval = {
                    "inputs": inputs,
                    "admission": result.model_dump(mode="json"),
                    "account": account.model_dump(mode="json"),
                    "history": history(engine, db, as_of=now).model_dump(mode="json"),
                    "session": w.model_dump(mode="json"),
                    "revision": revision,
                    "intent_terms": intent.model_dump(mode="json", exclude={"approval_hash"}),
                }
                intent = intent.model_copy(update={"approval_hash": fingerprint(approval)})
                db.execute(
                    "INSERT INTO execution_stock_orders VALUES(?,?,?,?,?,'PREPARED',1,NULL,NULL,NULL)",
                    (
                        intent.client_id,
                        source_key,
                        digest,
                        intent.model_dump_json(),
                        json.dumps(approval, sort_keys=True),
                    ),
                )
                output.update(status="PREPARED", client_id=intent.client_id)
        except (ExecutionBlocked, ValueError) as exc:
            output["reason"] = str(exc)
        db.execute(
            "INSERT INTO execution_stock_decisions VALUES(?,?,?,?)",
            (
                source_key,
                digest,
                json.dumps(inputs, sort_keys=True),
                json.dumps(output, sort_keys=True),
            ),
        )
        engine.journal.event(
            db, now, "STOCK_PROPOSAL_RECORDED", {"source_key": source_key, **output}
        )
        return output


@exact
def begin(engine, client_id, quote, now):
    with engine.journal.write() as db:
        engine._control(db)
        row = db.execute(
            "SELECT * FROM execution_stock_orders WHERE client_id=?", (client_id,)
        ).fetchone()
        if row is None:
            raise ExecutionBlocked("UNKNOWN_STOCK_INTENT")
        if row["status"] != "PREPARED" or row["attempted_at"]:
            return row["status"]
        try:
            intent = verify_order(db, row)
            approval = json.loads(row["approval_json"])
            if not intent.prepared_at <= now < intent.approval_expires_at:
                raise ExecutionBlocked("STOCK_ORIGINAL_APPROVAL_EXPIRED")
            proposal = StockProposal.model_validate(approval["inputs"]["proposal"])
            from app.mixed.selection import guard_stock

            guard_stock(engine, db, intent.source_key, proposal, quote, now)
            if approval["inputs"]["origin"] == "POSITION_MODEL":
                from app.mixed.position import close_guard

                close_guard(engine, db, intent.source_key, proposal, quote, now, exclude=client_id)
            result, account, _ = review(engine, db, proposal, quote, now, exclude=client_id)
            if result.outcome != "APPROVED" or result.quantity < intent.quantity:
                raise ExecutionBlocked("STOCK_FRESH_ADMISSION_REQUIRED")
            if intent.side == "BUY":
                p = engine.policy.mixed_owner.stocks
                cap = min(
                    account.settled_cash - account.reserved_cash,
                    account.daily_loss_available,
                    account.total_loss_available,
                    p.max_account_exposure,
                )
                if (
                    result.limit_price > intent.limit_price
                    or intent.approved_entry_debit + intent.reserved_exit_fee > cap
                ):
                    raise ExecutionBlocked("STOCK_ORIGINAL_PRICE_OR_BUDGET_EXCEEDED")
            else:
                held = position(engine, db)
                if (
                    held is None
                    or held.entry.client_id != intent.closing_entry_client_id
                    or result.limit_price < intent.limit_price
                ):
                    raise ExecutionBlocked("STOCK_ORIGINAL_CLOSE_UNAVAILABLE")
                requested = approval["inputs"]["close_quantity"]
                if requested is not None and Decimal(requested) < held.quantity:
                    from app.mixed.native_protection import assess_owned

                    if assess_owned(engine, db, quote, now)["status"] != "HEALTHY":
                        raise ExecutionBlocked("STOCK_MANDATORY_EXIT_REQUIRES_REMAINDER")
        except (ValueError, ExecutionBlocked) as exc:
            db.execute(
                "UPDATE execution_stock_orders SET status='REJECTED',active_lock=NULL WHERE client_id=?",
                (client_id,),
            )
            engine.journal.event(
                db, now, "STOCK_DISPATCH_REJECTED", {"reason": str(exc)}, client_id
            )
            return "REJECTED"
        db.execute(
            "UPDATE execution_stock_orders SET status='SUBMITTING',attempted_at=? WHERE client_id=?",
            (now.isoformat(), client_id),
        )
        engine.journal.event(
            db,
            now,
            "STOCK_ATTEMPT_STARTED",
            {"quote": quote.model_dump(mode="json"), "account": account.model_dump(mode="json")},
            client_id,
        )
        return intent


async def dispatch(engine, client_id, quote, *, now):
    enrolled(engine)
    started = time.monotonic()
    now = clock(now)
    quote = StockQuote.model_validate(quote.model_dump(warnings=False))
    intent = begin(engine, client_id, quote, now)
    if not isinstance(intent, StockIntent):
        return intent
    try:
        result = await run_option_process(
            engine.venue,
            now=now,
            stock_intent=intent,
            timeout_seconds=engine.policy.process_timeout_seconds,
            deadline=started
            + min(
                engine.policy.process_timeout_seconds,
                (intent.approval_expires_at - now).total_seconds(),
            ),
        )
        with engine.journal.write() as db:
            engine._control(db)
            row = db.execute(
                "SELECT status FROM execution_stock_orders WHERE client_id=?", (client_id,)
            ).fetchone()
            if row[0] != "SUBMITTING":
                raise ExecutionBlocked("STOCK_ATTEMPT_STATE_CHANGED")
            db.execute(
                "UPDATE execution_stock_orders SET status='OPEN',order_id=? WHERE client_id=?",
                (result.order_id, client_id),
            )
            engine.journal.event(
                db, now, "STOCK_ACKNOWLEDGED", {"order_id": result.order_id}, client_id
            )
        return "OPEN"
    except BaseException as exc:
        with engine.journal.write() as db:
            db.execute(
                "UPDATE execution_stock_orders SET status='UNKNOWN' WHERE client_id=? AND status='SUBMITTING'",
                (client_id,),
            )
            engine._halt(db, "UNCERTAIN_STOCK_ATTEMPT", now)
            engine.journal.event(
                db, now, "ATTEMPT_UNCERTAIN", {"error_class": type(exc).__name__}, client_id
            )
        if not isinstance(exc, Exception):
            raise
        return "UNKNOWN"
