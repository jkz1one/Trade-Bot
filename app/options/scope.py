"""Pure Scope evidence preflight. Coverage is not a setup, admission or trade authority."""

from datetime import UTC, date, datetime, timedelta
from decimal import Context, localcontext
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.options.degen import DegenBar
from app.options.engine import fingerprint
from app.options.governor import _fresh, _supported
from app.options.models import Evidence, Money, Name, OptionQuote, OptionRecord
from app.options.selection import ContractMetadata

ScopeGroup = Literal[
    "provider_readiness",
    "technical_structure",
    "options_analytics",
    "dealer_structure",
    "options_flow",
    "cross_market_agreement",
    "economic_events",
    "broad_market_news",
    "spxw_contracts",
]
SCOPE_GROUPS = get_args(ScopeGroup)
MARKETS = ("SPX", "SPY", "QQQ")
NY = ZoneInfo("America/New_York")


class ScopeSource(OptionRecord):
    kind: ScopeGroup
    source: Name
    max_age_seconds: int = Field(gt=0, le=86400, strict=True)


class ScopeHistorySource(OptionRecord):
    symbol: Literal["SPX", "SPY", "QQQ"]
    source: Name


class ScopePreflightPolicy(OptionRecord):
    version: Literal["scope-preflight-v1"] = "scope-preflight-v1"
    # Explicit fixture/research enrollment; no unmeasured provider defaults.
    sources: tuple[ScopeSource, ...] = Field(min_length=9, max_length=9)
    history_sources: tuple[ScopeHistorySource, ...] = Field(min_length=3, max_length=3)
    session_source: Name
    provider: Name
    metadata_source: Name
    quote_source: Name
    max_receive_lag_seconds: int = Field(ge=0, le=60, strict=True)
    max_evidence_skew_seconds: int = Field(ge=0, le=60, strict=True)
    max_history_age_seconds: int = Field(gt=0, le=600, strict=True)
    max_contract_age_seconds: int = Field(gt=0, le=60, strict=True)
    max_spread_fraction: Money = Field(gt=0, le=1)

    @model_validator(mode="after")
    def complete_bindings(self):
        if {s.kind for s in self.sources} != set(SCOPE_GROUPS) or {
            s.symbol for s in self.history_sources
        } != set(MARKETS):
            raise ValueError(
                "All nine unique Scope sources and three unique history sources required"
            )
        return self


class ScopeSession(OptionRecord):
    """Explicit reviewed index session input, not inferred XNYS/weekday entitlement."""

    source: Name
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    session_date: date
    opens_at: datetime
    entry_starts_at: datetime
    entry_cutoff_at: datetime
    protect_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def ordered_session(self):
        clocks = (
            self.opens_at,
            self.entry_starts_at,
            self.entry_cutoff_at,
            self.protect_at,
            self.closes_at,
        )
        if not (
            self.opens_at
            < self.entry_starts_at
            < self.entry_cutoff_at
            < self.protect_at
            <= self.closes_at
        ) or any(t.astimezone(NY).date() != self.session_date for t in clocks):
            raise ValueError("Ordered same-session index entry and protection boundaries required")
        return self


class ScopeEvidence(Evidence):
    """Coverage attestation bound to retained normalized payload, not its semantic verdict."""

    kind: ScopeGroup
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]


class ScopeHistory(Evidence):
    symbol: Literal["SPX", "SPY", "QQQ"]
    interval_seconds: Literal[300] = 300
    bounds: Literal["regular"] = "regular"
    bars: tuple[DegenBar, ...] = Field(max_length=96)


class ScopePreflightInput(OptionRecord):
    session: ScopeSession | None
    evidence: tuple[ScopeEvidence, ...] = Field(max_length=18)
    histories: tuple[ScopeHistory, ...] = Field(max_length=6)
    metadata: ContractMetadata | None
    quote: OptionQuote | None


class ScopeBlocker(OptionRecord):
    subject: Name
    code: Name


class ScopePreflight(OptionRecord):
    version: Literal["scope-preflight-v1"] = "scope-preflight-v1"
    evaluated_at: datetime
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["BLOCKED", "COVERAGE_COMPLETE"]
    authority: Literal[False] = False
    live_enabled: Literal[False] = False
    blockers: tuple[ScopeBlocker, ...]


