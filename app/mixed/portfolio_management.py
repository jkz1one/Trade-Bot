"""One optional management call per completed slot, with exact-play native consumption."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.governor import _account
from app.mixed.native_models import StockProtection
from app.mixed.portfolio_execution import fresh
from app.mixed.portfolio_position import PortfolioPositionPacket, review
from app.mixed.portfolio_store import control, history, intent
from app.mixed.stock_models import StockIntent
from app.options.engine import fingerprint
from app.options.lifecycle import OptionPosition


def current(engine, db, identity, now, *, exclude=None):
    c, snapshot = fresh(engine, db, engine.portfolio_policy, now)
    h = history(engine, db, engine.portfolio_policy, now, exclude=exclude)
    projected = reconstruct(h)
    p = projected.ledger.positions.get(identity)
    if p is None:
        raise ExecutionBlocked("EXACT_HELD_MANAGEMENT_PLAY_REQUIRED")
    saved = json.loads(control(engine, db, engine.portfolio_policy)["protection_json"]).get(
        identity
    )
    if not saved:
        raise ExecutionBlocked("EXACT_PLAY_PROTECTION_REQUIRED")
    guard = (
        StockProtection.model_validate(saved["guard"])
        if hasattr(p, "entry")
        else OptionPosition.model_validate(saved["position"])
    )
    account = _account(h, projected, True, bool(c["halted"]), play_id=identity)
    account = account.model_copy(
        update={
            "captured_at": snapshot.captured_at,
            "snapshot_id": snapshot.snapshot_id,
            "entry_blockers": tuple(r for r in account.entry_blockers if r != "PLAY_CAPACITY"),
        }
    )
    return h, p, guard, account


def original_decision(db, entry):
    key = entry.source_key
    native = db.execute(
        "SELECT approval_json FROM execution_portfolio_orders WHERE client_id=?", (entry.client_id,)
    ).fetchone()
    if native:
        key = (json.loads(native[0])["inputs"].get("scope_arbitration") or {}).get("cycle_key", key)
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
        (key,),
    ).fetchone()
    evidence = json.loads(row[0] or "{}") if row else {}
    return evidence.get("entry_result", {}).get("plan")


def original_context(db, entry):
    if getattr(entry, "entry_lineage", None) and entry.entry_lineage.family == "SCOPE":
        from app.options.scope_execution import stored_entry

        return stored_entry(db, entry.source_key)["packet"]
    from app.options.swing_execution import selected_scan

    scan = selected_scan(db, entry.source_key)
    if scan is not None:
        return scan.model_dump(mode="json")
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
        (entry.source_key,),
    ).fetchone()
    evidence = json.loads(row[0] or "{}") if row else {}
    if isinstance(entry, StockIntent):
        values = evidence.get("entry_request", {}).get("packet", {}).get("stocks", [])
        return next(
            (v for v in values if v["candidate"]["proposal"]["source_hash"] == entry.source_hash),
            None,
        )
    return (
        {"candidate_id": entry.entry_lineage.candidate_id, "scans": evidence.get("scans", [])}
        if entry.entry_lineage
        else None
    )


def stored(db, key, *, usable=False):
    """Full receipt validation without projection recursion; costs remain readable while pending."""
    from app.options import position_judgment as j

    row = db.execute(
        "SELECT * FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    if row is None or row["result_json"] is None:
        raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_RECEIPT_REQUIRED")
    evidence = json.loads(row["result_json"])
    request = j.PositionRequest.model_validate(evidence["position_request"])
    packet = request.packet
    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    entryrow = db.execute(
        "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (packet.play_id,)
    ).fetchone()
    if (
        not isinstance(packet, PortfolioPositionPacket)
        or key != "manage:" + str(int(packet.as_of.timestamp()) // 300)
        or config.get("position_model") != request.configuration.model_dump(mode="json")
        or entryrow is None
        or intent(entryrow) != packet.entry
        or packet.original_decision != original_decision(db, packet.entry)
        or packet.original_context != original_context(db, packet.entry)
    ):
        raise ExecutionBlocked("PORTFOLIO_ORIGINAL_MANAGEMENT_CHANGED")
    from app.options.coordinator import DegenFrame

    frame = DegenFrame.model_validate_json(row["inputs_json"])
    if fingerprint(frame) != row["fingerprint"] or frame.portfolio_version != "portfolio-frame-v2":
        raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_FRAME_CHANGED")
    if scan_for(db, packet.entry, frame, packet.as_of) != packet.scan:
        raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_CONTEXT_CHANGED")
    quotes, underlyings = frame_quotes(frame)
    if quotes.get(packet.entry.instrument.instrument_id) != packet.quote or (
        packet.underlying is not None
        and underlyings.get(packet.underlying.symbol) != packet.underlying
    ):
        raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_QUOTE_CHANGED")
    call = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    result = (
        j.PositionResult.model_validate(evidence["position_result"])
        if "position_result" in evidence
        else None
    )
    if call is not None:
        if call["packet_hash"] != fingerprint(j.request_content(request)):
            raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_ATTEMPT_CHANGED")
        if call["cost"] is not None:
            if result is None or result.usage is None:
                raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_COST_EVIDENCE_REQUIRED")
            cost = (
                result.usage.input_tokens * request.configuration.costs.input_per_million
                + result.usage.output_tokens * request.configuration.costs.output_per_million
            ) / Decimal(1000000)
            if (
                call["usage_json"] != result.usage.model_dump_json()
                or call["decision_hash"] != fingerprint(result.plan)
                or call["request_id"] != result.usage.request_id
                or Decimal(call["cost"]) != cost
                or result.request_id != request.request_id
                or result.packet_hash != fingerprint(packet)
                or result.configuration_hash != fingerprint(request.configuration)
                or result.plan.entry_client_id != packet.play_id
                or result.plan.position_revision != packet.position_revision
            ):
                raise ExecutionBlocked("PORTFOLIO_SETTLED_MANAGEMENT_RECEIPT_CHANGED")
    if usable:
        if (
            call is None
            or call["cost"] is None
            or result is None
            or result.error is not None
            or evidence.get("position_timely") is not True
            or not packet.as_of
            <= datetime.fromisoformat(evidence["position_completed_at"])
            < packet.valid_until
        ):
            raise ExecutionBlocked("PORTFOLIO_USABLE_MANAGEMENT_REQUIRED")
        j.validate_result(request, result)
    return request, result, call, evidence


def frame_quotes(frame):
    from app.mixed.quote_fills import _unique
    from app.options.scope_runtime import protection

    qs, us = protection(frame)
    quotes = _unique(
        (*qs, *(s.quote for s in (*frame.stocks, *frame.held_stocks))),
        lambda q: q.instrument.instrument_id,
    )
    return quotes, _unique(us, lambda u: u.symbol)


def scan_for(db, entry, frame, now):
    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    if getattr(entry, "entry_lineage", None) and entry.entry_lineage.family == "SCOPE":
        from app.options.scope_context import ScopeContextPolicy, scan_scope_context
        from app.options.scope_execution import stored_entry

        receipt = stored_entry(db, entry.source_key)
        if (
            frame.scope is None
            or receipt is None
            or frame.scope.play_key != receipt["packet"]["binding"]["play_key"]
        ):
            raise ExecutionBlocked("EXACT_HELD_SCOPE_CONTEXT_REQUIRED")
        return scan_scope_context(
            frame.scope.frame,
            frame.scope.context,
            ScopeContextPolicy.model_validate(config["scope"]["watch"]["context"]),
            now=now,
        )
    from app.options.degen import DegenPolicy, scan_degen
    from app.robinhood.schedule import XNYSCalendar

    symbol = (
        entry.instrument.symbol
        if isinstance(entry, StockIntent)
        else entry.instrument.contract.underlying
    )
    histories = [h for h in frame.histories if h.symbol == symbol]
    if len(histories) != 1:
        raise ExecutionBlocked("HELD_COMPLETED_HISTORY_REQUIRED")
    return scan_degen(
        histories[0],
        DegenPolicy.model_validate(config["setup"]),
        XNYSCalendar().current_window(now),
        now=now,
    )


def validate_admission(engine, db, key, request, input_hash, now):
    from app.options import position_judgment as j

    saved, _, call, _ = stored(db, key)
    p = request.packet
    _, position, guard, account = current(engine, db, p.play_id, now)
    if (
        saved != request
        or call is not None
        or input_hash != fingerprint(j.request_content(request))
        or p.position_revision != engine.journal.revision(db)
        or account != p.account
        or review(
            p,
            j.maintain(p),
            position=position,
            protection=guard,
            account=account,
            quote=p.quote,
            underlying=p.underlying,
            now=now,
        ).outcome
        != "MAINTAIN"
    ):
        raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_ADMISSION_CHANGED")


def close_guard(engine, db, key, identity, quote, underlying, now, *, exclude=None):
    request, result, _, _ = stored(db, key, usable=True)
    if request.packet.play_id != identity or result.plan.action != "EXIT_ALL":
        raise ExecutionBlocked("PORTFOLIO_EXACT_MODEL_EXIT_REQUIRED")
    _, position, guard, account = current(engine, db, identity, now, exclude=exclude)
    checked = review(
        request.packet,
        result.plan,
        position=position,
        protection=guard,
        account=account,
        quote=quote,
        underlying=underlying,
        now=now,
    )
    if checked.outcome != "ELIGIBLE":
        raise ExecutionBlocked(";".join(checked.reasons))
    return request.packet.valid_until


def apply(c, key, request, result, quote, underlying, now):
    from app.mixed.models import StockProposal
    from app.mixed.portfolio_execution import prepare_stock
    from app.mixed.portfolio_options import prepare
    from app.mixed.portfolio_protection import tighten
    from app.options.models import OptionProposal

    packet = request.packet
    stock = isinstance(packet.entry, StockIntent)
    with c.engine.journal.write() as db:
        c._bound(db)
        saved, answer, _, _ = stored(db, key, usable=True)
        if saved != request or answer != result:
            raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_APPLICATION_CHANGED")
        prior = db.execute(
            "SELECT * FROM execution_portfolio_decisions WHERE source_key=?", (key,)
        ).fetchone()
        if prior:
            return json.loads(prior["result_json"])
        _, position, guard, account = current(c.engine, db, packet.play_id, now)
        checked = review(
            packet,
            result.plan,
            position=position,
            protection=guard,
            account=account,
            quote=quote,
            underlying=underlying,
            now=now,
        )
        if checked.outcome == "ELIGIBLE" and result.plan.action == "EXIT_ALL":
            if stock:
                return prepare_stock(
                    c.engine,
                    key,
                    StockProposal(
                        action="CLOSE",
                        instrument=packet.entry.instrument,
                        thesis=result.plan.thesis,
                    ),
                    quote,
                    now=now,
                    play_id=packet.play_id,
                    origin="POSITION_MODEL",
                    _db=db,
                )
            return prepare(
                c.engine,
                key,
                OptionProposal(
                    action="CLOSE",
                    contract=packet.entry.instrument.contract,
                    thesis=result.plan.thesis,
                ),
                quote,
                underlying,
                now=now,
                play_id=packet.play_id,
                origin="POSITION_MODEL",
                _db=db,
            )
        output = {
            "status": checked.outcome,
            "play_id": packet.play_id,
            "review": checked.model_dump(mode="json"),
        }
        if checked.outcome == "ELIGIBLE":
            output.update(
                tighten(
                    c.engine,
                    packet.play_id,
                    checked.tightened_invalidation,
                    quote,
                    underlying,
                    now=now,
                    stock=stock,
                    _db=db,
                )
            )
        db.execute(
            "INSERT INTO execution_portfolio_decisions VALUES(?,?,?)",
            (
                key,
                fingerprint({"request": request, "result": result}),
                json.dumps(output, sort_keys=True),
            ),
        )
        c.engine.journal.event(
            db, now, "PORTFOLIO_MANAGEMENT_CONSUMED", {"source_key": key, **output}, packet.play_id
        )
        return output


async def run(c, frame):
    """Round-robin one optional call; independent mandatory protection already visited all plays."""
    from app.mixed.portfolio_protection import tick
    from app.options import position_judgment as j

    now = c.now()
    key = "manage:" + str(int(now.timestamp()) // 300)
    quotes, underlyings = frame_quotes(frame)
    try:
        secret = c._model_secret()
        with c.engine.journal.write() as db:
            c._bound(db)
            prior = db.execute(
                "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
            ).fetchone()
            if prior:
                return json.loads(prior[0] or '{"status":"ALREADY_STARTED"}')
            ids = list(
                reconstruct(history(c.engine, db, c.engine.portfolio_policy, now)).ledger.positions
            )
            if not ids:
                return {"status": "FLAT"}

            # Oldest last management attempt first; source absence on one play
            # does not prevent preparing a healthy peer.
            def last(identity):
                row = db.execute(
                    "SELECT max(started_at) FROM execution_option_opportunities WHERE json_extract(result_json,'$.position_request.packet.play_id')=?",
                    (identity,),
                ).fetchone()
                return row[0] or ""

            ids.sort(key=lambda identity: (last(identity), identity))
            packet = None
            for identity in ids:
                try:
                    h, p, guard, account = current(c.engine, db, identity, now)
                    row = db.execute(
                        "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (identity,)
                    ).fetchone()
                    entry = intent(row)
                    q = quotes.get(entry.instrument.instrument_id)
                    if q is None:
                        continue
                    u = (
                        None
                        if isinstance(entry, StockIntent)
                        else underlyings.get(entry.instrument.contract.underlying)
                    )
                    scan = scan_for(db, entry, frame, now)
                    config = j.configuration(
                        c.engine.policy.cost_policy, c.judgment_limits, c.position_policy
                    )
                    window = (
                        c.engine.calendar.current_window(now)
                        if isinstance(entry, StockIntent)
                        else c.engine._session(entry.instrument.contract, now)
                    )
                    from app.mixed.native_execution import session

                    if isinstance(entry, StockIntent):
                        window = session(c.engine, entry.instrument, now)
                    candidate = PortfolioPositionPacket(
                        play_id=identity,
                        decision_id=fingerprint(
                            {"key": key, "play_id": identity, "config": config}
                        ),
                        cycle_key="position:" + key.split(":")[1] + ":" + identity,
                        model_configuration_hash=fingerprint(config),
                        as_of=now,
                        valid_until=min(
                            now + timedelta(seconds=c.position_policy.max_lease_seconds),
                            entry.exit_at,
                            datetime.fromtimestamp(
                                (int(now.timestamp()) // 300 + 1) * 300, tz=now.tzinfo
                            ),
                        ),
                        position_revision=c.engine.journal.revision(db),
                        position=p,
                        entry=entry,
                        original_decision=original_decision(db, entry),
                        original_context=original_context(db, entry),
                        protection=guard,
                        history=h,
                        account=account,
                        quote=q,
                        underlying=u,
                        scan=scan,
                        session=window,
                        limits=c.engine.limits,
                        execution_policy=c.engine.policy,
                        policy=c.position_policy,
                        evidence_ids=tuple(
                            fingerprint(x) for x in (p, entry, account, q, guard, scan)
                        ),
                    )
                    if (
                        review(
                            candidate,
                            j.maintain(candidate),
                            position=p,
                            account=account,
                            quote=q,
                            underlying=u,
                            now=now,
                        ).outcome
                        == "MAINTAIN"
                    ):
                        packet = candidate
                        break
                except (ValueError, ExecutionBlocked):
                    continue
            if packet is None:
                return {"status": "HELD", "reason": "NO_HEALTHY_MANAGEMENT_CONTEXT"}
            request = j.create_request(packet, config, request_id=uuid4().hex, now=now)
            if len(request.model_dump_json().encode()) > j.MAX_REQUEST_BYTES:
                raise ExecutionBlocked("PORTFOLIO_MANAGEMENT_REQUEST_CAPACITY")
            evidence = {
                "position_request": request.model_dump(mode="json"),
                "status": "MODEL_PENDING",
                "play_id": packet.play_id,
            }
            db.execute(
                "INSERT INTO execution_option_opportunities VALUES(?,?,?,?,'STARTED',?)",
                (
                    key,
                    fingerprint(frame),
                    now.isoformat(),
                    frame.model_dump_json(),
                    json.dumps(evidence, sort_keys=True),
                ),
            )
            # No event between captured revision and same-owner admission.
            c.engine._admit_model_attempt(
                db, key, fingerprint(j.request_content(request)), now, request
            )
    except (ValueError, OSError, ExecutionBlocked) as exc:
        return {"status": "HELD", "reason": str(exc)}
    try:
        result = await (
            c.replay_model.run(request)
            if c.replay_model is not None
            else j.run_position_process(request, secret)
        )
        result = j.PositionResult.model_validate(result.model_dump())
        completed = c.now()
        evidence.update(
            position_result=result.model_dump(mode="json"),
            position_completed_at=completed.isoformat(),
            position_timely=c._model_timely(request, now, completed)
            and now <= completed < packet.valid_until,
        )
        c._pending_evidence(key, evidence)
        if (
            result.usage is None
            or result.request_id != request.request_id
            or result.packet_hash != fingerprint(packet)
            or result.configuration_hash != fingerprint(config)
            or result.plan.entry_client_id != packet.play_id
        ):
            raise ValueError("Unknown or mismatched management usage")
        c.engine.record_position_usage(key, result.usage, result.plan, now=completed)
    except Exception as exc:  # noqa: BLE001 -- no provider messages
        c._model_halt("OPTION_MODEL_COST_UNKNOWN", c.now())
        from app.options.scope_runtime import protection

        qs, us = protection(frame)
        await tick(
            c.engine,
            now=c.now(),
            stock_quotes=tuple(s.quote for s in (*frame.stocks, *frame.held_stocks)),
            option_quotes=qs,
            underlyings=us,
        )
        return c._finish(
            key,
            {
                "status": "HELD",
                "reason": "OPTION_MODEL_COST_UNKNOWN",
                "error_class": type(exc).__name__,
            },
        )
    # Full portfolio supervision follows every completed/failed advice attempt.
    from app.options.scope_runtime import protection

    qs, us = protection(frame)
    await tick(
        c.engine,
        now=c.now(),
        stock_quotes=tuple(s.quote for s in (*frame.stocks, *frame.held_stocks)),
        option_quotes=qs,
        underlyings=us,
    )
    if result.error is not None or not evidence["position_timely"]:
        return c._finish(key, {"status": "HELD", "reason": "MANAGEMENT_MAINTAIN_OR_REJECTED"})
    try:
        j.validate_result(request, result)
        output = apply(
            c,
            key,
            request,
            result,
            quotes.get(packet.entry.instrument.instrument_id),
            packet.underlying,
            c.now(),
        )
        if output["status"] == "PREPARED":
            q = quotes.get(packet.entry.instrument.instrument_id)
            output["status"] = (
                await c.engine.dispatch_stock(output["client_id"], q, now=c.now())
                if isinstance(packet.entry, StockIntent)
                else await c.engine.dispatch(output["client_id"], q, packet.underlying, now=c.now())
            )
        return c._finish(key, output)
    except (ValueError, ExecutionBlocked) as exc:
        return c._finish(key, {"status": "HELD", "reason": str(exc)})
