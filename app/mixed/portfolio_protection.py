"""Independently bound stock supervision in the native portfolio journal."""

import json
from contextlib import nullcontext
from datetime import timedelta

from app.options.models import paper_market_evidence
from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.native_execution import session
from app.mixed.native_models import StockProtection
from app.mixed.portfolio_execution import fresh, policy
from app.mixed.portfolio_store import control, history
from app.mixed.stock_models import StockPosition, StockQuote
from app.options.engine import clock, exact
from app.options.governor import _fresh


@exact
def assess_stock(engine, play_id, quote, *, now, _db=None):
    now = clock(now)
    p = policy(engine)
    quote = StockQuote.model_validate(quote.model_dump()) if quote is not None else None
    with nullcontext(_db) if _db is not None else engine.journal.write() as db:
        fresh(engine, db, p, now)
        c = control(engine, db, p)
        projection = reconstruct(history(engine, db, p, now))
        held = projection.ledger.positions.get(play_id)
        if not isinstance(held, StockPosition):
            raise ExecutionBlocked("EXACT_HELD_STOCK_PLAY_REQUIRED")
        guards = json.loads(c["protection_json"])
        saved = guards.get(play_id)
        guard = (
            StockProtection.model_validate(saved["guard"])
            if saved
            else StockProtection(
                entry_client_id=play_id, invalidation=held.entry.original_invalidation
            )
        )
        if (
            guard.entry_client_id != play_id
            or guard.invalidation < held.entry.original_invalidation
        ):
            raise ValueError("Portfolio original stock protection changed")
        window = session(engine, held.instrument, now)
        deadline = held.entry.exit_at
        if window and held.entry.carry is None:
            deadline = min(
                deadline, window.closes_at - timedelta(minutes=engine.policy.exit_cutoff_minutes)
            )
        reason = guard.exit_reason
        if now >= deadline or (window is None and held.entry.carry is None):
            reason = reason or "STOCK_TIME_EXIT"
        if held.entry.carry is not None:
            from app.mixed.carry import verify_terms

            verify_terms(
                engine.policy.mixed_owner.stock_carry,
                engine.calendar,
                held.entry.carry,
                source_hash=held.entry.source_hash,
                symbol=held.instrument.symbol,
                exit_at=deadline,
            )
        issue = None
        if window is None:
            issue = "STOCK_MARKET_CLOSED"
        elif (
            quote is None
            or quote.instrument != held.instrument
            or quote.source != p.stocks.quote_source
            or not quote.complete
            or not paper_market_evidence(quote)
            or not _fresh(
                quote.source_at,
                quote.received_at,
                now,
                p.stocks.quote_max_age_seconds,
                p.stocks.max_receive_lag_seconds,
            )
        ):
            issue = "STOCK_SUPERVISION_QUOTE_REQUIRED"
        else:
            if quote.bid <= guard.invalidation:
                reason = reason or "STOCK_INVALIDATION"
            if quote.bid >= held.entry.original_target:
                reason = reason or "STOCK_TARGET"
        guard = guard.model_copy(
            update={
                "exit_reason": reason,
                "exit_required_at": guard.exit_required_at or (now if reason else None),
                "issue": issue,
            }
        )
        guards[play_id] = {
            "guard": guard.model_dump(mode="json"),
            "assessed_at": now.isoformat(),
            "quote": quote.model_dump(mode="json") if quote else None,
        }
        db.execute(
            "UPDATE execution_portfolio_control SET protection_json=? WHERE id=1",
            (json.dumps(guards, sort_keys=True),),
        )
        result = {
            "play_id": play_id,
            "status": "BLOCKED" if issue else "EXIT_REQUIRED" if reason else "HEALTHY",
            "issue": issue,
            "exit_reason": reason,
        }
        engine.journal.event(
            db, now, "POSITION_SUPERVISED", {**result, "protection": guards[play_id]}, play_id
        )
        return result


