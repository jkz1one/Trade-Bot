from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, model_validator


# Pydantic's Decimal validation schema includes regex lookaround, which the
# Structured Outputs API rejects. Override only the two model-proposed price
# fields' wire representation. Decimal parsing, finiteness and Field(gt=0)
# validation still run locally before any governor/review action.
DecisionPrice = Annotated[
    Decimal,
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "number", "exclusiveMinimum": 0},
                {"type": "string"},
            ],
            "description": "Positive finite decimal price; a string preserves precision.",
        },
        mode="validation",
    ),
]


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
    invalidation_price: DecisionPrice | None = Field(default=None, gt=0)
    target_price: DecisionPrice | None = Field(default=None, gt=0)
    hold_overnight: bool = False
    thesis: str
    invalidation_reason: str
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    why_now: str

    @model_validator(mode="after")
    def validate_action_fields(self) -> "TradeDecision":
        if self.action != Action.HOLD and not self.symbol:
            raise ValueError(f"{self.action.value} requires symbol")
        if self.action == Action.OPEN_LONG and self.invalidation_price is None:
            raise ValueError("OPEN_LONG requires invalidation_price")
        if self.action == Action.HOLD and self.symbol is None:
            self.desired_exposure_fraction = 0

        text_limits = {
            "thesis": (self.thesis, 500),
            "invalidation_reason": (self.invalidation_reason, 300),
            "why_now": (self.why_now, 300),
        }
        for name, (value, max_length) in text_limits.items():
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
            if len(value) > max_length:
                raise ValueError(f"{name} exceeds {max_length} characters")
        if len(self.evidence) > 6:
            raise ValueError("evidence may contain at most 6 items")
        if len(self.risks) > 6:
            raise ValueError("risks may contain at most 6 items")
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
    working_orders: list[dict[str, Any]] = Field(default_factory=list)

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
    session_context: dict[str, str] | None = None


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
    broker_review: dict[str, Any] | None = None
    agent_error: str | None = None
    review_error: str | None = None
    session_blocked: bool = False
