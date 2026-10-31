"""Independent original stock stop/target/time protection on the common owner."""

import json
from datetime import timedelta
from decimal import Decimal

from app.options.models import paper_market_evidence
from app.execution.engine import ExecutionBlocked
from app.mixed.models import StockProposal
from app.mixed.native_execution import enrolled, session
from app.mixed.native_store import position, protection
from app.mixed.stock_models import StockQuote
from app.options.engine import clock, exact
from app.options.governor import _fresh


@exact
def assess(engine, quote, *, now):
    enrolled(engine)
    now = clock(now)
    quote = StockQuote.model_validate(quote.model_dump(warnings=False)) if quote else None
    with engine.journal.write() as db:
        return assess_owned(engine, db, quote, now)


def assess_owned(engine, db, quote, now):
    c = engine._control(db)
    account = engine._account(db, now, closing=True)
    if (
        not timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=engine.limits.account_max_age_seconds)
    ):
        raise ExecutionBlocked("STOCK_ACCOUNT_SUPERVISION_STALE")
    p = position(engine, db)
    guard = protection(engine, db)
    issue = None
    if p:
        limits = engine.policy.mixed_owner.stocks
        w = session(engine, p.instrument, now)
        deadline = p.entry.exit_at
        if w and p.entry.carry is None:
            deadline = min(
                deadline, w.closes_at - timedelta(minutes=engine.policy.exit_cutoff_minutes)
            )
        reason = guard.exit_reason
        if now >= deadline or (w is None and p.entry.carry is None):
            reason = reason or "STOCK_TIME_EXIT"
        if p.entry.carry is not None:
            from app.mixed.carry import verify_terms

            verify_terms(
                engine.policy.mixed_owner.stock_carry,
                engine.calendar,
                p.entry.carry,
                source_hash=p.entry.source_hash,
                symbol=p.instrument.symbol,
                exit_at=deadline,
            )
        if w is None and p.entry.carry is not None:
            issue = "STOCK_CARRY_MARKET_CLOSED"
        elif (
            quote is None
            or quote.instrument != p.instrument
            or quote.source != limits.quote_source
            or not quote.complete
            or not paper_market_evidence(quote)
            or not _fresh(
                quote.source_at,
                quote.received_at,
                now,
                limits.quote_max_age_seconds,
                limits.max_receive_lag_seconds,
            )
        ):
            issue = "STOCK_SUPERVISION_QUOTE_REQUIRED"
        else:
            if quote.bid <= guard.invalidation:
                reason = reason or "STOCK_INVALIDATION"
            if quote.bid >= p.entry.original_target:
                reason = reason or "STOCK_TARGET"
        guard = guard.model_copy(
            update={
                "exit_reason": reason,
                "exit_required_at": guard.exit_required_at or (now if reason else None),
                "issue": issue,
            }
        )
        db.execute(
            "UPDATE execution_mixed_control SET protection_json=? WHERE id=1",
            (guard.model_dump_json(),),
        )
    elif json.loads(c["ledger_json"])["position"] is not None:
        raise ExecutionBlocked("STOCK_SUPERVISOR_CANNOT_IGNORE_OPTION")
    status = "BLOCKED" if issue else "EXIT_REQUIRED" if guard and guard.exit_reason else "HEALTHY"
    result = {
        "status": status,
        "issue": issue,
        "exit_reason": guard.exit_reason if guard else None,
        "entry_client_id": p.entry.client_id if p else None,
        "snapshot_id": account.snapshot_id,
    }
    db.execute(
        "INSERT INTO execution_supervisor VALUES(1,?,'HEALTHY',NULL,1,?,?,NULL,NULL) ON CONFLICT(id) DO UPDATE SET status=excluded.status,heartbeat_at=excluded.heartbeat_at,result_json=excluded.result_json",
        (engine.policy.model_dump_json(), now.isoformat(), json.dumps(result, sort_keys=True)),
    )
    if issue:
        db.execute("UPDATE execution_supervisor SET status='BLOCKED' WHERE id=1")
        engine._halt(db, issue, now)
    engine.journal.event(db, now, "POSITION_SUPERVISED", result)
    return result


