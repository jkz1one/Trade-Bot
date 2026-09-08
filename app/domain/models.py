from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Action(str, Enum):
    HOLD = "HOLD"
    OPEN_LONG = "OPEN_LONG"
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"


class Horizon(str, Enum):
    INTRADAY = "INTRADAY"
    MULTIDAY = "MULTIDAY"


class TradeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    symbol: str | None = None
    confidence: float = Field(ge=0, le=1)
    setup_quality: float = Field(ge=0, le=1)
    horizon: Horizon = Horizon.INTRADAY
    desired_exposure_fraction: float = Field(default=0, ge=0, le=1)
    invalidation_price: Decimal | None = Field(default=None, gt=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    hold_overnight: bool = False
    thesis: str = Field(min_length=1, max_length=500)
    invalidation_reason: str = Field(min_length=1, max_length=300)
    evidence: list[str] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=6)
    why_now: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "TradeDecision":
        if self.action != Action.HOLD and not self.symbol:
            raise ValueError(f"{self.action.value} requires symbol")
        if self.action == Action.OPEN_LONG and self.invalidation_price is None:
            raise ValueError("OPEN_LONG requires invalidation_price")
        if self.action == Action.HOLD and self.symbol is None:
            self.desired_exposure_fraction = 0
        return self


class Quote(BaseModel):
    symbol: str
    timestamp: datetime
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    last: Decimal = Field(gt=0)
    fractional_tradable: bool = True

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_fraction(self) -> Decimal:
        return (self.ask - self.bid) / self.midpoint


class Candidate(BaseModel):
    quote: Quote
    atr_fraction: Decimal = Field(gt=0)
    realized_vol_fraction: Decimal = Field(gt=0)
    day_change_fraction: Decimal = Decimal("0")
    above_vwap: bool | None = None
    relative_volume: Decimal | None = None


class Position(BaseModel):
    symbol: str
    quantity: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    current_price: Decimal = Field(gt=0)
    original_invalidation: Decimal = Field(gt=0)
    thesis: str
    opened_at: datetime

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> Decimal:
        return self.quantity * (self.current_price - self.entry_price)


class AccountState(BaseModel):
    equity: Decimal = Field(ge=0)
    cash: Decimal = Field(ge=0)
    buying_power: Decimal = Field(ge=0)
    high_watermark: Decimal = Field(ge=0)
    realized_pnl: Decimal = Decimal("0")
    position: Position | None = None

    @property
    def drawdown_fraction(self) -> Decimal:
        if self.high_watermark <= 0:
            return Decimal("0")
        return max(Decimal("0"), (self.high_watermark - self.equity) / self.high_watermark)


class MarketPacket(BaseModel):
    as_of: datetime
    account: AccountState
    candidates: list[Candidate]
    regime: str = "unknown"
    recent_lessons: list[str] = Field(default_factory=list)


class RiskDecision(BaseModel):
    approved: bool
    requested_notional: Decimal
    approved_notional: Decimal
    planned_risk_dollars: Decimal
    planned_risk_fraction: Decimal
    effective_loss_distance: Decimal
    risk_mode: str
    drawdown_modifier: Decimal
    confidence_modifier: Decimal
    constraint_hits: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    status: Literal["SKIPPED", "FILLED", "REJECTED"]
    order_id: str | None = None
    symbol: str | None = None
    notional: Decimal = Decimal("0")
    fill_price: Decimal | None = None
    filled_quantity: Decimal = Decimal("0")
    message: str = ""
