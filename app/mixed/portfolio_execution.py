"""Native portfolio order operations, using the existing single owner and journal."""

import json
import time
from contextlib import nullcontext
from datetime import timedelta
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.governor import admit_stock
from app.mixed.models import StockProposal
from app.mixed.native_execution import session
from app.mixed.portfolio_accounting import PortfolioPolicy
from app.mixed.portfolio_store import control, history, reserve
from app.mixed.portfolio_store import intent as stored_intent
from app.mixed.portfolio_venue import PortfolioVenueSnapshot
from app.mixed.stock_models import StockIntent, StockQuote
from app.options.engine import clock, exact, fingerprint
from app.options.lifecycle import TERMINAL
from app.options.process import run_option_process


def policy(engine):
    p = engine.policy
    settings = p.mixed_owner.portfolio
    if settings is None or engine._closed:
        raise ExecutionBlocked("PORTFOLIO_OWNER_REQUIRED")
    return PortfolioPolicy(
        capital=p.capital,
        daily_loss_limit=p.daily_loss_limit,
        total_loss_limit=p.total_loss_limit,
        options=engine.limits,
        stocks=p.mixed_owner.stocks,
        max_plays=settings.max_plays,
        exposure_limit=settings.exposure_limit,
        index_exposure_limit=settings.index_exposure_limit,
    )


def fresh(engine, db, p, now):
    c = engine._control(db)
    row = control(engine, db, p)
    if not row["snapshot_json"]:
        raise ExecutionBlocked("PORTFOLIO_RECONCILIATION_REQUIRED")
    snap = PortfolioVenueSnapshot.model_validate_json(row["snapshot_json"])
    if not timedelta(0) <= now - snap.captured_at < timedelta(
        seconds=engine.limits.account_max_age_seconds
    ) or json.loads(c["issues_json"]):
        raise ExecutionBlocked("PORTFOLIO_ACCOUNT_STALE_OR_UNRECONCILED")
    return c, snap


def selection_account(engine, db, now):
    """Read-only shared budget summary. Candidates still require instrument-specific review."""
    from app.mixed.governor import _account

    p = policy(engine)
    c, snap = fresh(engine, db, p, now)
    h = history(engine, db, p, now)
    account = _account(h, reconstruct(h), True, bool(c["halted"]))
    return account.model_copy(
        update={"captured_at": snap.captured_at, "snapshot_id": snap.snapshot_id}
    )


