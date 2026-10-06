"""Pure sampled-quote supervision. This module has no order or broker authority."""

from datetime import timedelta

from app.execution.models import PositionManagement


def assess_position(position, management: PositionManagement, packet, window, now, max_age):
    """Return a persistent exit requirement or an explicit inability to supervise."""
    issue = None
    quote = next((c.quote for c in packet.candidates if c.quote.symbol == position.symbol), None)
    if management.last_supervised_at is not None and now < management.last_supervised_at:
        issue = "SUPERVISION_TIME_REGRESSION"
    elif (
        packet.as_of.tzinfo is None
        or packet.as_of.utcoffset() is None
        or not 0 <= (now - packet.as_of).total_seconds() <= max_age
    ):
        issue = "INVALID_SUPERVISION_PACKET_TIME"
    elif window is None:
        issue = "OUTSIDE_REGULAR_SESSION"
    elif quote is None:
        issue = "POSITION_QUOTE_MISSING"
    elif (
        quote.timestamp.tzinfo is None
        or quote.timestamp.utcoffset() is None
        or not 0 <= (now - quote.timestamp).total_seconds() <= max_age
    ):
        issue = "POSITION_QUOTE_NOT_FRESH"
    elif management.last_quote_at is not None and quote.timestamp < management.last_quote_at:
        issue = "POSITION_QUOTE_TIME_REGRESSION"
    elif quote.bid > quote.ask:
        issue = "INSANE_POSITION_QUOTE"
    if issue:
        return management.model_copy(update={"supervision_issue": issue}), None
    reason = management.exit_reason
    if reason is None:
        reason = (
            "INVALIDATION"
            if quote.bid <= position.original_invalidation
            else "MISSED_SESSION_EXIT"
            if not management.hold_overnight and management.session_date != window.session_date
            else "SESSION_EXIT"
            if not management.hold_overnight and now >= window.closes_at - timedelta(minutes=15)
            else None
        )
    return management.model_copy(
        update={
            "exit_reason": reason,
            "exit_required_at": management.exit_required_at or (now if reason else None),
            "last_supervised_at": now,
            "last_quote_at": quote.timestamp,
            "supervision_issue": None,
        }
    ), quote
