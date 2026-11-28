from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class RobinhoodAccount(BaseModel):
    model_config = ConfigDict(extra="ignore")
    account_number: str
    rhs_account_number: str | None = None
    type: str
    brokerage_account_type: str
    agentic_allowed: bool
    state: str
    deactivated: bool
    permanently_deactivated: bool
    unsettled_funds: Decimal | None = None


class RobinhoodPortfolio(BaseModel):
    total_value: Decimal
    equity_value: Decimal
    cash: Decimal
    buying_power: Decimal
    unleveraged_buying_power: Decimal
    unsupported_value: Decimal = Decimal("0")


class RobinhoodPosition(BaseModel):
    symbol: str
    quantity: Decimal
    shares_available_for_sells: Decimal
    average_buy_price: Decimal | None = None
    type: str


class RobinhoodOrder(BaseModel):
    id: str
    symbol: str
    side: str
    state: str
    quantity: Decimal | None = None
    cumulative_quantity: Decimal = Decimal("0")
    average_price: Decimal | None = None
    price: Decimal | None = None
    stop_price: Decimal | None = None
    placed_agent: str | None = None


class RobinhoodTruth(BaseModel):
    account: RobinhoodAccount
    portfolio: RobinhoodPortfolio
    positions: list[RobinhoodPosition] = Field(default_factory=list)
    working_orders: list[RobinhoodOrder] = Field(default_factory=list)


class ReconciliationResult(BaseModel):
    reconciled: bool
    reasons: list[str] = Field(default_factory=list)
