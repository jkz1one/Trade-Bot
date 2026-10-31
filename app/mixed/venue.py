"""Stock operations on the same exact built-in durable option fixture balance."""

import hashlib
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from itertools import pairwise
from uuid import uuid4

from app.mixed.accounting import _apply_stock, _stock_fill_rules, _validate_stock_intent
from app.mixed.models import MixedLedger
from app.mixed.stock_models import StockFill, StockIntent, StockObservation, StockQuote
from app.options.lifecycle import TERMINAL


def _enrolled(venue):
    from app.options.venue import DurableOptionVenue

    if type(venue) is not DurableOptionVenue or venue.stock_limits is None:
        raise ValueError("Exact native mixed venue enrollment required")


def accept(venue, intent, now, deadline, parent_pid):
    _enrolled(venue)
    intent = StockIntent.model_validate(intent.model_dump(warnings=False))

    def operation(state):
        _validate_stock_intent(venue.stock_limits, intent)
        _clock(state, now)
        orders = (*state.orders, *state.stock_orders)
        if any(o.client_id == intent.client_id for o in orders):
            raise ValueError("Attempted stock order cannot replay")
        if (
            venue.portfolio_policy is None and any(o.status not in TERMINAL for o in orders)
        ) or state.underlying_exposures:
            raise ValueError("A cross-instrument order or exposure already exists")
        if venue.portfolio_policy is not None:
            from app.mixed.portfolio_venue import accepting

            accepting(venue, state, intent, now)
        if not intent.prepared_at <= now < intent.approval_expires_at:
            raise ValueError("Original stock approval expired")
        if intent.side == "BUY":
            if (
                state.position is not None
                or state.stock_position is not None
                or (intent.approved_entry_debit + intent.reserved_exit_fee > state.settled_cash)
            ):
                raise ValueError("Second position or unfunded stock entry")
        elif (
            state.stock_position is None
            or state.stock_position.instrument != intent.instrument
            or state.stock_position.entry.client_id != intent.closing_entry_client_id
            or intent.quantity > state.stock_position.quantity
            or any(
                getattr(intent, k) != getattr(state.stock_position.entry, k)
                for k in (
                    "source_hash",
                    "source_at",
                    "source_valid_until",
                    "family",
                    "original_invalidation",
                    "original_target",
                    "exit_at",
                    "carry",
                    "thesis",
                )
            )
        ):
            raise ValueError("Stock sale must close exact owned shares")
        order = StockObservation(
            intent=intent,
            order_id="stock-fixture-" + uuid4().hex,
            client_id=intent.client_id,
            instrument=intent.instrument,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            status="OPEN",
            filled_quantity=0,
            updated_at=now,
        )
        return state.model_copy(
            update={
                "stock_orders": (*state.stock_orders, order),
                "submit_count": state.submit_count + 1,
            }
        ), order.order_id

    return venue._mutate(operation, deadline=deadline, parent_pid=parent_pid, intent=intent)


