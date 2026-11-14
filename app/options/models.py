"""Immutable options evidence. Account/policy inputs belong to software, never the model."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator, Field, StrictBool, StrictInt, field_validator, model_validator

from app.execution.models import Contract


def _decimal(value):
    if isinstance(value, (float, bool)):
        # Pydantic needs ValueError to report a structured validation failure.
        raise ValueError(  # noqa: TRY004
            "Money requires Decimal, decimal text or integer, never float/bool"
        )
    # Bound arithmetic/serialization resources without introducing binary rounding.
    try:
        amount = Decimal(value)
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError("Invalid decimal money") from None
    if (
        not amount.is_finite()
        or len(amount.as_tuple().digits) > 28
        or abs(amount.as_tuple().exponent) > 12
    ):
        raise ValueError("Finite money with at most 28 digits and scale/exponent 12 required")
    return amount


Money = Annotated[Decimal, BeforeValidator(_decimal)]
Count = Annotated[StrictInt, Field(ge=0, le=1_000_000)]
PositiveCount = Annotated[StrictInt, Field(gt=0, le=1_000_000)]
Symbol = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,15}$")]
Name = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S(?:[^\r\n]*\S)?$")]


class OptionRecord(Contract):
    @field_validator("*", mode="after")
    @classmethod
    def utc_times(cls, value):
        # Compare actual instants, including ambiguous local DST folds.
        return value.astimezone(UTC) if isinstance(value, datetime) else value


class OptionContract(OptionRecord):
    underlying: Symbol
    underlying_kind: Literal["EQUITY", "ETF", "INDEX"]
    underlying_market: Literal["US_LISTED", "US_INDEX", "OTC", "NON_US"]
    root: Symbol
    right: Literal["CALL", "PUT"]
    strike: Money = Field(gt=0)
    expiration: date
    multiplier: PositiveCount
    deliverable_kind: Literal["SHARES", "CASH"]
    deliverable_units: Count
    currency: Literal["USD"] = "USD"
    exercise_style: Literal["AMERICAN", "EUROPEAN"]
    settlement: Literal["PHYSICAL", "CASH"]
    settlement_session: Literal["AM", "PM"]
    last_trading_at: datetime
    expires_at: datetime
    settles_at: datetime
    adjusted: StrictBool
    tick_below_three: Money = Field(gt=0)
    tick_at_or_above_three: Money = Field(gt=0)

    @model_validator(mode="after")
    def chronology(self):
        if not self.last_trading_at <= self.expires_at <= self.settles_at:
            raise ValueError("Contract trading, expiry and settlement times must be ordered")
        if self.expires_at.astimezone(ZoneInfo("America/New_York")).date() != self.expiration:
            raise ValueError("Expiry timestamp must match the contract expiration date")
        return self

    @property
    def contract_id(self) -> str:
        # Normalize Decimal scale so 600 and 600.00 identify the same metadata.
        fields = self.model_dump(mode="json")
        for name in ("strike", "tick_below_three", "tick_at_or_above_three"):
            value = format(getattr(self, name), "f")
            fields[name] = value.rstrip("0").rstrip(".") if "." in value else value
        for name in ("last_trading_at", "expires_at", "settles_at"):
            fields[name] = getattr(self, name).astimezone(UTC).isoformat()

        return (
            "option-v1:"
            + hashlib.sha256(
                json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )


class OptionInstrument(OptionRecord):
    simulation_terms: Literal["STANDARD_ETF_INTRADAY_V1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    provider: Name
    instrument_id: Name
    contract: OptionContract
    metadata_complete: StrictBool
    option_tradable: StrictBool

    @model_validator(mode="after")
    def simulated_terms_boundary(self):
        if self.simulation_terms is not None and (
            self.provider != "robinhood" or self.contract.underlying not in {"SPY", "QQQ"}
            or self.contract.underlying_kind != "ETF" or self.contract.multiplier != 100
            or self.contract.deliverable_units != 100 or self.contract.adjusted
            or self.contract.exercise_style != "AMERICAN"
            or self.contract.settlement != "PHYSICAL"
            or self.contract.deliverable_kind != "SHARES"
        ):
            raise ValueError("Standard ETF simulation assumptions require unadjusted SPY/QQQ terms")
        return self


class Evidence(OptionRecord):
    simulation_basis: Literal["ROBINHOOD_OBSERVED_V1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    source: Name
    source_at: datetime
    received_at: datetime
    entitlement: Literal["REALTIME", "DELAYED", "INDICATIVE", "UNKNOWN"]
    complete: StrictBool

    @model_validator(mode="after")
    def observed_simulation_source(self):
        if self.simulation_basis is not None and (
            self.entitlement != "UNKNOWN" or self.source != "robinhood-mcp"
            or type(self).__name__ not in {
                "OptionQuote", "UnderlyingQuote", "OptionGreekObservation",
                "ContractMetadata", "OptionInventory", "DegenHistory", "StockQuote",
                "StockDailyHistory", "SwingHistory", "SwingBaseHistory", "SwingMAHistory",
                "SwingLevelHistory", "SwingBatchHistory", "SwingHourlyHistory",
                "ScopeHistory", "ScopeEvidence", "IndexReference",
            }
        ):
            raise ValueError("Observed simulation requires supported original Robinhood market evidence")
        return self


def paper_market_evidence(value):
    """PAPER evidence only: preserve UNKNOWN entitlement on observed simulation data.

    This is not a freshness/completeness/admission check or a LIVE entitlement.
    Callers must retain their separate size, source, clock and identity checks.
    """
    return value.entitlement == "REALTIME" or (
        value.entitlement == "UNKNOWN"
        and value.source == "robinhood-mcp"
        and value.simulation_basis == "ROBINHOOD_OBSERVED_V1"
        and type(value).__name__ in {
            "OptionQuote", "UnderlyingQuote", "OptionGreekObservation",
            "ContractMetadata", "OptionInventory", "DegenHistory", "StockQuote",
            "StockDailyHistory", "SwingHistory", "SwingBaseHistory", "SwingMAHistory",
            "SwingLevelHistory", "SwingBatchHistory", "SwingHourlyHistory",
            "ScopeHistory", "ScopeEvidence", "IndexReference",
        }
    )


class OptionGreekObservation(Evidence):
    """Explicit normalized units and provenance; absence is never a zero estimate."""

    instrument: OptionInstrument
    provenance: Literal["OBSERVED", "ESTIMATED", "UNAVAILABLE"]
    theta_unit: Literal["USD_PER_SHARE_PER_DAY"]
    volatility_unit: Literal["DECIMAL_FRACTION"]
    delta: Money | None = Field(default=None, ge=-1, le=1)
    theta: Money | None = None
    implied_volatility: Money | None = Field(default=None, ge=0)


class OptionQuote(Evidence):
    instrument: OptionInstrument
    bid: Money | None = Field(default=None, ge=0)
    ask: Money | None = Field(default=None, gt=0)
    bid_size: Count
    ask_size: Count
    greeks: OptionGreekObservation | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def greek_identity(self):
        if self.greeks is not None and self.greeks.instrument != self.instrument:
            raise ValueError("Greek observation must bind the exact quoted instrument")
        return self


class UnderlyingQuote(Evidence):
    # Optional executable share sizes; omitted legacy values retain their tape hashes.
    bid_size: Count | None = Field(default=None, exclude_if=lambda v: v is None)
    ask_size: Count | None = Field(default=None, exclude_if=lambda v: v is None)
    symbol: Symbol
    bid: Money = Field(gt=0)
    ask: Money = Field(gt=0)


class IndexReference(Evidence):
    """Non-executable SPX value for PAPER option barrier/protection arithmetic.

    Numerical bid/ask aliases support the existing conservative-reference math;
    they are properties, never serialized quotes, prices for SPX fills or sizes.
    """
    version: Literal["robinhood-spx-index-reference-v1"] = "robinhood-spx-index-reference-v1"
    instrument_id: Name
    symbol: Literal["SPX"] = "SPX"
    value: Money = Field(gt=0)
    original_source_time: str
    provider_updated_at: str | None
    receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: Literal["robinhood-mcp"] = "robinhood-mcp"
    entitlement: Literal["UNKNOWN"] = "UNKNOWN"
    complete: Literal[True] = True
    simulation_basis: Literal["ROBINHOOD_OBSERVED_V1"] = "ROBINHOOD_OBSERVED_V1"
    executable_book: Literal[False] = False

    @model_validator(mode="after")
    def original_clock(self):
        source = datetime.fromisoformat(self.original_source_time)
        if source.tzinfo is None or source != self.source_at or self.source_at > self.received_at:
            raise ValueError("Original aware SPX venue clock must match reference")
        return self

    @property
    def bid(self):
        return self.value

    @property
    def ask(self):
        return self.value

    @property
    def bid_size(self):
        return None

    @property
    def ask_size(self):
        return None


UnderlyingObservation = UnderlyingQuote | IndexReference


def parse_underlying(value):
    if isinstance(value, (UnderlyingQuote, IndexReference)):
        value = value.model_dump()
    cls = IndexReference if isinstance(value, dict) and value.get("version") == "robinhood-spx-index-reference-v1" else UnderlyingQuote
    return cls.model_validate(value)


class SessionWindow(OptionRecord):
    """Reviewed input, not a weekday/calendar inference or proof of a provider session."""

    source: Name
    underlying: Symbol
    opens_at: datetime
    entry_cutoff_at: datetime
    closes_at: datetime

    @model_validator(mode="after")
    def chronology(self):
        if not self.opens_at < self.entry_cutoff_at <= self.closes_at:
            raise ValueError("Explicit session entry window required")
        return self


class OptionProposal(OptionRecord):
    action: Literal["HOLD", "OPEN_LONG", "CLOSE"]
    contract: OptionContract | None = None
    underlying_invalidation: Money | None = Field(default=None, gt=0)
    max_entry_debit: Money | None = Field(default=None, gt=0)
    close_quantity: PositiveCount | None = Field(default=None, exclude_if=lambda v: v is None)
    thesis: str = Field(min_length=1, max_length=500)

    @field_validator("thesis")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A nonblank thesis is required")
        return value

    @model_validator(mode="after")
    def terms(self):
        if self.action != "HOLD" and self.contract is None:
            raise ValueError("An exact option contract is required")
        if self.action == "OPEN_LONG" and self.underlying_invalidation is None:
            raise ValueError("Opening requires original underlying invalidation")
        if self.close_quantity is not None and self.action != "CLOSE":
            raise ValueError("A requested close quantity applies only to CLOSE")
        return self


class OptionHolding(OptionRecord):
    kind: Literal["OPTION"] = "OPTION"
    contract: OptionContract
    quantity: PositiveCount
    original_underlying_invalidation: Money = Field(gt=0)


class EquityHolding(OptionRecord):
    kind: Literal["EQUITY"] = "EQUITY"
    symbol: Symbol
    quantity: Money = Field(gt=0)


class OptionAccount(OptionRecord):
    """Caller supplies authoritative reconciled PAPER truth, outside proposal evidence."""

    account_id: Name
    population_id: Name
    snapshot_id: Name
    captured_at: datetime
    complete: StrictBool
    reconciled: StrictBool
    cash: Money = Field(ge=0)
    settled_cash: Money = Field(ge=0)
    reserved_cash: Money = Field(ge=0)
    daily_loss_available: Money = Field(ge=0)
    total_loss_available: Money = Field(ge=0)
    budgets_known: StrictBool
    position: Annotated[OptionHolding | EquityHolding, Field(discriminator="kind")] | None = None
    working_orders: Count
    unsupported_exposure: StrictBool
    entry_halted: StrictBool
    entry_blockers: tuple[Name, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def funded(self):
        if self.settled_cash > self.cash or self.reserved_cash > self.settled_cash:
            raise ValueError("Settled/reserved cash cannot grant borrowing authority")
        return self


class OptionLimits(OptionRecord):
    """Explicit frozen PAPER envelope; no tier-derived or inferred LIVE defaults."""

    version: Literal["long-option-admission-v1"] = "long-option-admission-v1"
    mode: Literal["PAPER"] = "PAPER"
    account_id: Name
    population_id: Name
    allowed_underlyings: tuple[Symbol, ...] = Field(min_length=1, max_length=128)
    provider: Name
    option_source: Name
    underlying_source: Name
    session_source: Name
    max_contracts: PositiveCount
    max_entry_debit: Money = Field(gt=0)
    max_account_exposure: Money = Field(gt=0)
    max_full_premium_loss: Money = Field(gt=0)
    entry_fee_per_contract: Money = Field(ge=0)
    exit_fee_per_contract: Money = Field(ge=0)
    entry_fee_per_order: Money = Field(ge=0)
    exit_fee_per_order: Money = Field(ge=0)
    slippage_bps: Money = Field(ge=0, lt=10_000)
    max_spread_fraction: Money = Field(gt=0, le=1)
    minimum_underlying_price: Money = Field(ge=5)
    quote_max_age_seconds: PositiveCount
    account_max_age_seconds: PositiveCount
    max_receive_lag_seconds: Count
    max_sync_seconds: Count
    approval_lifetime_seconds: PositiveCount

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.allowed_underlyings)) != len(self.allowed_underlyings):
            raise ValueError("Duplicate allowed underlyings")
        if self.max_entry_debit > self.max_account_exposure:
            raise ValueError("Entry cap cannot exceed account exposure cap")
        return self


class OptionAdmission(OptionRecord):
    """An offline result, never execution authority or a broker order receipt."""

    policy_version: Literal["long-option-admission-v1"] = "long-option-admission-v1"
    mode: Literal["PAPER"] = "PAPER"
    outcome: Literal["HOLD", "REJECTED", "APPROVED"]
    action: Literal["HOLD", "OPEN_LONG", "CLOSE"]
    reasons: tuple[str, ...] = ()
    contract_id: str | None = None
    quantity: Count = 0
    limit_price: Money = Field(default=Decimal(0), ge=0)
    entry_debit: Money = Field(default=Decimal(0), ge=0)
    full_premium_loss: Money = Field(default=Decimal(0), ge=0)
    reserved_exit_fees: Money = Field(default=Decimal(0), ge=0)
    minimum_exit_cash_change: Money = Decimal(0)
    approved_at: datetime
    valid_until: datetime | None = None