def preflight_scope(frame, policy, *, now):
    """Check supplied coverage and exact identity without reading files or starting an owner."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware preflight clock required")
    now = now.astimezone(UTC)
    frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
    policy = ScopePreflightPolicy.model_validate(policy.model_dump(warnings=False))
    with localcontext(Context(prec=192)):
        return _preflight(frame, policy, now)


def _preflight(frame, policy, now):
    blockers = []

    def block(subject, code):
        blockers.append(ScopeBlocker(subject=subject, code=code))

    def current(item, source, age):
        return (
            item.source == source
            and item.complete
            and item.entitlement == "REALTIME"
            and _fresh(item.source_at, item.received_at, now, age, policy.max_receive_lag_seconds)
        )

    session = frame.session
    if session is None:
        block("session", "MISSING_INDEX_SESSION")
    elif (
        session.source != policy.session_source
        or session.session_date != now.astimezone(NY).date()
        or not session.entry_starts_at <= now < session.entry_cutoff_at
    ):
        block("session", "INDEX_SESSION_BINDING_OR_ENTRY_WINDOW")

    for binding in policy.sources:
        items = [e for e in frame.evidence if e.kind == binding.kind]
        if len(items) != 1:
            block(binding.kind, "MISSING_EVIDENCE" if not items else "DUPLICATE_EVIDENCE")
        elif items[0].status != "AVAILABLE" or not current(
            items[0], binding.source, binding.max_age_seconds
        ):
            block(binding.kind, "EVIDENCE_BINDING_COVERAGE_OR_FRESHNESS")

    market_clocks = []
    for binding in policy.history_sources:
        histories = [h for h in frame.histories if h.symbol == binding.symbol]
        if len(histories) != 1:
            block(binding.symbol, "MISSING_HISTORY" if not histories else "DUPLICATE_HISTORY")
            continue
        h = histories[0]
        if not current(h, binding.source, policy.max_history_age_seconds):
            block(binding.symbol, "HISTORY_BINDING_COVERAGE_OR_FRESHNESS")
        market_clocks.append(h.source_at)
        if session is None:
            continue
        completed_count = int(
            (min(now, session.closes_at) - session.opens_at).total_seconds() // 300
        )
        if (
            completed_count < 3
            or len(h.bars) != completed_count
            or any(
                bar.begins_at != session.opens_at + timedelta(minutes=5 * n)
                or bar.ends_at > min(now, h.source_at, h.received_at)
                or bar.interpolated
                for n, bar in enumerate(h.bars)
            )
        ):
            block(binding.symbol, "COMPLETED_SESSION_HISTORY_REQUIRED")

    metadata, quote = frame.metadata, frame.quote
    if metadata is None:
        block("contract", "MISSING_EXACT_SPXW_METADATA")
    else:
        instrument, c = metadata.instrument, metadata.instrument.contract
        if (
            instrument.provider != policy.provider
            or not instrument.metadata_complete
            or not instrument.option_tradable
            or not _supported(c)
            or c.underlying != "SPX"
            or c.root != "SPXW"
            or c.underlying_kind != "INDEX"
            or c.settlement_session != "PM"
            or c.expiration != now.astimezone(NY).date()
            or c.last_trading_at.astimezone(NY).date() != c.expiration
            or now >= c.last_trading_at
            or session is None
            or c.last_trading_at < session.protect_at
        ):
            block("contract", "EXACT_SPXW_ZERO_DTE_IDENTITY_OR_CUTOFF")
        if not current(metadata, policy.metadata_source, policy.max_contract_age_seconds):
            block("contract", "METADATA_BINDING_COVERAGE_OR_FRESHNESS")
        # No Degen delta band, premium tier or source score becomes a Scope admission rule.
        if metadata.delta is not None and (
            metadata.delta <= 0 if c.right == "CALL" else metadata.delta >= 0
        ):
            block("contract", "DELTA_DIRECTION_INCONSISTENT")
    if quote is None:
        block("quote", "MISSING_EXACT_SPXW_QUOTE")
    else:
        if metadata is None or quote.instrument != metadata.instrument:
            block("quote", "EXACT_INSTRUMENT_MISMATCH")
        if not current(quote, policy.quote_source, policy.max_contract_age_seconds):
            block("quote", "QUOTE_BINDING_COVERAGE_OR_FRESHNESS")
        market_clocks.append(quote.source_at)
        if (
            quote.bid is None
            or quote.ask is None
            or quote.bid <= 0
            or quote.ask < quote.bid
            or quote.bid_size == 0
            or quote.ask_size == 0
        ):
            block("quote", "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED")
        else:
            if 2 * (quote.ask - quote.bid) / (quote.ask + quote.bid) > policy.max_spread_fraction:
                block("quote", "SPREAD_EXCEEDS_FROZEN_BOUND")
            c = quote.instrument.contract
            if any(
                price % (c.tick_below_three if price < 3 else c.tick_at_or_above_three) != 0
                for price in (quote.bid, quote.ask)
            ):
                block("quote", "QUOTE_PRICE_OFF_CONTRACT_TICK")
    if len(market_clocks) == 4 and max(market_clocks) - min(market_clocks) > timedelta(
        seconds=policy.max_evidence_skew_seconds
    ):
        block("markets", "SPX_CONFIRMATION_QUOTE_CLOCK_SKEW")

    return ScopePreflight(
        evaluated_at=now,
        policy_hash=fingerprint(policy),
        input_hash=fingerprint(frame),
        status="BLOCKED" if blockers else "COVERAGE_COMPLETE",
        blockers=tuple(blockers),
    )
