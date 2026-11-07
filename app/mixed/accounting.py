"""Exact common cash-history reconstruction. No admission, dispatch or model calls.

The option branch uses the existing native accounting operations on the *current*
common cash state. It never funds an independent child ledger or translates shares
into options. Execution owners must still verify approvals, complete native order
history, revisions and immutable snapshot prefixes before using this projection.
"""

import hashlib
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from itertools import pairwise
from zoneinfo import ZoneInfo

from app.options.models import paper_market_evidence
from app.mixed.models import (
    CashHistory,
    CashProjection,
    MixedLedger,
    OptionTrade,
    Settlement,
    StockIntent,
    StockLot,
    StockPosition,
)
from app.options.accounting import apply_fill, apply_receipt
from app.options.governor import _fresh, _supported
from app.options.lifecycle import OptionIntent, OptionLedger

ZERO = Decimal(0)


def _day(at):
    return at.astimezone(ZoneInfo("America/New_York")).date().isoformat()


def _option_part(state):
    return OptionLedger.model_validate(
        {k: v for k, v in state.model_dump().items() if k in OptionLedger.model_fields}
    )


def _merge(state, native):
    return MixedLedger.model_validate({**state.model_dump(), **native.model_dump()})


def _validate_intent(policy, intent):
    """Static native envelope; this is not a source/strategy approval."""
    if isinstance(intent, OptionIntent):
        p = policy.options
        if (
            intent.instrument.provider != p.provider
            or not intent.instrument.metadata_complete
            or not intent.instrument.option_tradable
            or intent.instrument.contract.underlying not in p.allowed_underlyings
            or not _supported(intent.instrument.contract)
            or intent.quantity > p.max_contracts
        ):
            raise ValueError("MIXED_OPTION_IDENTITY_OR_QUANTITY")
        if intent.side == "BUY":
            minimum = (
                intent.quantity * intent.limit_price * intent.instrument.contract.multiplier
                + p.entry_fee_per_contract * intent.quantity
                + p.entry_fee_per_order
            )
            exit_fee = intent.quantity * (p.exit_fee_per_contract + p.exit_fee_per_order)
            if (
                not minimum <= intent.approved_entry_debit <= p.max_entry_debit
                or not intent.approved_entry_debit + exit_fee
                <= intent.approved_full_premium_loss
                <= min(p.max_account_exposure, p.max_full_premium_loss)
            ):
                raise ValueError("MIXED_OPTION_DEBIT_OR_EXIT_RESERVE")
        return
    _validate_stock_intent(policy.stocks, intent)


def _validate_stock_intent(p, intent):
    i = intent.instrument
    if (
        i.provider != p.provider
        or not i.metadata_complete
        or not i.tradable
        or i.symbol not in p.allowed_symbols
        or intent.quantity > p.max_shares
        or intent.quantity % p.share_step
        or intent.limit_price % i.tick
    ):
        raise ValueError("MIXED_STOCK_IDENTITY_OR_QUANTITY")
    if intent.side == "BUY":
        debit = intent.quantity * intent.limit_price + (
            p.entry_fee_per_share * intent.quantity + p.entry_fee_per_order
        )
        # A minimum-sized sale may pay one order fee for every share increment.
        exit_fee = intent.quantity * p.exit_fee_per_share + (
            intent.quantity / p.share_step * p.exit_fee_per_order
        )
        if (
            intent.limit_price < p.minimum_price
            or not debit <= intent.approved_entry_debit <= p.max_entry_debit
            or intent.reserved_exit_fee != exit_fee
            or intent.approved_entry_debit + exit_fee > p.max_account_exposure
        ):
            raise ValueError("MIXED_STOCK_DEBIT_OR_EXIT_RESERVE")


def _stock_fill(policy, intent, fill, index, used):
    _stock_fill_rules(policy.stocks, intent, fill, index, used)


