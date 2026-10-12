"""Shared pure mandatory position protection; no model or execution authority."""

from datetime import timedelta
from decimal import Context, localcontext

from app.options.governor import _fresh


def assess_position(p, quote, underlying, limits, policy, *, now):
    """Caller supplies validated records and an aware clock. Never clears a latch."""
    with localcontext(Context(prec=192)):
        return _assess(p, quote, underlying, limits, policy, now)


def _assess(p, quote, underlying, limits, policy, now):
    reason, issue = p.exit_reason, None
    if now >= p.contract.last_trading_at - timedelta(seconds=policy.expiry_guard_seconds):
        reason = reason or "EXPIRY_GUARD"
    if now >= p.exit_at:
        reason = reason or "TIME_EXIT"
    underlying_ok = (
        underlying is not None
        and underlying.symbol == p.contract.underlying
        and underlying.source == limits.underlying_source
        and underlying.complete
        and underlying.entitlement == "REALTIME"
        and underlying.bid <= underlying.ask
        and _fresh(
            underlying.source_at,
            underlying.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    )
    quote_ok = (
        quote is not None
        and quote.instrument.contract == p.contract
        and quote.instrument.provider == limits.provider
        and quote.source == limits.option_source
        and quote.complete
        and quote.entitlement == "REALTIME"
        and quote.bid is not None
        and quote.bid > 0
        and quote.bid_size > 0
        and (quote.ask is None or quote.ask >= quote.bid)
        and _fresh(
            quote.source_at,
            quote.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    )
    if underlying_ok and (
        (p.contract.right == "CALL" and underlying.bid <= p.tightened_underlying_invalidation)
        or (p.contract.right == "PUT" and underlying.ask >= p.tightened_underlying_invalidation)
    ):
        reason = reason or "UNDERLYING_INVALIDATION"
    if quote_ok and quote.bid * p.quantity * p.contract.multiplier <= p.basis * (
        1 - policy.premium_catastrophe_fraction
    ):
        reason = reason or "PREMIUM_CATASTROPHE"
    if (
        underlying_ok
        and p.entry_protection is not None
        and (
            (p.contract.right == "CALL" and underlying.bid >= p.entry_protection.underlying_target)
            or (
                p.contract.right == "PUT" and underlying.ask <= p.entry_protection.underlying_target
            )
        )
    ):
        reason = reason or "UNDERLYING_TARGET"
    if not quote_ok:
        issue = "OPTION_UNPRICED_OR_STALE"
    elif not underlying_ok:
        issue = "UNDERLYING_UNAVAILABLE_OR_STALE"
    p = p.model_copy(
        update={
            "exit_reason": reason,
            "exit_required_at": p.exit_required_at or (now if reason else None),
            "supervision_issue": issue,
        }
    )
    return p
