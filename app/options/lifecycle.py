"""PAPER-only order, receipt and accounting contracts. No real brokerage transport."""

from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from app.execution.economics import CostPolicy
from app.options.models import (
    Count,
    Money,
    Name,
    OptionContract,
    OptionHolding,
    OptionInstrument,
    OptionQuote,
    OptionRecord,
    PositiveCount,
    Symbol,
)

ZERO = Decimal(0)
TERMINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
CALENDAR_SOURCE = "XNYS_REGULAR_INTERSECTION_V1"


class FamilyLossPolicy(OptionRecord):
    family: Literal["DEGEN", "SWING"]
    max_consecutive_losses: int = Field(strict=True, ge=1, le=2)
    cooldown_seconds: int = Field(strict=True, ge=1800, le=86400)


class NativeLossPolicy(OptionRecord):
    version: Literal["native-position-loss-v1"] = "native-position-loss-v1"
    max_consecutive_losses: int = Field(strict=True, ge=1, le=2)
    cooldown_seconds: int = Field(strict=True, ge=1800, le=86400)
    families: tuple[FamilyLossPolicy, ...] = Field(
        default=(), max_length=2, exclude_if=lambda v: not v
    )

    @model_validator(mode="after")
    def distinct_families(self):
        if len({p.family for p in self.families}) != len(self.families):
            raise ValueError("Distinct frozen family loss policies required")
        return self


class OptionExecutionPolicy(OptionRecord):
    version: Literal["option-paper-lifecycle-v1"] = "option-paper-lifecycle-v1"
    capital: Money = Field(gt=0)
    daily_loss_limit: Money = Field(gt=0)
    total_loss_limit: Money = Field(gt=0)
    calendar_source: Literal["XNYS_REGULAR_INTERSECTION_V1"] = CALENDAR_SOURCE
    entry_cutoff_minutes: PositiveCount
    exit_cutoff_minutes: PositiveCount
    expiry_guard_seconds: PositiveCount
    premium_catastrophe_fraction: Money = Field(gt=0, lt=1)
    supervisor_max_age_seconds: PositiveCount
    process_timeout_seconds: float = Field(gt=0, le=30, allow_inf_nan=False)
    cost_policy: CostPolicy | None = None
    loss_control: NativeLossPolicy | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def bounded(self):
        if self.total_loss_limit > self.capital or self.daily_loss_limit > self.total_loss_limit:
            raise ValueError("Explicit loss limits must fit the original PAPER capital")
        if self.exit_cutoff_minutes >= self.entry_cutoff_minutes:
            raise ValueError("New entries must stop before deterministic session exit")
        return self


class EntryProtection(OptionRecord):
    """Immutable independently enforceable terms, bound to the complete stored plan."""

    packet_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    underlying_target: Money = Field(gt=0)
    exit_by: datetime


class PositionExitProtection(OptionRecord):
    packet_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    entry_client_id: Name
    position_revision: PositiveCount


class EntryLineage(OptionRecord):
    """Frozen selected-opportunity identity; never a caller-selected strategy label."""

    version: Literal["native-entry-lineage-v1"] = "native-entry-lineage-v1"
    family: Literal["DEGEN", "SWING"]
    setup: Name
    opportunity_key: Name
    candidate_id: Name
    candidate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class OptionIntent(OptionRecord):
    client_id: Name
    source_key: Name
    instrument: OptionInstrument
    side: Literal["BUY", "SELL"]
    quantity: PositiveCount
    limit_price: Money = Field(gt=0)
    approved_entry_debit: Money = Field(ge=0)
    approved_full_premium_loss: Money = Field(ge=0)
    prepared_at: datetime
    approval_expires_at: datetime
    order_expires_at: datetime
    exit_at: datetime
    original_underlying_invalidation: Money = Field(gt=0)
    thesis: str = Field(min_length=1, max_length=500)
    time_in_force: Literal["DAY"] = "DAY"
    entry_protection: EntryProtection | None = Field(default=None, exclude_if=lambda v: v is None)
    closing_entry_client_id: Name | None = Field(default=None, exclude_if=lambda v: v is None)
    entry_lineage: EntryLineage | None = Field(default=None, exclude_if=lambda v: v is None)

    position_protection: PositionExitProtection | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def lifetime(self):
        if not self.prepared_at < self.approval_expires_at <= self.order_expires_at:
            raise ValueError("Distinct fresh approval and DAY-order deadlines required")
        if self.order_expires_at > self.instrument.contract.last_trading_at:
            raise ValueError("DAY order cannot outlive the exact contract trading instant")
        if self.entry_lineage is not None and (
            self.side != "BUY" or self.entry_lineage.opportunity_key != self.source_key
        ):
            raise ValueError("Entry lineage binds only its originating buy opportunity")
        if self.closing_entry_client_id is not None and (
            self.side != "SELL"
            or self.closing_entry_client_id == self.client_id
            or (
                self.position_protection is not None
                and self.closing_entry_client_id != self.position_protection.entry_client_id
            )
        ):
            raise ValueError("Closing entry link requires the exact distinct buy")
        if self.position_protection is not None and (
            self.side != "SELL" or self.entry_protection is not None
        ):
            raise ValueError("Management protection binds only an owned full-exit intent")
        if self.entry_protection is not None and (
            self.side != "BUY"
            or not self.prepared_at < self.exit_at <= self.entry_protection.exit_by
            or self.order_expires_at > self.exit_at
        ):
            raise ValueError("Entry plan must bound entry order and independent exit lifetime")
        return self