def _stock_fill_rules(p, intent, fill, index, used):
    q = fill.quote
    if (
        q.instrument != intent.instrument
        or q.source != p.quote_source
        or not q.complete
        or not paper_market_evidence(q)
        or q.source_at <= intent.prepared_at
        or not _fresh(
            q.source_at,
            q.received_at,
            fill.occurred_at,
            p.quote_max_age_seconds,
            p.max_receive_lag_seconds,
        )
        or fill.quantity % p.share_step
        or (
            intent.side == "BUY"
            and (q.bid < p.minimum_price or (q.ask - q.bid) / q.ask > p.max_spread_fraction)
        )
    ):
        raise ValueError("MIXED_STOCK_FILL_EVIDENCE")
    if hashlib.sha256(q.model_dump_json().encode()).hexdigest() != fill.quote_hash:
        raise ValueError("MIXED_STOCK_QUOTE_HASH")
    # A changed receipt time cannot mint more size at one source instant.
    from app.options.engine import fingerprint

    key = (fingerprint(q.instrument), intent.side, q.source_at)
    previous, size_used = used.get(key, (q, ZERO))
    if any(getattr(previous, k) != getattr(q, k) for k in ("bid", "ask", "bid_size", "ask_size")):
        raise ValueError("MIXED_STOCK_SOURCE_QUOTE_CHANGED")
    size_used += fill.quantity
    size = q.ask_size if intent.side == "BUY" else q.bid_size
    if size is None or size_used > size:
        raise ValueError("MIXED_STOCK_SIZE_UNKNOWN_OR_EXCEEDED")
    used[key] = (q, size_used)
    buying = intent.side == "BUY"
    raw = q.ask if buying else q.bid
    price = raw * (1 + (1 if buying else -1) * p.slippage_bps / 10000)
    price = (price / q.instrument.tick).to_integral_value(
        rounding=ROUND_CEILING if buying else ROUND_FLOOR
    ) * q.instrument.tick
    fee = (p.entry_fee_per_share if buying else p.exit_fee_per_share) * fill.quantity
    if index == 0:
        fee += p.entry_fee_per_order if buying else p.exit_fee_per_order
    if (
        fill.price != price
        or fill.fee != fee
        or (buying and price > intent.limit_price)
        or (not buying and price < intent.limit_price)
    ):
        raise ValueError("MIXED_STOCK_FILL_PRICE_OR_FEE")


def _apply_stock(state, intent, fill):
    p = state.stock_position
    if state.position is not None:
        raise ValueError("MIXED_EXISTING_OPTION_POSITION")
    value, gross = fill.quantity * fill.price, ZERO
    if intent.side == "BUY":
        if p is not None and p.entry != intent:
            raise ValueError("MIXED_STOCK_AVERAGING_OR_SECOND_POSITION")
        lots = (
            (*p.lots, StockLot(quantity=fill.quantity, price=fill.price))
            if p
            else (StockLot(quantity=fill.quantity, price=fill.price),)
        )
        p = StockPosition(
            instrument=intent.instrument,
            entry=intent,
            quantity=(p.quantity if p else ZERO) + fill.quantity,
            lots=lots,
        )
        cash = state.cash - value - fill.fee
        settled = state.settled_cash - value - fill.fee
    else:
        if (
            p is None
            or p.instrument != intent.instrument
            or p.entry.client_id != intent.closing_entry_client_id
            or fill.quantity > p.quantity
            or any(
                getattr(p.entry, k) != getattr(intent, k)
                for k in (
                    "source_hash",
                    "source_at",
                    "source_valid_until",
                    "family",
                    "original_invalidation",
                    "original_target",
                    "exit_at",
                    "carry",
                )
            )
        ):
            raise ValueError("MIXED_UNOWNED_STOCK_SALE_OR_CHANGED_ORIGINAL")
        remaining, basis, lots = fill.quantity, ZERO, []
        for lot in p.lots:
            take = min(remaining, lot.quantity)
            basis += take * lot.price
            remaining -= take
            if take < lot.quantity:
                lots.append(StockLot(quantity=lot.quantity - take, price=lot.price))
        gross = value - basis
        p = (
            StockPosition(
                instrument=p.instrument,
                entry=p.entry,
                quantity=p.quantity - fill.quantity,
                lots=tuple(lots),
            )
            if lots
            else None
        )
        cash = state.cash + value - fill.fee
        settled = state.settled_cash + min(ZERO, value - fill.fee)
    day = _day(fill.occurred_at)
    return MixedLedger.model_validate(
        {
            **state.model_dump(),
            "cash": cash,
            "settled_cash": settled,
            "stock_position": p,
            "realized_pnl": state.realized_pnl + gross,
            "fees_paid": state.fees_paid + fill.fee,
            "daily_net_pnl": {
                **state.daily_net_pnl,
                day: state.daily_net_pnl.get(day, ZERO) + gross - fill.fee,
            },
            "high_watermark": max(state.high_watermark, cash if p is None else ZERO),
        }
    )


