"""Fixed native option request/response contracts, independent of the parent transport."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.execution.process_protocol import FixtureFault
from app.mixed.portfolio_venue import PortfolioPolicy, PortfolioVenueSnapshot
from app.mixed.stock_models import StockIntent, StockLimits
from app.options.lifecycle import OptionIntent, OptionVenueSnapshot
from app.options.models import Name, OptionRecord


class OptionRequest(OptionRecord):
    operation: Literal["accept", "stock_accept", "snapshot"]
    path: str
    venue_id: Name
    account_id: Name
    population_id: Name
    now: datetime
    deadline_monotonic: float = Field(gt=0, allow_inf_nan=False)
    parent_pid: int = Field(gt=0, strict=True)
    intent: OptionIntent | None = None
    portfolio_policy: PortfolioPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    stock_limits: StockLimits | None = Field(default=None, exclude_if=lambda v: v is None)
    stock_intent: StockIntent | None = Field(default=None, exclude_if=lambda v: v is None)
    fault: FixtureFault = "NONE"

    @model_validator(mode="after")
    def paired(self):
        if (self.operation == "accept") != (self.intent is not None):
            raise ValueError("Operation and option intent must agree")
        if (self.operation == "stock_accept") != (self.stock_intent is not None):
            raise ValueError("Operation and stock intent must agree")
        if self.stock_intent is not None and self.stock_limits is None:
            raise ValueError("Stock worker request needs its frozen limits")
        return self


class OptionProcessResult(OptionRecord):
    order_id: Name | None = None
    snapshot: PortfolioVenueSnapshot | OptionVenueSnapshot | None = None

