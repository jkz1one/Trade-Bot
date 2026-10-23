"""Explicit native mixed-owner enrollment; legacy owners omit these contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.mixed.stock_models import StockLimits
from app.options.models import Money, Name, OptionRecord


class MixedOwnerPolicy(OptionRecord):
    version: Literal["mixed-native-owner-v1"] = "mixed-native-owner-v1"
    stocks: StockLimits
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