def _record(event):
    return event.receipt if isinstance(event, Settlement) else event.fill


def reconstruct(history: CashHistory) -> CashProjection:
    """Revalidate a complete immutable cash prefix without granting order authority."""
    from app.mixed.portfolio_accounting import parse_history

    history = parse_history(history)
    with localcontext(Context(prec=192)):
        return _reconstruct(history)


def _reconstruct(history):
    from app.mixed import portfolio_accounting as portfolio

    multiple = isinstance(history, portfolio.PortfolioHistory)
    policy = history.policy
    ordered = sorted(history.events, key=lambda e: _record(e).sequence)
    if (
        [_record(e).sequence for e in ordered] != list(range(1, len(ordered) + 1))
        or any(_record(a).occurred_at > _record(b).occurred_at for a, b in pairwise(ordered))
        or any(
            not history.opened_at <= _record(e).occurred_at <= history.captured_at for e in ordered
        )
    ):
        raise ValueError("MIXED_EVENT_SEQUENCE_OR_TIME_CONFLICT")
    ledger_type = portfolio.PortfolioLedger if multiple else MixedLedger
    state = ledger_type(cash=policy.capital, high_watermark=policy.capital)
    seen, intents, quantities, debits, indices, orders = set(), {}, {}, {}, {}, {}
    option_usage, stock_usage, retired = {}, {}, set()
    portfolio_option_usage = {}
    for event in ordered:
        record = _record(event)
        key = (
            "RECEIPT" if isinstance(event, Settlement) else "FILL",
            record.receipt_id if isinstance(event, Settlement) else record.fill_id,
        )
        if key in seen:
            raise ValueError("MIXED_DUPLICATE_RECEIPT_OR_FILL")
        seen.add(key)
        if isinstance(event, Settlement):
            if multiple:
                if event.play_id is not None:
                    retired.add(event.play_id)
                state = portfolio.apply_settlement(state, event)
                continue
            if event.play_id is not None:
                raise ValueError("Portfolio settlement identity requires v2 enrollment")
            if record.kind != "FUNDS_SETTLED" and state.position is not None:
                retired.add(state.position.entry_client_id)
            state = _merge(state, apply_receipt(_option_part(state), record))
            continue
        intent, fill = event.intent, event.fill
        _validate_intent(policy, intent)
        client_id = intent.client_id
        if client_id in intents and intents[client_id] != intent:
            raise ValueError("MIXED_ORIGINAL_INTENT_CHANGED")
        if client_id in intents and orders[client_id] != (fill.order_id, event.attempted_at):
            raise ValueError("MIXED_ORDER_OR_ATTEMPT_CHANGED")
        if any(v[0] == fill.order_id and k != client_id for k, v in orders.items()):
            raise ValueError("MIXED_ORDER_ID_REUSED")
        if not (
            history.opened_at
            <= intent.prepared_at
            <= event.attempted_at
            < intent.approval_expires_at
            and event.attempted_at <= fill.occurred_at < intent.order_expires_at
        ):
            raise ValueError("MIXED_ORIGINAL_DEADLINE_VIOLATION")
        intents[client_id], orders[client_id] = intent, (fill.order_id, event.attempted_at)
        quantity = quantities.get(client_id, ZERO) + fill.quantity
        if quantity > intent.quantity:
            raise ValueError("MIXED_ORDER_OVERFILLED")
        quantities[client_id] = quantity
        index = indices.get(client_id, 0)
        if intent.side == "BUY" and client_id in retired:
            raise ValueError("MIXED_ENTRY_CANNOT_RESUME_AFTER_EXIT")
        if multiple and intent.side == "SELL":
            retired.add(portfolio.play_id(intent))
        if isinstance(event, OptionTrade):
            from app.options.fill_evidence import validate_fill

            if not multiple and state.stock_position is not None:
                raise ValueError("MIXED_EXISTING_STOCK_POSITION")
            if intent.side == "SELL" and state.position is not None:
                if intent.closing_entry_client_id not in (None, state.position.entry_client_id):
                    raise ValueError("MIXED_OPTION_CLOSE_LINEAGE")
                retired.add(state.position.entry_client_id)
            validate_fill(policy.options, intent, fill, index, option_usage)
            if multiple:
                portfolio.check_option_source_size(intent, fill, portfolio_option_usage)
            value = fill.price * fill.quantity * intent.instrument.contract.multiplier
            updated = (
                portfolio.apply_trade(state, intent, fill)
                if multiple
                else _merge(state, apply_fill(_option_part(state), intent, fill))
            )
        else:
            _stock_fill(policy, intent, fill, index, stock_usage)
            if intent.side == "SELL" and state.stock_position is not None:
                retired.add(state.stock_position.entry.client_id)
            value = fill.price * fill.quantity
            updated = (
                portfolio.apply_trade(state, intent, fill)
                if multiple
                else _apply_stock(state, intent, fill)
            )
        if intent.side == "BUY":
            paid = debits.get(client_id, ZERO) + value + fill.fee
            if paid > intent.approved_entry_debit:
                raise ValueError("MIXED_APPROVED_DEBIT_EXCEEDED")
            debits[client_id] = paid
        state = updated
        indices[client_id] = index + 1

    terminal_ids = set()
    for item in history.terminals:
        intent = item.intent
        _validate_intent(policy, intent)
        if (
            intent.client_id in terminal_ids
            or not history.opened_at
            <= intent.prepared_at
            <= item.observed_at
            <= history.captured_at
            or (intent.client_id in intents and intents[intent.client_id] != intent)
            or any(r.intent.client_id == intent.client_id for r in history.reservations)
        ):
            raise ValueError("MIXED_TERMINAL_ID_OR_ORIGINAL_CONFLICT")
        if (
            item.attempted_at is not None
            and not intent.prepared_at <= item.attempted_at < intent.approval_expires_at
        ):
            raise ValueError("MIXED_TERMINAL_ATTEMPT_DEADLINE")
        if item.order_id is not None and item.attempted_at is None:
            raise ValueError("MIXED_TERMINAL_UNATTEMPTED_ORDER")
        if intent.client_id in orders and orders[intent.client_id] != (
            item.order_id,
            item.attempted_at,
        ):
            raise ValueError("MIXED_TERMINAL_ATTEMPT_CHANGED")
        if item.order_id is not None and any(
            oid == item.order_id and client != intent.client_id
            for client, (oid, _) in orders.items()
        ):
            raise ValueError("MIXED_TERMINAL_ORDER_ID_REUSED")
        if item.order_id is not None:
            orders[intent.client_id] = (item.order_id, item.attempted_at)
        quantity = quantities.get(intent.client_id, ZERO)
        if (
            (item.status == "FILLED") != (quantity == intent.quantity)
            or (item.status == "REJECTED" and quantity)
            or any(
                not isinstance(e, Settlement)
                and e.intent.client_id == intent.client_id
                and e.fill.occurred_at > item.observed_at
                for e in ordered
            )
        ):
            raise ValueError("MIXED_TERMINAL_FILL_CONFLICT")
        intents[intent.client_id] = intent
        terminal_ids.add(intent.client_id)
    commitments = ()
    if multiple:
        if any(
            r.intent.side == "BUY" and r.intent.client_id in retired for r in history.reservations
        ):
            raise ValueError("MIXED_ENTRY_CANNOT_RESUME_AFTER_EXIT")
        reserved, blockers, commitments = portfolio.reservations(
            history, state, intents, quantities, debits
        )
    else:
        reserved, blockers = _reservations(history, state, intents, quantities, debits)
    cost, daily, unknown, cost_ids, allocations = ZERO, {}, [], set(), set()
    resolutions = {}
    for item in history.cost_resolutions:
        if (
            item.cost_id in resolutions
            or not history.opened_at <= item.recorded_at <= history.captured_at
        ):
            raise ValueError("MIXED_COST_RESOLUTION_ID_OR_TIME")
        resolutions[item.cost_id] = item
    for item in history.costs:
        if (
            item.cost_id in cost_ids
            or not history.opened_at <= item.occurred_at <= history.captured_at
        ):
            raise ValueError("MIXED_COST_ID_OR_TIME_CONFLICT")
        cost_ids.add(item.cost_id)
        # Paid entry reasoning can precede native preparation. Management requires
        # actual owned entry fills. Rejected/unfilled entry calls remain charged.
        if item.entry_client_id is not None:
            entry = intents.get(item.entry_client_id)
            if entry is None or entry.side != "BUY":
                raise ValueError("MIXED_COST_ENTRY_LINEAGE")
            if item.kind == "MANAGEMENT_MODEL" and not any(
                not isinstance(e, Settlement)
                and e.intent.client_id == item.entry_client_id
                and e.fill.occurred_at <= item.occurred_at
                for e in ordered
            ):
                raise ValueError("MIXED_MANAGEMENT_COST_BEFORE_POSITION")
        resolution = resolutions.get(item.cost_id)
        if resolution is not None and (
            item.amount is not None or resolution.recorded_at < item.occurred_at
        ):
            raise ValueError("MIXED_COST_RESOLUTION_CONFLICT")
        amount = resolution.amount if resolution else item.amount
        if item.kind in {"DATA", "HOST", "OPERATING"}:
            allocations.add((_day(item.occurred_at), item.kind))
        if amount is None:
            unknown.append(item.cost_id)
        else:
            cost += amount
            day = _day(item.occurred_at)
            daily[day] = daily.get(day, ZERO) + amount
    if set(resolutions) - cost_ids:
        raise ValueError("MIXED_COST_RESOLUTION_WITHOUT_ORIGINAL")
    day = history.opened_at.astimezone(ZoneInfo("America/New_York")).date()
    end = history.captured_at.astimezone(ZoneInfo("America/New_York")).date()
    while day <= end:
        for kind in ("DATA", "HOST", "OPERATING"):
            if (day.isoformat(), kind) not in allocations:
                unknown.append("missing-" + kind + ":" + day.isoformat())
        day += timedelta(days=1)
    if unknown:
        blockers.append("MIXED_COST_UNKNOWN")
    day = _day(history.captured_at)
    daily_loss = max(
        ZERO, policy.daily_loss_limit + state.daily_net_pnl.get(day, ZERO) - daily.get(day, ZERO)
    )
    total_loss = max(ZERO, policy.total_loss_limit + state.realized_pnl - state.fees_paid - cost)
    if not daily_loss or not total_loss:
        blockers.append("MIXED_LOSS_BUDGET_EXHAUSTED")
    projection_type = portfolio.PortfolioProjection if multiple else CashProjection
    return projection_type(
        **({"commitments": commitments} if multiple else {}),
        ledger=state,
        reserved_cash=reserved,
        available_settled_cash=max(ZERO, state.settled_cash - reserved),
        known_cost=cost,
        unknown_cost_ids=tuple(unknown),
        daily_cost=daily,
        net_realized_pnl=None if unknown else state.realized_pnl - state.fees_paid - cost,
        daily_loss_available=None if unknown else daily_loss,
        total_loss_available=None if unknown else total_loss,
        entry_blockers=tuple(blockers),
    )