def entry_guard(engine, db, p, now):
    """Every held play must have completed fresh protection before optional risk."""
    from datetime import datetime

    h = history(engine, db, p, now)
    projection = reconstruct(h)
    guards = json.loads(control(engine, db, p)["protection_json"])
    for play_id in projection.ledger.positions:
        saved = guards.get(play_id)
        if saved is None or not timedelta(0) <= now - datetime.fromisoformat(
            saved["assessed_at"]
        ) < timedelta(seconds=engine.policy.supervisor_max_age_seconds):
            raise ExecutionBlocked("PORTFOLIO_PROTECTION_REQUIRED:" + play_id)
        if saved["guard"].get("issue") or saved["guard"].get("exit_reason"):
            raise ExecutionBlocked("PORTFOLIO_PROTECTION_PENDING:" + play_id)


@exact
def tighten(engine, play_id, price, quote, underlying, *, now, stock=False, _db=None):
    """One exact owned stop; fresh protection and monotonic stops in the same transaction."""
    from decimal import Decimal

    from app.options.lifecycle import OptionPosition

    now = clock(now)
    price = Decimal(price)
    if not price.is_finite() or price <= 0:
        raise ValueError("Finite positive invalidation required")
    with nullcontext(_db) if _db is not None else engine.journal.write() as db:
        engine._control(db)
        result = (
            assess_stock(engine, play_id, quote, now=now, _db=db)
            if stock
            else assess_option(engine, play_id, quote, underlying, now=now, _db=db)
        )
        if result["status"] != "HEALTHY":
            raise ExecutionBlocked("PORTFOLIO_TIGHTENING_UNAVAILABLE")
        guards = json.loads(control(engine, db, engine.portfolio_policy)["protection_json"])
        saved = guards[play_id]
        if stock:
            guard = StockProtection.model_validate(saved["guard"])
            if not guard.invalidation <= price < quote.bid:
                raise ExecutionBlocked("STOCK_INVALIDATION_CANNOT_WIDEN_OR_CROSS")
            saved["guard"] = guard.model_copy(update={"invalidation": price}).model_dump(
                mode="json"
            )
        else:
            held = OptionPosition.model_validate(saved["position"])
            old = held.tightened_underlying_invalidation
            if (held.contract.right == "CALL" and not old <= price < underlying.bid) or (
                held.contract.right == "PUT" and not underlying.ask < price <= old
            ):
                raise ExecutionBlocked("OPTION_INVALIDATION_CANNOT_WIDEN_OR_CROSS")
            saved["position"] = held.model_copy(
                update={"tightened_underlying_invalidation": price}
            ).model_dump(mode="json")
        db.execute(
            "UPDATE execution_portfolio_control SET protection_json=? WHERE id=1",
            (json.dumps(guards, sort_keys=True),),
        )
        engine.journal.event(
            db,
            now,
            "PORTFOLIO_INVALIDATION_TIGHTENED",
            {"play_id": play_id, "price": str(price), "protection": saved},
            play_id,
        )
        return {"status": "TIGHTENED", "play_id": play_id, "price": str(price)}


