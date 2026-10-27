"""Versioned, immutable local evidence; absent timestamps stay absent."""

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import ConfigDict, Field, model_validator

from app.options.models import Money, Name, OptionRecord, Symbol

State = Literal["CLEAR", "CAUTION", "BLOCK_NEW_ENTRIES", "UNKNOWN"]


class Event(OptionRecord):
    source: Name
    source_version: Name
    event_id: Name
    revision: Name
    revision_sequence: int | None = Field(default=None, ge=0)
    # Cross-provider equivalence requires an explicitly reviewed mapping. Titles
    # alone never merge a decision and a related press conference.
    canonical_key: Name | None = None
    category: Name
    title: str = Field(min_length=1, max_length=512)
    scope: Literal["MARKET", "SYMBOL"]
    symbols: tuple[Symbol, ...] = ()
    source_at: datetime | None
    received_at: datetime
    starts_at: datetime
    ends_at: datetime
    timezone: Name
    precision: Literal["EXACT", "DATE", "RANGE"]
    importance: Literal["HIGH", "MEDIUM", "UNKNOWN"]
    status: Literal["SCHEDULED", "CANCELLED", "TENTATIVE"] = "SCHEDULED"
    complete: bool
    evidence_ref: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def valid(self):
        ZoneInfo(self.timezone)
        if self.ends_at < self.starts_at:
            raise ValueError("Ordered event interval required")
        if (self.scope == "SYMBOL") != bool(self.symbols):
            raise ValueError("Explicit affected symbols required only for symbol events")
        if self.source_at is not None and self.source_at > self.received_at:
            raise ValueError("Future source revision")
        return self


class Coverage(OptionRecord):
    source: Name
    source_version: Name
    dataset: Name
    scope: Literal["MARKET", "SYMBOL"]
    symbols: tuple[Symbol, ...] = ()
    starts_at: datetime
    ends_at: datetime
    checked_at: datetime
    # This is retrieval freshness, not the age of the calendar's last revision.
    fresh_until: datetime
    status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE", "CONFLICT"]
    issues: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def valid(self):
        if self.starts_at >= self.ends_at or self.checked_at >= self.fresh_until:
            raise ValueError("Positive coverage and freshness intervals required")
        if (self.scope == "SYMBOL") != bool(self.symbols):
            raise ValueError("Coverage symbol scope mismatch")
        return self


class MarketSample(OptionRecord):
    source: Name
    source_version: Name
    evidence_ref: Name
    instrument_id: Name
    symbol: Symbol
    asset: Literal["STOCK", "OPTION", "INDEX"]
    source_at: datetime
    received_at: datetime
    bid: Money | None = Field(default=None, ge=0)
    ask: Money | None = Field(default=None, ge=0)
    bid_size: Money | None = Field(default=None, ge=0)
    ask_size: Money | None = Field(default=None, ge=0)
    reference_price: Money | None = Field(default=None, gt=0)
    reference_at: datetime | None = None
    entitlement: Literal["REALTIME", "DELAYED", "INDICATIVE", "UNKNOWN"]
    complete: bool


class Session(OptionRecord):
    day: date
    opens_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def ordered(self):
        if self.opens_at >= self.closes_at:
            raise ValueError("Ordered session required")
        return self


class Volatility(OptionRecord):
    source: Name
    source_version: Name
    symbol: Symbol
    observed_date: date
    value: Money = Field(gt=0)
    received_at: datetime
    frequency: Literal["DAILY_CLOSE"] = "DAILY_CLOSE"
    evidence_ref: str


class Snapshot(OptionRecord):
    version: Literal["event-snapshot-v1"] = "event-snapshot-v1"
    sequence: int = Field(gt=0)
    published_at: datetime
    policy_hash: Name
    events: tuple[Event, ...] = Field(default=(), max_length=10000)
    coverage: tuple[Coverage, ...] = Field(default=(), max_length=256)
    samples: tuple[MarketSample, ...] = Field(default=(), max_length=128)
    sessions: tuple[Session, ...] = Field(default=(), max_length=400)
    volatility: tuple[Volatility, ...] = Field(default=(), max_length=8)
    issues: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def available(self):
        clocks = [e.received_at for e in self.events]
        clocks += [c.checked_at for c in self.coverage]
        clocks += [s.received_at for s in self.samples]
        clocks += [v.received_at for v in self.volatility]
        if any(t > self.published_at for t in clocks):
            raise ValueError("Snapshot cannot contain future received evidence")
        if len({s.day for s in self.sessions}) != len(self.sessions):
            raise ValueError("Duplicate session dates")
        return self


