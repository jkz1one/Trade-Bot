"""Order-free shared-account stock admission and existing option-account projection.

Native ownership/reconciliation is an explicit caller assertion, as in the option
governor. Neither function authenticates that assertion or grants dispatch rights.
"""

from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext

from app.mixed.accounting import reconstruct
from app.mixed.models import CashHistory, StockAdmission, StockProposal, StockQuote
from app.options.engine import clock, fingerprint
from app.options.governor import _fresh
from app.options.models import EquityHolding, OptionAccount, OptionHolding, SessionWindow

ZERO = Decimal(0)


def option_account(history, *, reconciled=False, entry_halted=False):
    """Expose the same balances/occupancy to native option admission, never a clone."""
    history = CashHistory.model_validate(history.model_dump(warnings=False))
    result = reconstruct(history)
    return _account(history, result, reconciled, entry_halted)


def _account(history, result, reconciled, entry_halted):
    state = result.ledger
    holding = None
    if state.position is not None:
        holding = OptionHolding.model_validate(
            {
                k: v
                for k, v in state.position.model_dump().items()
                if k in OptionHolding.model_fields
            }
        )
    elif state.stock_position is not None:
        holding = EquityHolding(
            symbol=state.stock_position.instrument.symbol, quantity=state.stock_position.quantity
        )
    return OptionAccount(
        account_id=history.account_id,
        population_id=history.population_id,
        snapshot_id=fingerprint(history),
        captured_at=history.captured_at,
        complete=True,
        reconciled=reconciled,
        cash=state.cash,
        settled_cash=state.settled_cash,
        reserved_cash=min(state.settled_cash, result.reserved_cash),
        daily_loss_available=result.daily_loss_available or ZERO,
        total_loss_available=result.total_loss_available or ZERO,
        budgets_known=not result.unknown_cost_ids,
        position=holding,
        working_orders=len(history.reservations),
        unsupported_exposure=False,
        entry_halted=entry_halted,
        entry_blockers=result.entry_blockers,
    )


def admit_stock(proposal, quote, history, session, *, now, reconciled=False, entry_halted=False):
    """Pure deterministic review; quantities use the common complete loss envelope."""
    now = clock(now)
    proposal = StockProposal.model_validate(proposal.model_dump(warnings=False))
    history = CashHistory.model_validate(history.model_dump(warnings=False))
    result = reconstruct(history)
    quote = (
        StockQuote.model_validate(quote.model_dump(warnings=False)) if quote is not None else None
    )
    session = (
        SessionWindow.model_validate(session.model_dump(warnings=False))
        if session is not None
        else None
    )
    with localcontext(Context(prec=192)):
        return _admit(proposal, quote, history, result, session, now, reconciled, entry_halted)


