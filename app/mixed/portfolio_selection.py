"""Sequential native selection: shared configured priorities, at most one paid call."""

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.portfolio_protection import entry_guard
from app.mixed.portfolio_store import history


async def cycle(c, frame):
    from app.options.coordinator import DegenFrame
    from app.options.scope_runtime import protection

    frame = DegenFrame.model_validate(frame.model_dump())
    managed = await c.supervise(*protection(frame), stocks=stock_inputs(frame))
    if not managed.get("reconciled"):
        return {"status": "HOLD", "reason": "PORTFOLIO_PROTECTION_REQUIRED", "management": managed}
    results = []
    paid = c.judgment_limits is not None or c.entry_policy is not None
    status, reason = "COMPLETE", None
    for slot in range(1 if paid else 2):
        try:
            with c.engine.journal.read() as db:
                c._bound(db)
                h = history(c.engine, db, c.engine.portfolio_policy, c.now())
                projected = reconstruct(h)
                if len(projected.commitments) >= h.policy.max_plays:
                    status = "HELD" if projected.ledger.positions else "HOLD"
                    reason = "PLAY_CAPACITY"
                    break
                entry_guard(c.engine, db, c.engine.portfolio_policy, c.now())
        except ExecutionBlocked as exc:
            status, reason = "HOLD", str(exc)
            break
        outcome = await c._cycle_once(frame, portfolio_slot=slot)
        results.append(outcome)
        if outcome.get("status") not in {"OPEN", "FILLED", "PARTIAL"}:
            break
    if c.position_policy is not None:
        # A healthy held play does not occupy the free slot. Preserve the existing
        # one-paid-call budget: native management follows only if no entry call
        # was admitted in this completed slot, including a rejected/unknown call.
        prefix = "degen:" + str(int(c.now().timestamp()) // 300) + ":portfolio:"
        with c.engine.journal.read() as db:
            entry_call = db.execute(
                "SELECT 1 FROM execution_model_calls WHERE source_key LIKE ?", (prefix + "%",)
            ).fetchone()
        if entry_call is None:
            from app.mixed.portfolio_management import run

            advice = await run(c, frame)
            managed["discretionary"] = advice
            if advice.get("status") != "FLAT":
                status = "HELD"
    return {"status": status, "reason": reason, "entries": results, "management": managed}


def stock_inputs(frame):
    from app.mixed.quote_fills import _unique

    values = _unique(
        (x.quote for x in (*frame.stocks, *frame.held_stocks)), lambda q: q.instrument.instrument_id
    )
    from app.mixed.sources import StockCycleInput

    return tuple(StockCycleInput(quote=q) for q in values.values())


def held_instruments(c):
    """Durable held plus pending originals, including contracts absent from current scans."""
    from app.mixed.portfolio_store import intent

    with c.engine.journal.read() as db:
        c._bound(db)
        h = history(c.engine, db, c.engine.portfolio_policy, c.now())
        projection = reconstruct(h)
        identities = {x.play_id for x in projection.commitments}
        return tuple(
            intent(r).instrument
            for r in db.execute(
                "SELECT * FROM execution_portfolio_orders WHERE json_extract(intent_json,'$.side')='BUY'"
            )
            if r["play_id"] in identities
        )
