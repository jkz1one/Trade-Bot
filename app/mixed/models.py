"""One-bankroll history contracts. Legacy option/stock cohorts cannot enroll these."""

from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictBool, model_validator

from app.options.lifecycle import OptionFill, OptionIntent, OptionLedger, OptionReceipt
from app.options.models import (
    Count,
    Evidence,
    Money,
    Name,
    OptionLimits,
    OptionRecord,
    PositiveCount,
    Symbol,
)

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


class MixedPolicy(OptionRecord):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    mode: Literal["PAPER"] = "PAPER"
    capital: Money = Field(gt=0)
    daily_loss_limit: Money = Field(gt=0)
    total_loss_limit: Money = Field(gt=0)
    options: OptionLimits
    stocks: StockLimits

    @model_validator(mode="after")
    def one_brokerage(self):
        if self.options.provider != self.stocks.provider:
            raise ValueError("Mixed history requires one frozen brokerage provider")
        if not self.daily_loss_limit <= self.total_loss_limit <= self.capital:
            raise ValueError("Mixed losses must fit one original capital")
        return self


class MixedLedger(OptionLedger):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    stock_position: StockPosition | None = None

    @model_validator(mode="after")
    def one_position(self):
        if self.position is not None and self.stock_position is not None:
            raise ValueError("Only one position across stocks and options")
        return self


class StockTrade(OptionRecord):
    kind: Literal["STOCK_FILL"] = "STOCK_FILL"
    intent: StockIntent
    attempted_at: datetime
    fill: StockFill


class OptionTrade(OptionRecord):
    kind: Literal["OPTION_FILL"] = "OPTION_FILL"
    intent: OptionIntent
    attempted_at: datetime
    fill: OptionFill


class Settlement(OptionRecord):
    kind: Literal["SETTLEMENT"] = "SETTLEMENT"
    receipt: OptionReceipt


CashEvent = Annotated[StockTrade | OptionTrade | Settlement, Field(discriminator="kind")]


class CostRecord(OptionRecord):
    cost_id: Name
    kind: Literal["ENTRY_MODEL", "MANAGEMENT_MODEL", "DATA", "HOST", "OPERATING"]
    occurred_at: datetime
    amount: Money | None = Field(ge=0)
    entry_client_id: Name | None = None
    evidence_hash: Digest


class CostResolution(OptionRecord):
    cost_id: Name
    recorded_at: datetime
    amount: Money = Field(ge=0)
    evidence_hash: Digest


class Reservation(OptionRecord):
    """An unresolved native order, not a model proposal or a new approval."""

    intent: StockIntent | OptionIntent
    status: Literal["PREPARED", "SUBMITTING", "UNKNOWN", "OPEN", "PARTIAL"]


class TerminalOrder(OptionRecord):
    intent: StockIntent | OptionIntent
    status: Literal["FILLED", "CANCELED", "REJECTED", "EXPIRED"]
    observed_at: datetime
    order_id: Name | None
    attempted_at: datetime | None


class CashHistory(OptionRecord):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    account_id: Name
    population_id: Name
    venue_id: Name
    policy: MixedPolicy
    opened_at: datetime
    captured_at: datetime
    events: tuple[CashEvent, ...] = Field(default=(), max_length=10000)
    costs: tuple[CostRecord, ...] = Field(default=(), max_length=10000)
    cost_resolutions: tuple[CostResolution, ...] = Field(default=(), max_length=10000)
    reservations: tuple[Reservation, ...] = Field(default=(), max_length=1)
    terminals: tuple[TerminalOrder, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def account_binding(self):
        if not 0 <= (self.captured_at - self.opened_at).total_seconds() <= 366 * 86400:
            raise ValueError("Bounded original history interval required")
        if (self.account_id, self.population_id) != (
            self.policy.options.account_id,
            self.policy.options.population_id,
        ):
            raise ValueError("Mixed history must bind its one original account/population")
        return self


class CashProjection(OptionRecord):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    ledger: MixedLedger
    reserved_cash: Money = Field(ge=0)
    available_settled_cash: Money = Field(ge=0)
    known_cost: Money = Field(ge=0)
    unknown_cost_ids: tuple[Name, ...]
    daily_cost: dict[str, Money]
    net_realized_pnl: Money | None
    daily_loss_available: Money | None = Field(ge=0)
    total_loss_available: Money | None = Field(ge=0)
    entry_blockers: tuple[Name, ...]


class StockProposal(OptionRecord):
    action: Literal["HOLD", "OPEN_LONG", "CLOSE"]
    instrument: StockInstrument | None = None
    source_hash: Digest | None = None
    family: Literal["DEGEN", "SWING"] | None = None
    source_at: datetime | None = None
    valid_until: datetime | None = None
    exit_at: datetime | None = None
    original_invalidation: Money | None = Field(default=None, gt=0)
    original_target: Money | None = Field(default=None, gt=0)
    thesis: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def terms(self):
        if self.action != "HOLD" and self.instrument is None:
            raise ValueError("An exact stock instrument is required")
        if self.action == "OPEN_LONG" and (
            any(
                getattr(self, k) is None
                for k in (
                    "source_hash",
                    "family",
                    "source_at",
                    "valid_until",
                    "exit_at",
                    "original_invalidation",
                    "original_target",
                )
            )
            or not self.source_at < self.valid_until <= self.exit_at
        ):
            raise ValueError("Original stock source, geometry and deadlines are required")
        return self


class StockAdmission(OptionRecord):
    version: Literal["mixed-stock-admission-v1"] = "mixed-stock-admission-v1"
    mode: Literal["PAPER"] = "PAPER"
    outcome: Literal["HOLD", "REJECTED", "APPROVED"]
    action: Literal["HOLD", "OPEN_LONG", "CLOSE"]
    reasons: tuple[Name, ...] = ()
    history_hash: Digest
    proposal_hash: Digest
    approved_at: datetime
    approval_expires_at: datetime | None = None
    quantity: Shares = Field(default=ZERO, ge=0)
    limit_price: Money | None = Field(default=None, gt=0)
    entry_debit: Money = Field(default=ZERO, ge=0)
    reserved_exit_fee: Money = Field(default=ZERO, ge=0)