@exact
def prepare_stock(
    engine,
    source_key,
    proposal,
    quote,
    *,
    now,
    play_id=None,
    close_quantity=None,
    origin="DETERMINISTIC",
    _db=None,
):
    now = clock(now)
    p = policy(engine)
    proposal = StockProposal.model_validate(proposal.model_dump())
    quote = StockQuote.model_validate(quote.model_dump()) if quote else None
    paid = engine.policy.mixed_owner.reasoning is not None
    if (
        origin not in {"DETERMINISTIC", "PROTECTIVE", "MODEL", "POSITION_MODEL"}
        or (proposal.action == "OPEN_LONG" and paid != (origin == "MODEL"))
        or (origin == "POSITION_MODEL" and proposal.action != "CLOSE")
    ):
        raise ExecutionBlocked("PORTFOLIO_BOUND_MODEL_RECEIPT_REQUIRED")
    if not isinstance(source_key, str) or not source_key.strip() or len(source_key) > 128:
        raise ValueError("Bounded source identity required")
    inputs = {
        "proposal": proposal.model_dump(mode="json"),
        "quote": quote.model_dump(mode="json") if quote else None,
        "play_id": play_id,
        "close_quantity": str(close_quantity) if close_quantity is not None else None,
        "origin": origin,
    }
    digest = fingerprint(inputs)
    with nullcontext(_db) if _db is not None else engine.journal.write() as db:
        engine._control(db)
        prior = db.execute(
            "SELECT * FROM execution_portfolio_decisions WHERE source_key=?", (source_key,)
        ).fetchone()
        if prior:
            if prior["fingerprint"] != digest:
                raise ExecutionBlocked("PORTFOLIO_SOURCE_CONFLICT")
            return json.loads(prior["result_json"])
        output = {"status": "REJECTED", "client_id": None}
        if control(engine, db, p)["snapshot_json"]:
            from app.mixed.portfolio_loss import refresh

            refresh(engine, db, p, now)
        db.execute("SAVEPOINT portfolio_admission")
        try:
            c, snap = fresh(engine, db, p, now)
            h = history(engine, db, p, now)
            held = reconstruct(h).ledger.positions.get(play_id)
            window = session(engine, proposal.instrument, now) if proposal.instrument else None
            review = admit_stock(
                proposal,
                quote,
                h,
                window,
                now=now,
                reconciled=True,
                entry_halted=bool(c["halted"]),
                play_id=play_id,
            )
            output["admission"] = review.model_dump(mode="json")
            if review.outcome == "HOLD":
                output["status"] = "HOLD"
            elif review.outcome != "APPROVED":
                output["reason"] = ";".join(review.reasons)
            else:
                buying = proposal.action == "OPEN_LONG"
                management_deadline = review.approval_expires_at
                if origin == "POSITION_MODEL":
                    from app.mixed.portfolio_management import close_guard

                    management_deadline = close_guard(
                        engine, db, source_key, play_id, quote, None, now
                    )
                quantity = review.quantity
                if close_quantity is not None:
                    from app.mixed.stock_models import _shares

                    quantity = _shares(close_quantity)
                    if (
                        buying
                        or quantity <= 0
                        or quantity > review.quantity
                        or quantity % p.stocks.share_step
                    ):
                        raise ValueError("Owned executable partial close quantity required")
                if not buying and held is not None and quantity < held.quantity:
                    from app.mixed.portfolio_protection import assess_stock

                    if assess_stock(engine, play_id, quote, now=now, _db=db)["status"] != "HEALTHY":
                        raise ExecutionBlocked("MANDATORY_EXIT_REQUIRES_REMAINDER")
                if buying:
                    from app.mixed.portfolio_loss import guard
                    from app.mixed.portfolio_protection import entry_guard

                    guard(engine, db, p, now, proposal.family)
                    entry_guard(engine, db, p, now)
                    from decimal import Decimal

                    from app.mixed.selection import guard_stock

                    ceiling = guard_stock(engine, db, source_key, proposal, quote, now)
                    if ceiling is not None and (
                        quantity > Decimal(ceiling["quantity"])
                        or review.limit_price > Decimal(ceiling["limit_price"])
                    ):
                        raise ExecutionBlocked("STOCK_ORIGINAL_SELECTION_CEILING_EXCEEDED")
                    if proposal.carry is not None:
                        from app.mixed.carry import review_entry

                        review_entry(
                            engine.policy.mixed_owner.stock_carry,
                            engine.calendar,
                            proposal,
                            now,
                            p.stocks.max_receive_lag_seconds,
                        )
                    elif proposal.exit_at > window.closes_at - timedelta(
                        minutes=engine.policy.exit_cutoff_minutes
                    ):
                        raise ExecutionBlocked("STOCK_CARRY_NOT_ENROLLED")
                    fields = {
                        "instrument": proposal.instrument,
                        "side": "BUY",
                        "quantity": quantity,
                        "limit_price": review.limit_price,
                        "approved_entry_debit": review.entry_debit,
                        "reserved_exit_fee": review.reserved_exit_fee,
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
                    if held is None or not hasattr(held, "entry"):
                        raise ValueError("Exact stock play required")
                    fields = held.entry.model_dump(exclude={"approval_hash"})
                    fields.update(
                        side="SELL",
                        quantity=quantity,
                        limit_price=review.limit_price,
                        approved_entry_debit=0,
                        reserved_exit_fee=0,
                        closing_entry_client_id=play_id,
                    )
                fields.update(
                    client_id="stock-" + uuid4().hex,
                    source_key=source_key,
                    prepared_at=now,
                    approval_expires_at=min(
                        review.approval_expires_at,
                        management_deadline,
                        snap.captured_at + timedelta(seconds=engine.limits.account_max_age_seconds),
                    ),
                    order_expires_at=min(window.closes_at, proposal.exit_at)
                    if buying
                    else window.closes_at,
                    account_revision=engine.journal.revision(db),
                    approval_hash="0" * 64,
                )
                i = StockIntent.model_validate(fields)
                approval = {
                    "inputs": inputs,
                    "history": h.model_dump(mode="json"),
                    "session": window.model_dump(mode="json"),
                    "admission": review.model_dump(mode="json"),
                    "intent_terms": i.model_dump(mode="json", exclude={"approval_hash"}),
                }
                i = i.model_copy(update={"approval_hash": fingerprint(approval)})
                reserve(engine, db, p, i, approval, now)
                output.update(
                    status="PREPARED",
                    client_id=i.client_id,
                    play_id=i.client_id if buying else play_id,
                )
        except (ValueError, ExecutionBlocked) as exc:
            db.execute("ROLLBACK TO portfolio_admission")
            output.update(status="REJECTED", client_id=None, reason=str(exc))
        finally:
            db.execute("RELEASE portfolio_admission")
        db.execute(
            "INSERT INTO execution_portfolio_decisions VALUES(?,?,?)",
            (source_key, digest, json.dumps(output, sort_keys=True)),
        )
        engine.journal.event(
            db, now, "PORTFOLIO_PROPOSAL_RECORDED", {"source_key": source_key, **output}
        )
        return output


@exact
def begin_stock(engine, client_id, quote, now):
    p = policy(engine)
    with engine.journal.write() as db:
        engine._control(db)
        row = db.execute(
            "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (client_id,)
        ).fetchone()
        if row is None or row["asset"] != "STOCK":
            raise ExecutionBlocked("UNKNOWN_STOCK_INTENT")
        if row["status"] != "PREPARED" or row["attempted_at"]:
            return row["status"]
        i = stored_intent(row)
        try:
            c, _ = fresh(engine, db, p, now)
            if not i.prepared_at <= now < i.approval_expires_at:
                raise ExecutionBlocked("ORIGINAL_APPROVAL_EXPIRED")
            if i.side == "BUY":
                from app.mixed.portfolio_loss import guard
                from app.mixed.portfolio_protection import entry_guard

                guard(engine, db, p, now, i.family)
                entry_guard(engine, db, p, now)
            a = json.loads(row["approval_json"])
            if fingerprint({k: v for k, v in a.items() if k != "intent_hash"}) != i.approval_hash:
                raise ValueError("Original stock approval changed")
            proposal = StockProposal.model_validate(a["inputs"]["proposal"])
            if a["inputs"]["origin"] == "POSITION_MODEL":
                from app.mixed.portfolio_management import close_guard

                close_guard(
                    engine,
                    db,
                    i.source_key,
                    i.closing_entry_client_id,
                    quote,
                    None,
                    now,
                    exclude=i.client_id,
                )
            if i.side == "BUY":
                from app.mixed.selection import guard_stock

                guard_stock(engine, db, i.source_key, proposal, quote, now)
            h = history(engine, db, p, now, exclude=i.client_id)
            if i.side == "SELL":
                held = reconstruct(h).ledger.positions.get(i.closing_entry_client_id)
                if held is not None and i.quantity < held.quantity:
                    from app.mixed.portfolio_protection import assess_stock

                    if (
                        assess_stock(engine, i.closing_entry_client_id, quote, now=now, _db=db)[
                            "status"
                        ]
                        != "HEALTHY"
                    ):
                        raise ExecutionBlocked("MANDATORY_EXIT_REQUIRES_REMAINDER")
            result = admit_stock(
                proposal,
                quote,
                h,
                session(engine, i.instrument, now),
                now=now,
                reconciled=True,
                entry_halted=bool(c["halted"]),
                play_id=row["play_id"] if i.side == "SELL" else None,
            )
            if (
                result.outcome != "APPROVED"
                or result.quantity < i.quantity
                or (
                    result.limit_price > i.limit_price
                    if i.side == "BUY"
                    else result.limit_price < i.limit_price
                )
            ):
                raise ExecutionBlocked("FRESH_PORTFOLIO_ADMISSION_REQUIRED")
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
            {"play_id": row["play_id"], "quote": quote.model_dump(mode="json")},
            client_id,
        )
        return i


