"""Actual long-share identities and native terms, independent of option lifecycle."""

from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictBool, model_validator

from app.mixed.carry import StockCarryTerms
from app.options.models import Count, Evidence, Money, Name, OptionRecord, PositiveCount, Symbol

ZERO = Decimal(0)
SHARE_STEP = Decimal(".00000001")
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def _shares(value):
    # Money's before validator also forbids floats, bools and unbounded decimals.
    from app.options.models import _decimal

    value = _decimal(value)
    with localcontext(Context(prec=192)):
        if value % SHARE_STEP:
            raise ValueError("Shares require exact increments of 1e-8")
    return value


Shares = Annotated[Decimal, BeforeValidator(_shares)]


class StockInstrument(OptionRecord):
    provider: Name
    instrument_id: Name
    symbol: Symbol
    kind: Literal["EQUITY", "ETF"]
    market: Literal["US_LISTED"] = "US_LISTED"
    currency: Literal["USD"] = "USD"
    tick: Money = Field(gt=0)
    metadata_complete: StrictBool
    tradable: StrictBool


class StockLimits(OptionRecord):
    version: Literal["mixed-long-shares-v1"] = "mixed-long-shares-v1"
    provider: Name
    quote_source: Name
    allowed_symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=128)
    share_step: Shares = Field(gt=0, le=1)
    max_shares: Shares = Field(gt=0)
    max_entry_debit: Money = Field(gt=0)
    max_account_exposure: Money = Field(gt=0)
    minimum_price: Money = Field(ge=5)
    max_spread_fraction: Money = Field(gt=0, le=1)
    slippage_bps: Money = Field(ge=0, lt=10000)
    entry_fee_per_share: Money = Field(ge=0)
    exit_fee_per_share: Money = Field(ge=0)
    entry_fee_per_order: Money = Field(ge=0)
    exit_fee_per_order: Money = Field(ge=0)
    quote_max_age_seconds: PositiveCount
    max_receive_lag_seconds: Count
    approval_lifetime_seconds: PositiveCount

    @model_validator(mode="after")
    def bounded(self):
        if len(set(self.allowed_symbols)) != len(self.allowed_symbols):
            raise ValueError("Duplicate allowed stock symbols")
        with localcontext(Context(prec=192)):
            if self.max_shares % self.share_step:
                raise ValueError("Stock cap must fit the explicit share increment")
        if self.max_entry_debit > self.max_account_exposure:
            raise ValueError("Stock entry cannot exceed exposure ceiling")
        return self


class StockQuote(Evidence):
    instrument: StockInstrument
    bid: Money = Field(gt=0)
    ask: Money = Field(gt=0)
    bid_size: Shares | None = Field(default=None, ge=0)
    ask_size: Shares | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def uncrossed(self):
        if self.ask < self.bid:
            raise ValueError("Crossed stock quote")
        return self


class StockIntent(OptionRecord):
    version: Literal["mixed-stock-intent-v1"] = "mixed-stock-intent-v1"
    client_id: Name
    source_key: Name
    instrument: StockInstrument
    side: Literal["BUY", "SELL"]
    quantity: Shares = Field(gt=0)
    limit_price: Money = Field(gt=0)
    approved_entry_debit: Money = Field(ge=0)
    reserved_exit_fee: Money = Field(ge=0)
    prepared_at: datetime
    approval_expires_at: datetime
    order_expires_at: datetime
    exit_at: datetime
    carry: StockCarryTerms | None = Field(default=None, exclude_if=lambda v: v is None)
    original_invalidation: Money = Field(gt=0)
    original_target: Money = Field(gt=0)
    family: Literal["DEGEN", "SWING"]
    source_hash: Digest
    source_at: datetime
    source_valid_until: datetime
    approval_hash: Digest
    account_revision: Count
    thesis: str = Field(min_length=1, max_length=500)
    closing_entry_client_id: Name | None = None
    time_in_force: Literal["DAY"] = "DAY"

    @model_validator(mode="after")
    def bounded(self):
        if self.carry is not None and (
            self.family != "SWING"
            or self.exit_at != self.carry.exit_at
            or self.source_hash != self.carry.source_hash
        ):
            raise ValueError("Original Swing stock carry terms required")
        if (
            not self.source_at <= self.prepared_at
            or not self.source_at < self.source_valid_until <= self.exit_at
        ):
            raise ValueError("Original stock source clocks must fit the original exit")
        if not self.prepared_at < self.approval_expires_at <= self.order_expires_at:
            raise ValueError("Original stock approval and DAY deadlines required")
        if self.side == "BUY":
            if (
                self.closing_entry_client_id is not None
                or not self.original_invalidation < self.limit_price < self.original_target
                or self.order_expires_at > self.exit_at
                or self.approval_expires_at > self.source_valid_until
                or self.approved_entry_debit <= 0
            ):
                raise ValueError("Original long-share geometry and debit required")
        elif (
            self.closing_entry_client_id is None
            or self.closing_entry_client_id == self.client_id
            or self.approved_entry_debit
            or self.reserved_exit_fee
        ):
            raise ValueError("Stock sell must close a distinct owned entry without new debit")
        return self


