"""Observed Scope quote lifecycle; locked geometry, no inferred bars or trade authority."""

from app.options.models import parse_underlying
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import fingerprint
from app.options.governor import _fresh
from app.options.models import IndexReference, Name, OptionRecord, UnderlyingObservation, paper_market_evidence
from app.options.scope_structure import ScopeGeometry

TERMINALS = {"INVALIDATED_UNFILLED", "OBJECTIVE_CONSUMED_UNFILLED", "EXPIRED_UNFILLED"}


class ScopeQuoteReview(OptionRecord):
    version: Literal["scope-observed-quotes-v1"] = "scope-observed-quotes-v1"
    evaluated_at: datetime
    geometry: ScopeGeometry
    limits_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: UnderlyingObservation | None
    status: Literal[
        "OBSERVED",
        "REJECTED",
        "INVALIDATED_UNFILLED",
        "OBJECTIVE_CONSUMED_UNFILLED",
        "EXPIRED_UNFILLED",
    ]
    reasons: tuple[Name, ...]
    authority: Literal[False] = False
    live_enabled: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "REJECTED":
            if not self.reasons:
                raise ValueError("Rejected quote requires a reason")
        elif self.status == "EXPIRED_UNFILLED":
            if self.reasons != ("SCOPE_WATCH_ENTRY_CUTOFF",):
                raise ValueError("Expiry requires its cutoff reason")
        elif (
            self.quote is None
            or self.reasons
            or self.status != price_status(self.geometry, self.quote)
        ):
            raise ValueError("Scope quote classification must match original geometry")
        return self


def price_status(g, quote):
    call = g.right == "CALL"
    if quote.bid <= g.invalidation if call else quote.ask >= g.invalidation:
        return "INVALIDATED_UNFILLED"
    if quote.bid >= g.target_two if call else quote.ask <= g.target_two:
        return "OBJECTIVE_CONSUMED_UNFILLED"
    return "OBSERVED"


def review_quote(record, quote, limits, now, *, price_options=False):
    g = ScopeGeometry.model_validate(record["geometry"])
    cutoff = datetime.fromisoformat(record["locked_frame"]["session"]["entry_cutoff_at"])
    reasons = []
    if now >= cutoff:
        status, reasons = "EXPIRED_UNFILLED", ["SCOPE_WATCH_ENTRY_CUTOFF"]
    else:
        prior = record.get("last_observed_quote")
        if (
            quote is None
            or quote.symbol != "SPX"
            or quote.source != limits.underlying_source
            or not quote.complete
            or (not paper_market_evidence(quote) if price_options else quote.entitlement != "REALTIME")
            or (isinstance(quote, IndexReference) and not price_options)
            or not limits.minimum_underlying_price <= quote.bid <= quote.ask
            or quote.source_at
            < max(datetime.fromisoformat(record[k]) for k in ("called_at", "reviewed_through"))
            or not _fresh(
                quote.source_at,
                quote.received_at,
                now,
                limits.quote_max_age_seconds,
                limits.max_receive_lag_seconds,
            )
        ):
            reasons.append("SCOPE_WATCH_QUOTE_UNAVAILABLE_OR_STALE")
        elif prior is not None:
            previous = parse_underlying(prior)
            if quote.source_at < previous.source_at or (
                quote.source_at == previous.source_at and quote != previous
            ):
                reasons.append("SCOPE_WATCH_QUOTE_CLOCK_OR_CONTENT_CONFLICT")
        status = "REJECTED" if reasons else price_status(g, quote)
    return ScopeQuoteReview(
        evaluated_at=now,
        geometry=g,
        limits_hash=fingerprint(limits),
        quote=quote,
        status=status,
        reasons=tuple(reasons),
    )
