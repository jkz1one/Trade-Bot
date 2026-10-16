"""Shared pure mandatory position protection; no model or execution authority."""

from datetime import timedelta
from decimal import Context, localcontext

from app.options.governor import _fresh
from app.options.lifecycle import EntryPremiumProtection


def verify_premium_binding(intent, approval):
    raw = approval.get("entry_premium_protection")
    protection = EntryPremiumProtection.model_validate(raw) if raw is not None else None
    if intent.entry_premium_protection != protection:
        raise ValueError("OPTION_ENTRY_PREMIUM_PROTECTION_CHANGED")
    if protection is not None and approval.get("origin") != "DETERMINISTIC":
        raise ValueError("OPTION_ENTRY_PREMIUM_DETERMINISTIC_ONLY")


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
    premium_fraction = policy.premium_catastrophe_fraction
    if p.entry_premium_protection is not None:
        premium_fraction = min(premium_fraction, p.entry_premium_protection.maximum_loss_fraction)
    if quote_ok and quote.bid * p.quantity * p.contract.multiplier <= p.basis * (
        1 - premium_fraction
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
    stage = p.target_exit_stage
    if underlying_ok and p.target_exit_schedule is not None and reason is None:
        for index, step in enumerate(p.target_exit_schedule.steps, 1):
            if (
                underlying.bid >= step.underlying_price
                if p.contract.right == "CALL"
                else underlying.ask <= step.underlying_price
            ):
                stage = max(stage, index)
    p = p.model_copy(
        update={
            "exit_reason": reason,
            "exit_required_at": p.exit_required_at or (now if reason else None),
            "supervision_issue": issue,
            "target_exit_stage": stage,
        }
    )
    return p