def _reservations(history, state, intents, quantities, debits):
    p, stock, option = history.policy, state.stock_position, state.position
    reserved, blockers = ZERO, []
    if stock is not None:
        reserved = stock.quantity * p.stocks.exit_fee_per_share + (
            stock.quantity / p.stocks.share_step * p.stocks.exit_fee_per_order
        )
    if option is not None:
        reserved = option.quantity * (
            p.options.exit_fee_per_contract + p.options.exit_fee_per_order
        )
    if stock or option:
        blockers.append("MIXED_POSITION_OWNED")
    held_entry = stock.entry.client_id if stock else option.entry_client_id if option else None
    for item in history.reservations:
        intent = item.intent
        _validate_intent(p, intent)
        if not history.opened_at <= intent.prepared_at <= history.captured_at:
            raise ValueError("MIXED_FUTURE_RESERVATION")
        previous = intents.get(intent.client_id)
        if previous is not None and previous != intent:
            raise ValueError("MIXED_RESERVATION_INTENT_CHANGED")
        quantity = quantities.get(intent.client_id, ZERO)
        if (
            quantity >= intent.quantity
            or (item.status == "PARTIAL" and not quantity)
            or (quantity and item.status in {"PREPARED", "SUBMITTING", "OPEN"})
        ):
            raise ValueError("MIXED_RESERVATION_FILL_CONFLICT")
        if intent.side == "BUY":
            if held_entry is not None and held_entry != intent.client_id:
                raise ValueError("MIXED_CROSS_INSTRUMENT_RESERVATION")
            full = (
                intent.approved_full_premium_loss
                if isinstance(intent, OptionIntent)
                else (intent.approved_entry_debit + intent.reserved_exit_fee)
            )
            reserved = max(reserved, full - debits.get(intent.client_id, ZERO))
        elif (
            held_entry is None
            or (
                isinstance(intent, StockIntent)
                and (stock is None or stock.instrument != intent.instrument)
            )
            or (
                isinstance(intent, OptionIntent)
                and (option is None or option.contract != intent.instrument.contract)
            )
            or intent.closing_entry_client_id != held_entry
        ):
            raise ValueError("MIXED_RESERVATION_UNOWNED_SALE")
        elif intent.quantity - quantity > (stock.quantity if stock else option.quantity):
            raise ValueError("MIXED_RESERVATION_OVERSELL")
        blockers.append("MIXED_ORDER_UNRESOLVED")
    if reserved > state.settled_cash:
        blockers.append("MIXED_EXIT_RESERVE_UNFUNDED")
    return reserved, blockers