class Window(OptionRecord):
    category: Name
    before_seconds: int = Field(ge=0, le=86400)
    after_seconds: int = Field(ge=0, le=86400)


class Policy(OptionRecord):
    model_config = ConfigDict(validate_default=True)
    version: Literal["event-awareness-research-v1"] = "event-awareness-research-v1"
    label: Literal["PROVISIONAL_RESEARCH_NOT_VALIDATED"] = "PROVISIONAL_RESEARCH_NOT_VALIDATED"
    mode: Literal["OBSERVATION_ONLY"] = "OBSERVATION_ONLY"
    windows: tuple[Window, ...] = (
        Window(category="macro", before_seconds=900, after_seconds=1800),
        Window(category="company", before_seconds=3600, after_seconds=3600),
    )
    required_market_datasets: tuple[Name, ...] = ("macro.us.high_impact", "session.xnys")
    required_company_datasets: tuple[Name, ...] = ("company.earnings",)
    market_proxies: tuple[Symbol, ...] = ("SPY", "QQQ")
    quote_max_age_seconds: int = Field(default=10, gt=0, le=300)
    quote_receive_lag_seconds: int = Field(default=2, gt=0, le=60)
    reference_max_age_seconds: int = Field(default=300, gt=0, le=3600)
    stock_spread_caution: Money = Field(default=".005", gt=0, le=1)
    stock_spread_block: Money = Field(default=".01", gt=0, le=1)
    option_spread_caution: Money = Field(default=".10", gt=0, le=1)
    option_spread_block: Money = Field(default=".20", gt=0, le=1)
    price_move_caution: Money = Field(default=".01", gt=0, le=1)
    price_move_block: Money = Field(default=".02", gt=0, le=1)
    minimum_displayed_size: Money = Field(default="1", gt=0)
    open_caution_seconds: int = Field(default=300, ge=0)
    entry_close_buffer_seconds: int = Field(default=1800, ge=0)
    max_assessment_seconds: int = Field(default=10, gt=0, le=60)
    max_local_events: int = Field(default=256, ge=1, le=512)
    volatility_daily_max_age_days: int = Field(default=4, ge=1, le=10)
    overnight_carry: Literal[False] = False
    unsupported: tuple[Name, ...] = (
        "UNSCHEDULED_NEWS_AND_GEOPOLITICS",
        "COMPANY_NON_EARNINGS_EVENTS",
        "FX_AND_CROSS_ASSET_STRESS",
        "INTRADAY_VOLATILITY",
        "VENUE_HALTS_AND_EMERGENCY_CLOSURES",
    )

    @model_validator(mode="after")
    def ordered(self):
        for name in ("stock_spread", "option_spread", "price_move"):
            if getattr(self, name + "_caution") > getattr(self, name + "_block"):
                raise ValueError("Ordered stress thresholds required")
        if len({w.category for w in self.windows}) != len(self.windows):
            raise ValueError("Unique window categories required")
        return self


class Request(OptionRecord):
    population_id: Name
    decision_id: Name
    family: Literal["DEGEN", "SWING", "SCOPE"]
    symbol: Symbol
    instrument_id: Name
    underlying_kind: Literal["EQUITY", "ETF", "INDEX"]
    evaluated_at: datetime
    holding_until: datetime

    @model_validator(mode="after")
    def horizon(self):
        if self.holding_until < self.evaluated_at:
            raise ValueError("Holding coverage ends before assessment")
        return self


class Finding(OptionRecord):
    state: State
    reason: Name
    scope: Literal["MARKET", "SYMBOL"]
    symbols: tuple[Symbol, ...] = ()
    evidence: tuple[str, ...] = ()


class Assessment(OptionRecord):
    version: Literal["event-assessment-v1"] = "event-assessment-v1"
    policy_version: Name
    policy_hash: Name
    snapshot_sequence: int | None
    snapshot_hash: Name | None
    request: Request
    state: State
    market_state: State
    symbol_state: State
    valid_until: datetime
    findings: tuple[Finding, ...]
    unsupported: tuple[Name, ...]
    would_block_new_entries: bool
    would_restrict_exposure: bool
    would_review_held_position: bool
    would_restrict_carry: bool
    mode: Literal["OBSERVATION_ONLY"] = "OBSERVATION_ONLY"
    authority: Literal[False] = False
    live_enabled: Literal[False] = False
    trade_approval: Literal[False] = False
