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
    provider: Name
    instrument_id: Name
    contract: OptionContract
    metadata_complete: StrictBool
    option_tradable: StrictBool


class Evidence(OptionRecord):
    source: Name
    source_at: datetime
    received_at: datetime
    entitlement: Literal["REALTIME", "DELAYED", "INDICATIVE", "UNKNOWN"]
    complete: StrictBool


class OptionQuote(Evidence):
    instrument: OptionInstrument
    bid: Money | None = Field(default=None, ge=0)
    ask: Money | None = Field(default=None, gt=0)
    bid_size: Count
    ask_size: Count


class UnderlyingQuote(Evidence):
    symbol: Symbol
    bid: Money = Field(gt=0)
    ask: Money = Field(gt=0)


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