def _admit(proposal, q, history, result, session, now, reconciled, entry_halted):
    fields = {
        "action": proposal.action,
        "history_hash": fingerprint(history),
        "proposal_hash": fingerprint(proposal),
        "approved_at": now,
    }
    if proposal.action == "HOLD":
        return StockAdmission(outcome="HOLD", **fields)
    p, limits = history.policy.stocks, history.policy.options
    account = _account(history, result, reconciled, entry_halted)
    reasons = []
    if not account.reconciled or not timedelta(0) <= now - history.captured_at < timedelta(
        seconds=limits.account_max_age_seconds
    ):
        reasons.append("MIXED_FRESH_RECONCILIATION_REQUIRED")
    i = proposal.instrument
    if (
        i.provider != p.provider
        or i.symbol not in p.allowed_symbols
        or not i.metadata_complete
        or not i.tradable
    ):
        reasons.append("MIXED_STOCK_INSTRUMENT_UNSUPPORTED")
    if q is None or (
        q.instrument != i
        or q.source != p.quote_source
        or not q.complete
        or q.entitlement != "REALTIME"
        or not _fresh(
            q.source_at, q.received_at, now, p.quote_max_age_seconds, p.max_receive_lag_seconds
        )
    ):
        reasons.append("MIXED_STOCK_QUOTE_REQUIRED")
    if session is None or (
        session.underlying != i.symbol
        or session.source != limits.session_source
        or not session.opens_at <= now < session.closes_at
    ):
        reasons.append("MIXED_STOCK_SESSION_REQUIRED")
    if history.reservations:
        reasons.append("MIXED_ORDER_UNRESOLVED")
    closing = proposal.action == "CLOSE"
    position = result.ledger.stock_position
    if closing:
        if position is None or position.instrument != i:
            reasons.append("MIXED_STOCK_EXACT_OWNERSHIP_REQUIRED")
    else:
        reasons.extend(result.entry_blockers)
        if entry_halted:
            reasons.append("MIXED_ENTRY_HALTED")
        if not proposal.source_at <= now < proposal.valid_until:
            reasons.append("MIXED_STOCK_ORIGINAL_SOURCE_EXPIRED")
        if session is not None and now >= session.entry_cutoff_at:
            reasons.append("MIXED_STOCK_ENTRY_CUTOFF")
        if q is not None and (
            q.bid < p.minimum_price or (q.ask - q.bid) / q.ask > p.max_spread_fraction
        ):
            reasons.append("MIXED_STOCK_ENTRY_PRICE_OR_SPREAD")
    if reasons:
        return StockAdmission(outcome="REJECTED", reasons=tuple(dict.fromkeys(reasons)), **fields)
    size = q.bid_size if closing else q.ask_size
    if size is None:
        return StockAdmission(outcome="REJECTED", reasons=("MIXED_STOCK_SIZE_UNKNOWN",), **fields)
    price = (q.bid if closing else q.ask) * (1 + (-1 if closing else 1) * p.slippage_bps / 10000)
    price = (price / i.tick).to_integral_value(
        rounding=ROUND_FLOOR if closing else ROUND_CEILING
    ) * i.tick
    if price <= 0:
        return StockAdmission(outcome="REJECTED", reasons=("MIXED_STOCK_PRICE_INVALID",), **fields)
    if (
        not closing
        and not proposal.original_invalidation < q.bid <= price < proposal.original_target
    ):
        return StockAdmission(
            outcome="REJECTED", reasons=("MIXED_STOCK_ORIGINAL_GEOMETRY_INVALID",), **fields
        )
    if closing:
        quantity = min(position.quantity, size)
    else:
        # Both kinds share the same settled funds and remaining full-loss budget.
        # A stop is protection, not a guarantee permitting credit or extra capital.
        budget = min(
            result.available_settled_cash,
            p.max_account_exposure,
            result.daily_loss_available,
            result.total_loss_available,
        )
        per_share = (
            price
            + p.entry_fee_per_share
            + p.exit_fee_per_share
            + p.exit_fee_per_order / p.share_step
        )
        quantity = min(
            p.max_shares,
            size,
            (budget - p.entry_fee_per_order) / per_share,
            (p.max_entry_debit - p.entry_fee_per_order) / (price + p.entry_fee_per_share),
        )
    quantity = (quantity / p.share_step).to_integral_value(rounding=ROUND_FLOOR) * p.share_step
    if quantity <= 0:
        return StockAdmission(outcome="REJECTED", reasons=("MIXED_STOCK_NO_FUNDED_SIZE",), **fields)
    if closing:
        fee = p.exit_fee_per_order + quantity * p.exit_fee_per_share
        if quantity * price + result.ledger.settled_cash < fee:
            return StockAdmission(
                outcome="REJECTED", reasons=("MIXED_STOCK_EXIT_FEE_UNFUNDED",), **fields
            )
        debit, reserve = ZERO, ZERO
    else:
        debit = quantity * (price + p.entry_fee_per_share) + p.entry_fee_per_order
        reserve = quantity * p.exit_fee_per_share + quantity / p.share_step * p.exit_fee_per_order
    expiry = min(
        now + timedelta(seconds=p.approval_lifetime_seconds),
        session.closes_at,
        history.captured_at + timedelta(seconds=limits.account_max_age_seconds),
        q.source_at + timedelta(seconds=p.quote_max_age_seconds),
    )
    if not closing:
        expiry = min(expiry, proposal.valid_until, proposal.exit_at, session.entry_cutoff_at)
    return StockAdmission(
        outcome="APPROVED",
        approval_expires_at=expiry,
        quantity=quantity,
        limit_price=price,
        entry_debit=debit,
        reserved_exit_fee=reserve,
        **fields,
    )
