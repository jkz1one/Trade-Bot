from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import Horizon, Position

ZERO = Decimal(0)
SHARE_STEP = Decimal("0.00000001")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value):
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Execution timestamps must be timezone-aware")
        return value


class OrderState(StrEnum):
    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


TERMINAL = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED}


class Intent(Contract):
    client_id: str
    source_key: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    approved_notional: Decimal = Field(gt=0)
    prepared_at: datetime
    expires_at: datetime
    original_invalidation: Decimal = Field(gt=0)
    thesis: str


class Fill(Contract):
    fill_id: str = Field(min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(default=ZERO, ge=0)
    occurred_at: datetime


class Observation(Contract):
    order_id: str = Field(min_length=1, max_length=128)
    client_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    status: Literal["OPEN", "PARTIAL", "FILLED", "CANCELED", "REJECTED", "EXPIRED"]
    filled_quantity: Decimal = Field(ge=0)
    updated_at: datetime
    fills: list[Fill] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if self.filled_quantity != sum((f.quantity for f in self.fills), ZERO):
            raise ValueError("Cumulative quantity must match complete fill evidence")
        if self.filled_quantity > self.quantity:
            raise ValueError("Order is overfilled")
        if any(f.order_id != self.order_id for f in self.fills):
            raise ValueError("Fill belongs to a different order")
        if len({f.fill_id for f in self.fills}) != len(self.fills):
            raise ValueError("Duplicate fill identities")
        if self.status == "FILLED" and self.filled_quantity != self.quantity:
            raise ValueError("FILLED requires complete quantity")
        if self.status in {"OPEN", "REJECTED"} and self.filled_quantity != 0:
            raise ValueError("OPEN/REJECTED cannot contain fills")
        if self.status == "PARTIAL" and not 0 < self.filled_quantity < self.quantity:
            raise ValueError("PARTIAL requires an incomplete positive quantity")
        if self.status != "FILLED" and self.filled_quantity == self.quantity:
            raise ValueError("Complete quantity requires FILLED")
        return self


class VenuePosition(Contract):
    symbol: str
    quantity: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)


class Snapshot(Contract):
    environment: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    account_id: str = Field(default="execution-rehearsal", min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=1, max_length=128)
    captured_at: datetime
    complete: bool = True
    cash: Decimal = Field(ge=0)
    safe_buying_power: Decimal = Field(ge=0)
    unsupported_value: Decimal = Field(default=ZERO, ge=0)
    positions: list[VenuePosition] = Field(default_factory=list)
    orders: list[Observation] = Field(default_factory=list)


class PositionManagement(Contract):
    policy: Literal["original-stop-session-v1"] = "original-stop-session-v1"
    entry_client_id: str
    session_date: str
    horizon: Horizon
    hold_overnight: bool
    exit_reason: Literal["INVALIDATION", "MISSED_SESSION_EXIT", "SESSION_EXIT"] | None = None
    exit_required_at: datetime | None = None
    last_supervised_at: datetime | None = None
    last_quote_at: datetime | None = None
    supervision_issue: str | None = None


class ExecutionLimits(Contract):
    """Frozen local-fixture admission envelope, independent of model proposals."""

    account_id: str = Field(default="execution-rehearsal", min_length=1, max_length=128)
    max_entry_notional: Decimal = Field(gt=0)
    max_position_notional: Decimal = Field(gt=0)
    total_loss_limit: Decimal = Field(gt=0)
    daily_loss_limit: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def bounded(self):
        if not self.account_id.strip():
            raise ValueError("An explicit fixture account identity is required")
        if self.max_entry_notional > self.max_position_notional:
            raise ValueError("Entry ceiling cannot exceed position ceiling")
        return self


class Ledger(Contract):
    cash: Decimal = Field(ge=0)
    position: Position | None = None
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = Field(default=ZERO, ge=0)
    high_watermark: Decimal = Field(gt=0)
    entry_times: list[datetime] = Field(default_factory=list)
    last_close_at: datetime | None = None
    management: PositionManagement | None = None
    daily_net_pnl: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("daily_net_pnl")
    @classmethod
    def finite_daily_pnl(cls, value):
        if any(not amount.is_finite() for amount in value.values()):
            raise ValueError("Daily net P&L must be finite")
        return value
