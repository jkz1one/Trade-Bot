"""Explicit native mixed-owner enrollment; legacy owners omit these contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from app.mixed.carry import StockCarryPolicy
from app.mixed.stock_models import StockLimits
from app.options.models import Money, Name, OptionRecord


class PortfolioEnrollment(OptionRecord):
    version: Literal["mixed-native-portfolio-v2"] = "mixed-native-portfolio-v2"
    max_plays: StrictInt = Field(default=2, ge=0, le=2)
    exposure_limit: Money = Field(gt=0)
    index_exposure_limit: Money = Field(gt=0)


class MixedOwnerPolicy(OptionRecord):
    portfolio: PortfolioEnrollment | None = Field(default=None, exclude_if=lambda v: v is None)
    version: Literal["mixed-native-owner-v1"] = "mixed-native-owner-v1"
    reasoning: Literal["mixed-paid-entry-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    stocks: StockLimits
    stock_carry: StockCarryPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    allocation: Literal["daily-calendar-fixture-v1"] = "daily-calendar-fixture-v1"
    daily_data_cost: Money | None = Field(ge=0)
    daily_host_cost: Money | None = Field(ge=0)
    daily_operating_cost: Money | None = Field(ge=0)


class StockProtection(OptionRecord):
    entry_client_id: Name
    invalidation: Money = Field(gt=0)
    exit_reason: Name | None = None
    exit_required_at: datetime | None = None
    issue: Name | None = None

    @model_validator(mode="after")
    def paired(self):
        if (self.exit_reason is None) != (self.exit_required_at is None):
            raise ValueError("Original stock exit latch clock required")
        return self