async def tick(engine, *, now, stock_quotes=(), option_quotes=(), underlyings=()):
    """Visit every held play even when another instrument cannot be managed."""
    from decimal import Decimal

    from app.mixed.models import StockProposal
    from app.mixed.portfolio_store import intent as stored_intent
    from app.options.models import OptionProposal, OptionQuote, UnderlyingQuote

    now = clock(now)
    p = policy(engine)
    quotes = {
        q.instrument.instrument_id: StockQuote.model_validate(q.model_dump()) for q in stock_quotes
    }
    options = {
        q.instrument.contract.contract_id: OptionQuote.model_validate(q.model_dump())
        for q in option_quotes
    }
    underlying_quotes = {
        q.symbol: UnderlyingQuote.model_validate(q.model_dump()) for q in underlyings
    }
    if (
        len(quotes) != len(stock_quotes)
        or len(options) != len(option_quotes)
        or len(underlying_quotes) != len(underlyings)
    ):
        raise ValueError("Unique portfolio quotes required")
    reconciliation = await engine.reconcile_fixture(now=now)
    if not reconciliation["reconciled"]:
        return reconciliation
    with engine.journal.read() as db:
        held = reconstruct(history(engine, db, p, now)).ledger.positions
    results = {}
    for identity, position in held.items():
        stock = isinstance(position, StockPosition)
        quote = (
            quotes.get(position.instrument.instrument_id)
            if stock
            else options.get(position.contract.contract_id)
        )
        underlying = None if stock else underlying_quotes.get(position.contract.underlying)
        try:
            result = (
                assess_stock(engine, identity, quote, now=now)
                if stock
                else assess_option(engine, identity, quote, underlying, now=now)
            )
            results[identity] = result
            if not stock and result["status"] == "HEALTHY" and result["target_exit_stage"]:
                from app.mixed.portfolio_targets import tick as target_tick

                results[identity] = await target_tick(
                    engine, identity, quote, underlying, now, result
                )
                continue
            if result["status"] != "EXIT_REQUIRED":
                continue
            with engine.journal.write() as db:
                engine._control(db)
                active = db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE active_play=?", (identity,)
                ).fetchone()
                if active:
                    i = stored_intent(active)
                    if (
                        active["status"] == "PREPARED"
                        and active["attempted_at"] is None
                        and i.side == "SELL"
                        and i.quantity < position.quantity
                    ):
                        db.execute(
                            "UPDATE execution_portfolio_orders SET status='REJECTED',active_play=NULL WHERE client_id=?",
                            (i.client_id,),
                        )
                        engine.journal.event(
                            db,
                            now,
                            "PORTFOLIO_PARTIAL_CLOSE_SUPERSEDED",
                            {"play_id": identity},
                            i.client_id,
                        )
                    else:
                        results[identity] = {
                            "status": "EXIT_BLOCKED",
                            "reason": "PLAY_ORDER_UNRESOLVED",
                        }
                        continue
                rows = db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE play_id=? AND json_extract(intent_json,'$.side')='SELL'",
                    (identity,),
                ).fetchall()
                if any(
                    r["attempted_at"] and r["status"] in {"CANCELED", "REJECTED", "EXPIRED"}
                    for r in rows
                ):
                    results[identity] = {
                        "status": "EXIT_REVIEW_REQUIRED",
                        "reason": "PLAY_EXIT_REVIEW_REQUIRED",
                    }
                    continue
                filled = sum(
                    (
                        Decimal(json.loads(r["observation_json"])["filled_quantity"])
                        for r in rows
                        if r["observation_json"]
                    ),
                    Decimal(0),
                )
            source = (
                ("stock-protection:" if stock else "option-protection:")
                + identity
                + ":"
                + str(filled)
            )
            if stock:
                prepared = engine.prepare_stock(
                    source,
                    StockProposal(
                        action="CLOSE",
                        instrument=position.instrument,
                        thesis="Independent mandatory stock exit",
                    ),
                    quote,
                    now=now,
                    origin="PROTECTIVE",
                    play_id=identity,
                )
            else:
                prepared = engine.prepare(
                    source,
                    OptionProposal(
                        action="CLOSE",
                        contract=position.contract,
                        thesis="Independent mandatory option exit",
                    ),
                    quote,
                    underlying,
                    now=now,
                    origin="PROTECTIVE",
                    play_id=identity,
                )
            if prepared["status"] != "PREPARED":
                results[identity] = prepared
                continue
            results[identity] = {
                **result,
                "status": await engine.dispatch_stock(prepared["client_id"], quote, now=now)
                if stock
                else await engine.dispatch(prepared["client_id"], quote, underlying, now=now),
                "client_id": prepared["client_id"],
            }
        except (ValueError, ExecutionBlocked) as exc:
            results[identity] = {"status": "BLOCKED", "reason": str(exc)}
    result = {"reconciled": True, "plays": results}
    with engine.journal.write() as db:
        engine._control(db)
        db.execute(
            "INSERT INTO execution_supervisor VALUES(1,?,'HEALTHY',NULL,1,?,?,NULL,NULL) ON CONFLICT(id) DO UPDATE SET status=excluded.status,heartbeat_at=excluded.heartbeat_at,result_json=excluded.result_json",
            (engine.policy.model_dump_json(), now.isoformat(), json.dumps(result, sort_keys=True)),
        )
        if any(
            r.get("status") in {"BLOCKED", "EXIT_BLOCKED", "EXIT_REVIEW_REQUIRED", "UNKNOWN"}
            for r in results.values()
        ):
            db.execute("UPDATE execution_supervisor SET status='BLOCKED' WHERE id=1")
    return result