def fill(venue, intent, quantity, quote, at, *, fill_id):
    _enrolled(venue)
    intent = StockIntent.model_validate(intent.model_dump(warnings=False))
    quote = StockQuote.model_validate(quote.model_dump(warnings=False))

    def operation(state):
        _clock(state, at)
        order = next(o for o in state.stock_orders if o.client_id == intent.client_id)
        if (
            order.intent != intent
            or order.status in TERMINAL
            or any(
                getattr(order, k) != getattr(intent, k)
                for k in ("instrument", "side", "quantity", "limit_price")
            )
        ):
            raise ValueError("Exact working stock order required")
        if not order.updated_at <= at < intent.order_expires_at:
            raise ValueError("Stock fill outside original DAY lifetime")
        if any(f.fill_id == fill_id for o in (*state.orders, *state.stock_orders) for f in o.fills):
            raise ValueError("Duplicate cross-instrument fill identity")
        p = venue.stock_limits
        buying = intent.side == "BUY"
        raw = quote.ask if buying else quote.bid
        price = raw * (1 + (1 if buying else -1) * p.slippage_bps / 10000)
        price = (price / intent.instrument.tick).to_integral_value(
            rounding=ROUND_CEILING if buying else ROUND_FLOOR
        ) * intent.instrument.tick
        # StockFill performs the exact share/Decimal validation before arithmetic.
        receipt = StockFill(
            fill_id=fill_id,
            order_id=order.order_id,
            sequence=state.sequence + 1,
            quantity=quantity,
            price=price,
            fee="0",
            occurred_at=at,
            quote_hash=hashlib.sha256(quote.model_dump_json().encode()).hexdigest(),
            quote=quote,
        )
        fee = receipt.quantity * (p.entry_fee_per_share if buying else p.exit_fee_per_share)
        if not order.fills:
            fee += p.entry_fee_per_order if buying else p.exit_fee_per_order
        receipt = StockFill.model_validate({**receipt.model_dump(), "fee": fee})
        if receipt.quantity > order.quantity - order.filled_quantity:
            raise ValueError("Stock fill exceeds original remaining quantity")
        usage = {}
        for old in state.stock_orders:
            # Reconstruct consumed source size without accepting receipt-time aliases.
            for f in old.fills:
                from app.options.engine import fingerprint

                key = (fingerprint(f.quote.instrument), old.side, f.quote.source_at)
                q, used = usage.get(key, (f.quote, Decimal(0)))
                if any(
                    getattr(q, k) != getattr(f.quote, k)
                    for k in ("bid", "ask", "bid_size", "ask_size")
                ):
                    raise ValueError("Stored stock source quote conflict")
                usage[key] = (q, used + f.quantity)
        _stock_fill_rules(venue.stock_limits, intent, receipt, len(order.fills), usage)
        if (
            buying
            and sum((f.quantity * f.price + f.fee for f in (*order.fills, receipt)), Decimal(0))
            > intent.approved_entry_debit
        ):
            raise ValueError("Stock fill exceeds approved entry debit")
        state_ledger = MixedLedger(
            cash=state.cash,
            settled_cash=state.settled_cash,
            position=state.position,
            stock_position=state.stock_position,
            high_watermark=venue.initial_capital,
        )
        ledger = _apply_stock(state_ledger, intent, receipt)
        total = order.filled_quantity + receipt.quantity
        updated = StockObservation.model_validate(
            {
                **order.model_dump(),
                "fills": (*order.fills, receipt),
                "filled_quantity": total,
                "status": "FILLED" if total == order.quantity else "PARTIAL",
                "updated_at": at,
            }
        )
        return state.model_copy(
            update={
                "cash": ledger.cash,
                "settled_cash": ledger.settled_cash,
                "stock_position": ledger.stock_position,
                "sequence": receipt.sequence,
                "stock_orders": tuple(
                    updated if o.client_id == order.client_id else o for o in state.stock_orders
                ),
            }
        ), receipt

    return venue._mutate(operation, intent=intent)


def terminal(venue, client_id, status, at):
    _enrolled(venue)
    if status not in {"CANCELED", "REJECTED", "EXPIRED"}:
        raise ValueError("Explicit stock terminal outcome required")

    def operation(state):
        _clock(state, at)
        old = next(o for o in state.stock_orders if o.client_id == client_id)
        if old.status in TERMINAL or at < old.updated_at or (status == "REJECTED" and old.fills):
            raise ValueError("Stock terminal history cannot regress")
        updated = StockObservation.model_validate(
            {**old.model_dump(), "status": status, "updated_at": at}
        )
        return state.model_copy(
            update={
                "stock_orders": tuple(
                    updated if o.client_id == client_id else o for o in state.stock_orders
                )
            }
        ), None

    return venue._mutate(operation)


def _clock(state, at):
    from app.options.engine import clock

    at = clock(at)
    if any(o.updated_at > at for o in (*state.orders, *state.stock_orders)) or any(
        r.occurred_at > at for r in state.receipts
    ):
        raise ValueError("Mixed fixture clock cannot precede accepted history")


def validate_state(state):
    """One complete event/order namespace for the explicitly enrolled fixture."""
    orders = (*state.orders, *state.stock_orders)
    if (
        len(orders) > 1000
        or len({o.client_id for o in orders}) != len(orders)
        or len({o.order_id for o in orders}) != len(orders)
    ):
        raise ValueError("Mixed fixture order identities must be unique and bounded")
    if not hasattr(state, "positions") and sum(o.status not in TERMINAL for o in orders) > 1:
        raise ValueError("Mixed fixture has one unresolved order lock")
    fills = [f for o in orders for f in o.fills]
    if len({f.fill_id for f in fills}) != len(fills):
        raise ValueError("Mixed fixture fill identities must be unique")
    events = sorted((*fills, *state.receipts), key=lambda e: e.sequence)
    if [e.sequence for e in events] != list(range(1, state.sequence + 1)):
        raise ValueError("Mixed fixture requires one complete event sequence")
    if any(a.occurred_at > b.occurred_at for a, b in pairwise(events)):
        raise ValueError("Mixed fixture event clock cannot regress")
    if state.submit_count != len(orders):
        raise ValueError("Mixed fixture attempt count must retain every order")