class StockFill(OptionRecord):
    fill_id: Name
    order_id: Name
    sequence: PositiveCount
    quantity: Shares = Field(gt=0)
    price: Money = Field(gt=0)
    fee: Money = Field(ge=0)
    occurred_at: datetime
    quote_hash: Digest
    quote: StockQuote


class StockLot(OptionRecord):
    quantity: Shares = Field(gt=0)
    price: Money = Field(gt=0)


class StockPosition(OptionRecord):
    instrument: StockInstrument
    entry: StockIntent
    quantity: Shares = Field(gt=0)
    lots: tuple[StockLot, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def owned(self):
        with localcontext(Context(prec=192)):
            quantity = sum((lot.quantity for lot in self.lots), ZERO)
        if (
            self.entry.side != "BUY"
            or self.instrument != self.entry.instrument
            or self.quantity != quantity
            or self.quantity > self.entry.quantity
        ):
            raise ValueError("Exact original stock entry and lots required")
        return self

    @property
    def basis(self):
        with localcontext(Context(prec=192)):
            return sum((lot.quantity * lot.price for lot in self.lots), ZERO)


class StockObservation(OptionRecord):
    intent: StockIntent
    order_id: Name
    client_id: Name
    instrument: StockInstrument
    side: Literal["BUY", "SELL"]
    quantity: Shares = Field(gt=0)
    limit_price: Money = Field(gt=0)
    status: Literal["OPEN", "PARTIAL", "FILLED", "CANCELED", "REJECTED", "EXPIRED"]
    filled_quantity: Shares = Field(ge=0)
    updated_at: datetime
    fills: tuple[StockFill, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def complete(self):
        with localcontext(Context(prec=192)):
            quantity = sum((f.quantity for f in self.fills), ZERO)
        if any(
            getattr(self, k) != getattr(self.intent, k)
            for k in ("client_id", "instrument", "side", "quantity", "limit_price")
        ):
            raise ValueError("Stock observation must retain its exact accepted intent")
        if any(
            not self.intent.prepared_at <= f.occurred_at <= self.updated_at
            or f.occurred_at >= self.intent.order_expires_at
            for f in self.fills
        ):
            raise ValueError("Stock fills must fit original order clocks")
        if (
            quantity != self.filled_quantity
            or quantity > self.quantity
            or any(f.order_id != self.order_id for f in self.fills)
        ):
            raise ValueError("Complete owned share fill history required")
        if len({f.fill_id for f in self.fills}) != len(self.fills):
            raise ValueError("Duplicate stock fill identity")
        if (self.status == "FILLED") != (quantity == self.quantity):
            raise ValueError("Full stock quantity and FILLED must agree")
        if self.status in {"OPEN", "REJECTED"} and quantity:
            raise ValueError("OPEN/REJECTED cannot contain stock fills")
        if self.status == "PARTIAL" and not 0 < quantity < self.quantity:
            raise ValueError("Partial stock order needs incomplete positive fills")
        return self