@exact
def tighten(engine, price, quote, *, now):
    assess(engine, quote, now=now)
    with engine.journal.write() as db:
        p = position(engine, db)
        guard = protection(engine, db)
        if p is None or guard.issue or guard.exit_reason:
            raise ExecutionBlocked("STOCK_TIGHTENING_UNAVAILABLE")
        updated = type(guard).model_validate({**guard.model_dump(), "invalidation": price})
        if not guard.invalidation <= updated.invalidation < quote.bid:
            raise ExecutionBlocked("STOCK_INVALIDATION_CANNOT_WIDEN_OR_CROSS")
        db.execute(
            "UPDATE execution_mixed_control SET protection_json=? WHERE id=1",
            (updated.model_dump_json(),),
        )
        engine.journal.event(
            db,
            clock(now),
            "STOCK_INVALIDATION_TIGHTENED",
            {"price": str(updated.invalidation)},
            p.entry.client_id,
        )


async def tick(engine, quote, *, now):
    enrolled(engine)
    now = clock(now)
    result = await engine.reconcile_fixture(now=now)
    if not result["reconciled"]:
        return result
    return await after_reconciliation(engine, quote, now=now)


async def after_reconciliation(engine, quote, *, now):
    """Continue one already completed common native snapshot without a second read."""
    enrolled(engine)
    result = assess(engine, quote, now=now)
    if result["status"] != "EXIT_REQUIRED":
        return result
    with engine.journal.write() as db:
        p = position(engine, db)
        active = db.execute("SELECT * FROM execution_stock_orders WHERE active_lock=1").fetchone()
        if active:
            intent = json.loads(active["intent_json"])
            approval = json.loads(active["approval_json"])
            requested = approval["inputs"]["close_quantity"]
            if (
                active["status"] == "PREPARED"
                and active["attempted_at"] is None
                and intent.get("closing_entry_client_id") == p.entry.client_id
                and requested is not None
                and Decimal(requested) < p.quantity
            ):
                db.execute(
                    "UPDATE execution_stock_orders SET status='REJECTED',active_lock=NULL WHERE client_id=?",
                    (active["client_id"],),
                )
                engine.journal.event(
                    db,
                    now,
                    "STOCK_PARTIAL_CLOSE_SUPERSEDED",
                    {"entry_client_id": p.entry.client_id},
                    active["client_id"],
                )
            else:
                return {"status": "EXIT_BLOCKED", "reason": "STOCK_ORDER_ALREADY_IN_FLIGHT"}
        if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
            return {"status": "EXIT_BLOCKED", "reason": "OPTION_ORDER_ALREADY_IN_FLIGHT"}
        rows = db.execute(
            "SELECT * FROM execution_stock_orders WHERE json_extract(intent_json,'$.closing_entry_client_id')=?",
            (p.entry.client_id,),
        ).fetchall()
        if any(
            r["attempted_at"] and r["status"] in {"CANCELED", "REJECTED", "EXPIRED"} for r in rows
        ):
            engine._halt(db, "STOCK_EXIT_REVIEW_REQUIRED", now)
            return {"status": "EXIT_REVIEW_REQUIRED", "reason": "STOCK_EXIT_REVIEW_REQUIRED"}
        filled = sum(
            (
                Decimal(json.loads(r["observation_json"])["filled_quantity"])
                for r in rows
                if r["observation_json"]
            ),
            Decimal(0),
        )
    prepared = engine.prepare_stock(
        f"stock-protection:{p.entry.client_id}:{filled}",
        StockProposal(
            action="CLOSE", instrument=p.instrument, thesis="Independent mandatory stock exit"
        ),
        quote,
        now=now,
        origin="PROTECTIVE",
    )
    if prepared["status"] != "PREPARED":
        return prepared
    return {
        "status": await engine.dispatch_stock(prepared["client_id"], quote, now=now),
        "client_id": prepared["client_id"],
        "exit_reason": result["exit_reason"],
    }