async def dispatch_stock(engine, client_id, quote, *, now):
    started = time.monotonic()
    now = clock(now)
    quote = StockQuote.model_validate(quote.model_dump())
    i = begin_stock(engine, client_id, quote, now)
    if not isinstance(i, StockIntent):
        return i
    return await submit(engine, i, now, started)


async def submit(engine, i, now, started):
    client_id = i.client_id
    arguments = {"stock_intent" if isinstance(i, StockIntent) else "intent": i}
    try:
        result = await run_option_process(
            engine.venue,
            now=now,
            timeout_seconds=engine.policy.process_timeout_seconds,
            deadline=started
            + min(
                engine.policy.process_timeout_seconds, (i.approval_expires_at - now).total_seconds()
            ),
            **arguments,
        )
        with engine.journal.write() as db:
            engine._control(db)
            row = db.execute(
                "SELECT status FROM execution_portfolio_orders WHERE client_id=?", (client_id,)
            ).fetchone()
            if row[0] != "SUBMITTING":
                raise ExecutionBlocked("PORTFOLIO_ATTEMPT_CHANGED")
            db.execute(
                "UPDATE execution_portfolio_orders SET status='OPEN',order_id=? WHERE client_id=?",
                (result.order_id, client_id),
            )
            engine.journal.event(
                db,
                now,
                "PORTFOLIO_ACKNOWLEDGED",
                {"order_id": result.order_id, "play_id": i.closing_entry_client_id or i.client_id},
                client_id,
            )
        return "OPEN"
    except BaseException as exc:
        with engine.journal.write() as db:
            db.execute(
                "UPDATE execution_portfolio_orders SET status='UNKNOWN' WHERE client_id=? AND status='SUBMITTING'",
                (client_id,),
            )
            engine._halt(db, "UNCERTAIN_PORTFOLIO_ATTEMPT", now)
            engine.journal.event(
                db, now, "ATTEMPT_UNCERTAIN", {"error_class": type(exc).__name__}, client_id
            )
        if not isinstance(exc, Exception):
            raise
        return "UNKNOWN"


