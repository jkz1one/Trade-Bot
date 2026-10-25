"""Opt-in simulated fills from delivered quotes, using the existing native venue.

No market reads, order submissions, settlement assumptions or model calls.
Only acknowledged native orders can receive a later observed executable quote.
"""

from datetime import datetime
from decimal import Decimal

from app.mixed.replay import stock_fill_quantity
from app.mixed.stock_models import StockIntent
from app.options.engine import exact, fingerprint
from app.options.fill_evidence import validate_underlying
from app.options.lifecycle import TERMINAL, OptionIntent
from app.options.replay import fill_quantity
from app.options.scope_runtime import protection


def _unique(quotes, key):
    result = {}
    for quote in quotes:
        identity = key(quote)
        if identity in result and result[identity] != quote:
            raise ValueError("Conflicting delivered quotes")
        result[identity] = quote
    return result


@exact
def apply_quote_fills(runtime, packet, at):
    """Called after native delivery validation and before reconciliation/protection."""
    if runtime.policy.simulated_fills != "mixed-quote-fills-v1" or runtime.mixed is None:
        raise ValueError("Explicit frozen quote-fill policy required")
    engine = runtime.c.engine
    quotes, underlyings = protection(packet.frame)
    options = _unique(quotes, lambda q: q.instrument.instrument_id)
    stocks = _unique((i.quote for i in packet.frame.stocks), lambda q: q.instrument.instrument_id)
    underlying = _unique(underlyings, lambda q: q.symbol)
    with engine.journal.read() as db:
        runtime._bound(db)
        delivery = db.execute(
            "SELECT packet_hash,status FROM execution_mixed_runtime_inputs WHERE sequence=?",
            (packet.sequence,),
        ).fetchone()
        if (
            packet.population_id != engine.limits.population_id
            or not 0
            <= (at - packet.recorded_at).total_seconds()
            < runtime.policy.feed_max_age_seconds
            or delivery is None
            or delivery["packet_hash"] != fingerprint(packet)
            or delivery["status"] not in {"ACCEPTED", "DELIVERED"}
        ):
            raise ValueError("Validated native delivery required before simulated fills")
        acknowledged = {}
        for table, model in (
            ("execution_orders", OptionIntent),
            ("execution_stock_orders", StockIntent),
        ):
            for row in db.execute(
                f"SELECT client_id,intent_json,attempted_at FROM {table} "
                "WHERE status IN ('OPEN','PARTIAL') AND attempted_at IS NOT NULL"
            ):
                acknowledged[row["client_id"]] = (
                    model.model_validate_json(row["intent_json"]),
                    datetime.fromisoformat(row["attempted_at"]),
                )
    venue = engine.venue
    snapshot = venue.snapshot(at)
    count = 0
    for order in (*snapshot.orders, *snapshot.stock_orders):
        if order.status in TERMINAL or order.client_id not in acknowledged:
            continue
        intent, attempted_at = acknowledged[order.client_id]
        stock = isinstance(intent, StockIntent)
        if at >= intent.order_expires_at:
            terminal = venue.record_stock_terminal if stock else venue.record_terminal
            terminal(order.client_id, "EXPIRED", at)
            continue
        quote = (stocks if stock else options).get(intent.instrument.instrument_id)
        if quote is None or quote.source_at <= attempted_at:
            continue
        size = quote.ask_size if intent.side == "BUY" else quote.bid_size
        if size is None:
            continue
        current = venue.snapshot(at)
        quantity = (stock_fill_quantity if stock else fill_quantity)(
            intent,
            order,
            current,
            quote,
            at,
            engine.policy.mixed_owner.stocks if stock else engine.limits,
        )
        # Option replay historically compares whole quote objects. For ongoing
        # deliveries, receipt-clock aliases must not replenish the same source size.
        consumed = Decimal(0)
        for prior in current.stock_orders if stock else current.orders:
            if prior.side != intent.side:
                continue
            for fill in prior.fills:
                old = fill.quote
                if old.instrument != quote.instrument or old.source_at != quote.source_at:
                    continue
                if any(
                    getattr(old, k) != getattr(quote, k)
                    for k in ("bid", "ask", "bid_size", "ask_size")
                ):
                    raise ValueError("Source quote conflicts with retained simulated fills")
                consumed += fill.quantity
        quantity = min(quantity, max(0, size - consumed))
        if quantity <= 0:
            continue
        fill_id = "quoted-" + fingerprint(
            {
                "population": packet.population_id,
                "client": order.client_id,
                "quote": quote.model_dump(mode="json"),
                "prior_quantity": str(order.filled_quantity),
            }
        )
        if stock:
            venue.fill_stock(intent, quantity, quote, at, fill_id=fill_id)
        else:
            observed = underlying.get(intent.instrument.contract.underlying)
            if observed is not None:
                try:
                    validate_underlying(engine.limits, intent, quote, observed, at)
                except ValueError:
                    observed = None
            venue.fill(intent, int(quantity), quote, at, fill_id=fill_id, underlying=observed)
        count += 1
    return count