@exact
def assess_option(engine, play_id, quote, underlying, *, now, _db=None):
    from app.options.lifecycle import OptionPosition
    from app.options.models import OptionQuote, UnderlyingQuote
    from app.options.protection import assess_position

    now = clock(now)
    p = policy(engine)
    quote = OptionQuote.model_validate(quote.model_dump()) if quote is not None else None
    underlying = (
        UnderlyingQuote.model_validate(underlying.model_dump()) if underlying is not None else None
    )
    with nullcontext(_db) if _db is not None else engine.journal.write() as db:
        fresh(engine, db, p, now)
        c = control(engine, db, p)
        held = reconstruct(history(engine, db, p, now)).ledger.positions.get(play_id)
        if not isinstance(held, OptionPosition):
            raise ExecutionBlocked("EXACT_HELD_OPTION_PLAY_REQUIRED")
        guards = json.loads(c["protection_json"])
        saved = guards.get(play_id)
        if saved is not None:
            old = OptionPosition.model_validate(saved["position"])
            if (
                old.entry_client_id != play_id
                or old.contract != held.contract
                or old.original_underlying_invalidation != held.original_underlying_invalidation
                or old.target_exit_schedule != held.target_exit_schedule
                or old.exit_at != held.exit_at
                or old.entry_protection != held.entry_protection
                or old.entry_time_protection != held.entry_time_protection
                or old.entry_premium_protection != held.entry_premium_protection
            ):
                raise ValueError("Portfolio option protection identity changed")
            trail = held.premium_trail
            if (trail is None) != (old.premium_trail is None):
                raise ValueError("Portfolio original trail changed")
            if trail is not None:
                if old.premium_trail.entry_quantity != trail.entry_quantity or (
                    old.premium_trail.entry_basis is not None
                    and old.premium_trail.entry_basis != trail.entry_basis
                ):
                    raise ValueError("Portfolio trail basis changed")
                trail = trail.model_copy(update={"peak_bid": old.premium_trail.peak_bid})
            if (held.trade_floor is None) != (old.trade_floor is None):
                raise ValueError("Portfolio original trade floor changed")
            held = held.model_copy(
                update={
                    "premium_trail": trail,
                    "trade_floor": old.trade_floor,
                    **{
                        k: getattr(old, k)
                        for k in (
                            "exit_reason",
                            "exit_required_at",
                            "tightened_underlying_invalidation",
                            "target_exit_stage",
                        )
                    },
                }
            )
        from app.mixed.portfolio_targets import refresh_floor

        held = refresh_floor(engine, db, held, now)
        executable = quote if quote is not None and quote.bid_size is not None else None
        updated = assess_position(
            held, executable, underlying, engine.limits, engine.policy, now=now
        )
        if updated.target_exit_stage != held.target_exit_stage:
            updated = refresh_floor(engine, db, updated, now)
            updated = assess_position(
                updated, executable, underlying, engine.limits, engine.policy, now=now
            )
        from app.options.progress_health import record

        progress = record(engine, db, updated, executable, underlying, now)
        if engine.policy.health_management is not None:
            from app.options.health_management import assess

            updated = assess(engine, db, updated, executable, underlying, progress, now)
        guards[play_id] = {
            "guard": {
                "entry_client_id": play_id,
                "issue": updated.supervision_issue,
                "exit_reason": updated.exit_reason,
            },
            "position": updated.model_dump(mode="json"),
            "assessed_at": now.isoformat(),
            "quote": quote.model_dump(mode="json") if quote else None,
            "underlying": underlying.model_dump(mode="json") if underlying else None,
        }
        db.execute(
            "UPDATE execution_portfolio_control SET protection_json=? WHERE id=1",
            (json.dumps(guards, sort_keys=True),),
        )
        result = {
            "play_id": play_id,
            "status": "BLOCKED"
            if updated.supervision_issue
            else "EXIT_REQUIRED"
            if updated.exit_reason
            else "HEALTHY",
            "issue": updated.supervision_issue,
            "exit_reason": updated.exit_reason,
            "target_exit_stage": updated.target_exit_stage,
        }
        engine.journal.event(
            db, now, "POSITION_SUPERVISED", {**result, "protection": guards[play_id]}, play_id
        )
        return result