class OptionFill(OptionRecord):
    fill_id: Name
    order_id: Name
    sequence: PositiveCount
    quantity: PositiveCount
    price: Money = Field(gt=0)
    fee: Money = Field(ge=0)
    occurred_at: datetime
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: OptionQuote


class OptionObservation(OptionRecord):
    order_id: Name
    client_id: Name
    instrument: OptionInstrument
    side: Literal["BUY", "SELL"]
    quantity: PositiveCount
    limit_price: Money = Field(gt=0)
    status: Literal["OPEN", "PARTIAL", "FILLED", "CANCELED", "REJECTED", "EXPIRED"]
    filled_quantity: Count
    updated_at: datetime
    fills: tuple[OptionFill, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def consistent(self):
        if self.filled_quantity != sum(f.quantity for f in self.fills):
            raise ValueError("Complete whole-contract fill history required")
        if self.filled_quantity > self.quantity or any(
            f.order_id != self.order_id for f in self.fills
        ):
            raise ValueError("Overfilled or foreign order fills")
        if len({f.fill_id for f in self.fills}) != len(self.fills):
            raise ValueError("Duplicate fill IDs")
        if self.status in {"OPEN", "REJECTED"} and self.filled_quantity:
            raise ValueError("OPEN/REJECTED cannot contain fills")
        if (self.status == "FILLED") != (self.filled_quantity == self.quantity):
            raise ValueError("Full quantity and FILLED must agree")
        if self.status == "PARTIAL" and not 0 < self.filled_quantity < self.quantity:
            raise ValueError("PARTIAL requires positive incomplete quantity")
        return self


class OptionLot(OptionRecord):
    quantity: PositiveCount
    price: Money = Field(gt=0)


class OptionPosition(OptionHolding):
    entry_client_id: Name
    lots: tuple[OptionLot, ...] = Field(min_length=1, max_length=1000)
    exit_at: datetime
    tightened_underlying_invalidation: Money = Field(gt=0)
    entry_protection: EntryProtection | None = Field(default=None, exclude_if=lambda v: v is None)
    exit_reason: (
        Literal[
            "UNDERLYING_INVALIDATION",
            "PREMIUM_CATASTROPHE",
            "TIME_EXIT",
            "EXPIRY_GUARD",
            "UNDERLYING_TARGET",
        ]
        | None
    ) = None
    exit_required_at: datetime | None = None
    supervision_issue: str | None = None

    @model_validator(mode="after")
    def owned(self):
        if self.entry_protection is not None and self.exit_at > self.entry_protection.exit_by:
            raise ValueError("Owned position cannot extend the original plan horizon")
        if self.quantity != sum(lot.quantity for lot in self.lots):
            raise ValueError("Owned quantity must match complete lots")
        if (self.exit_reason is None) != (self.exit_required_at is None):
            raise ValueError("Exit requirement must retain its original time")
        original, stop = (
            self.original_underlying_invalidation,
            self.tightened_underlying_invalidation,
        )
        if (self.contract.right == "CALL" and stop < original) or (
            self.contract.right == "PUT" and stop > original
        ):
            raise ValueError("Invalidation cannot widen")
        return self

    @property
    def basis(self):
        with localcontext(Context(prec=192)):
            return sum(
                (lot.quantity * lot.price * self.contract.multiplier for lot in self.lots), ZERO
            )


class OptionLedger(OptionRecord):
    cash: Money = Field(ge=0)
    settled_cash: Money | None = Field(default=None, ge=0)
    high_watermark: Money = Field(gt=0)
    position: OptionPosition | None = None
    realized_pnl: Money = ZERO
    fees_paid: Money = Field(default=ZERO, ge=0)
    daily_net_pnl: dict[str, Money] = Field(default_factory=dict)

    @model_validator(mode="after")
    def funded(self):
        if self.settled_cash is None:
            object.__setattr__(self, "settled_cash", self.cash)
        if self.settled_cash > self.cash:
            raise ValueError("Settled cash cannot exceed actual cash")
        return self


class OptionReceipt(OptionRecord):
    receipt_id: Name
    sequence: PositiveCount
    kind: Literal["FUNDS_SETTLED", "CASH_SETTLEMENT", "EXPIRED_WORTHLESS", "PHYSICAL_EXERCISE"]
    occurred_at: datetime
    contract: OptionContract | None = None
    quantity: Count = 0
    settlement_value: Money | None = Field(default=None, ge=0)
    cash_change: Money


class UnderlyingExposure(OptionRecord):
    symbol: Symbol
    quantity: Money


class OptionVenueSnapshot(OptionRecord):
    environment: Literal["LOCAL_OPTION_FIXTURE"] = "LOCAL_OPTION_FIXTURE"
    venue_id: Name
    account_id: Name
    population_id: Name
    snapshot_id: Name
    captured_at: datetime
    complete: StrictBool = True
    cash: Money
    settled_cash: Money
    position: OptionPosition | None = None
    orders: tuple[OptionObservation, ...] = Field(default=(), max_length=1000)
    receipts: tuple[OptionReceipt, ...] = Field(default=(), max_length=1000)
    underlying_exposures: tuple[UnderlyingExposure, ...] = Field(default=(), max_length=32)