@exact
def reconcile(engine, snapshot, *, now, epoch=None):
    from app.mixed.portfolio_store import control
    from app.mixed.portfolio_venue import PortfolioVenueSnapshot

    now = clock(now)
    p = policy(engine)
    try:
        snap = PortfolioVenueSnapshot.model_validate(snapshot.model_dump())
    except ValueError:
        raise ExecutionBlocked("EXPLICIT_PORTFOLIO_SNAPSHOT_REQUIRED") from None
    with engine.journal.write() as db:
        engine._control(db)
        c = control(engine, db, p)
        if engine._mixed_submitting(db):
            return {"reconciled": False, "issues": ["PORTFOLIO_SUBMISSION_IN_PROGRESS"]}
        if epoch is not None and engine._epoch(db) != epoch:
            engine.journal.event(db, now, "PORTFOLIO_READ_SUPERSEDED", {})
            return {"reconciled": False, "issues": ["PORTFOLIO_READ_SUPERSEDED"]}
        db.execute("SAVEPOINT portfolio_reconciliation")
        try:
            if (
                (snap.venue_id, snap.account_id, snap.population_id, snap.portfolio_policy)
                != (engine.venue.venue_id, engine.limits.account_id, engine.limits.population_id, p)
                or not snap.complete
                or snap.underlying_exposures
            ):
                raise ValueError("PORTFOLIO_SNAPSHOT_BINDING")
            if (
                not timedelta(0)
                <= now - snap.captured_at
                < timedelta(seconds=engine.limits.account_max_age_seconds)
            ):
                raise ValueError("PORTFOLIO_SNAPSHOT_STALE")
            old = (
                PortfolioVenueSnapshot.model_validate_json(c["snapshot_json"])
                if c["snapshot_json"]
                else None
            )
            if old:
                if (
                    snap.captured_at < old.captured_at
                    or snap.receipts[: len(old.receipts)] != old.receipts
                ):
                    raise ValueError("PORTFOLIO_SNAPSHOT_PREFIX_CHANGED")
                new_orders = {o.client_id: o for o in (*snap.orders, *snap.stock_orders)}
                for prior in (*old.orders, *old.stock_orders):
                    current = new_orders.get(prior.client_id)
                    if (
                        current is None
                        or current.updated_at < prior.updated_at
                        or current.fills[: len(prior.fills)] != prior.fills
                        or (prior.status in TERMINAL and current != prior)
                    ):
                        raise ValueError("PORTFOLIO_ORDER_PREFIX_CHANGED")
                if any(snap.settlement_plays.get(k) != v for k, v in old.settlement_plays.items()):
                    raise ValueError("PORTFOLIO_SETTLEMENT_PLAY_CHANGED")
            retained = db.execute(
                "SELECT payload FROM execution_snapshots WHERE snapshot_id=?", (snap.snapshot_id,)
            ).fetchone()
            if retained and PortfolioVenueSnapshot.model_validate_json(retained[0]) != snap:
                raise ValueError("PORTFOLIO_SNAPSHOT_IDENTITY_CHANGED")
            h = history(engine, db, p, now, snapshot=snap)
            result = reconstruct(h)
            if (result.ledger.cash, result.ledger.settled_cash, result.ledger.positions) != (
                snap.cash,
                snap.settled_cash,
                snap.positions,
            ):
                raise ValueError("PORTFOLIO_ACCOUNTING_MISMATCH")
            for order in (*snap.orders, *snap.stock_orders):
                row = db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (order.client_id,)
                ).fetchone()
                i = stored_intent(row)
                if row["status"] in TERMINAL and row["observation_json"] is None:
                    raise ValueError("PORTFOLIO_UNSUBMITTED_TERMINAL_OBSERVED")
                db.execute(
                    "UPDATE execution_portfolio_orders SET status=?,order_id=?,observation_json=?,active_play=? WHERE client_id=?",
                    (
                        order.status,
                        order.order_id,
                        order.model_dump_json(),
                        None if order.status in TERMINAL else row["play_id"],
                        i.client_id,
                    ),
                )
            db.execute(
                "UPDATE execution_portfolio_control SET snapshot_json=? WHERE id=1",
                (snap.model_dump_json(),),
            )
            db.execute(
                "INSERT OR IGNORE INTO execution_snapshots VALUES(?,?)",
                (snap.snapshot_id, snap.model_dump_json()),
            )
            db.execute("UPDATE execution_control SET issues_json='[]' WHERE id=1")
            from app.options.scope_execution import sync

            sync(engine, db, now)
            engine.journal.event(
                db,
                now,
                "PORTFOLIO_RECONCILED",
                {"snapshot_id": snap.snapshot_id, "play_ids": list(result.ledger.positions)},
            )
            db.execute("RELEASE portfolio_reconciliation")
            return {
                "reconciled": True,
                "positions": len(result.ledger.positions),
                "snapshot_id": snap.snapshot_id,
            }
        except (ValueError, ExecutionBlocked) as exc:
            db.execute("ROLLBACK TO portfolio_reconciliation")
            db.execute("RELEASE portfolio_reconciliation")
            engine._halt(db, "PORTFOLIO_RECONCILIATION_BLOCKED", now)
            db.execute(
                "UPDATE execution_control SET issues_json=? WHERE id=1", (json.dumps([str(exc)]),)
            )
            engine.journal.event(db, now, "RECONCILIATION_BLOCKED", {"reason": str(exc)})
            return {"reconciled": False, "issues": [str(exc)]}