def verify_extension(previous: CashHistory, current: CashHistory) -> CashProjection:
    """Require an immutable complete prefix before accepting a later projection.

    This verifies supplied native evidence. It does not authenticate a terminal
    receipt, authorize cancellation or resolve an ambiguous attempt by itself.
    """
    from app.mixed.portfolio_accounting import parse_history

    previous = parse_history(previous)
    current = parse_history(current)
    reconstruct(previous)
    result = reconstruct(current)
    for key in ("version", "account_id", "population_id", "venue_id", "policy", "opened_at"):
        if getattr(previous, key) != getattr(current, key):
            raise ValueError("MIXED_FROZEN_IDENTITY_CHANGED")
    if current.captured_at < previous.captured_at:
        raise ValueError("MIXED_CAPTURE_REGRESSION")
    for key in ("events", "costs", "cost_resolutions", "terminals"):
        old, new = getattr(previous, key), getattr(current, key)
        if key == "events":
            old = tuple(sorted(old, key=lambda e: _record(e).sequence))
            new = tuple(sorted(new, key=lambda e: _record(e).sequence))
        if new[: len(old)] != old:
            raise ValueError("MIXED_IMMUTABLE_HISTORY_CHANGED")
        for item in new[len(old) :]:
            at = (
                _record(item).occurred_at
                if key == "events"
                else item.recorded_at
                if key == "cost_resolutions"
                else item.observed_at
                if key == "terminals"
                else item.occurred_at
            )
            if at < previous.captured_at:
                raise ValueError("MIXED_NEW_HISTORY_BACKDATED")
    for item in previous.reservations:
        new = next(
            (r for r in current.reservations if r.intent.client_id == item.intent.client_id), None
        )
        if new is not None:
            if new.intent != item.intent:
                raise ValueError("MIXED_RESERVATION_ORIGINAL_CHANGED")
            order = ("PREPARED", "SUBMITTING", "UNKNOWN", "OPEN", "PARTIAL")
            # UNKNOWN may follow an earlier OPEN/PARTIAL when reconciliation fails.
            if new.status != "UNKNOWN" and order.index(new.status) < order.index(item.status):
                raise ValueError("MIXED_RESERVATION_STATUS_REGRESSION")
        else:
            terminal = next(
                (t for t in current.terminals if t.intent.client_id == item.intent.client_id), None
            )
            if terminal is None or terminal.intent != item.intent:
                raise ValueError("MIXED_RESERVATION_DISAPPEARED_WITHOUT_TERMINAL")
    return result
