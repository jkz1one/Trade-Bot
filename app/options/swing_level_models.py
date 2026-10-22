"""Frozen higher-timeframe level setup identity and original source evidence."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.options.models import Money, Name, OptionRecord

LevelKey = Literal[
    "previous_week_high",
    "previous_week_low",
    "previous_month_high",
    "previous_month_low",
    "weekly_open",
]
LEVEL_FAMILIES = {
    "previous_week_high": "SWING_PREVIOUS_WEEK_HIGH",
    "previous_week_low": "SWING_PREVIOUS_WEEK_LOW",
    "previous_month_high": "SWING_PREVIOUS_MONTH_HIGH",
    "previous_month_low": "SWING_PREVIOUS_MONTH_LOW",
    "weekly_open": "SWING_WEEKLY_OPEN",
}


class SwingLevelPolicy(OptionRecord):
    version: Literal["swing-level-retest-v1"] = "swing-level-retest-v1"
    keys: tuple[LevelKey, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.keys)) != len(self.keys):
            raise ValueError("Unique frozen higher-timeframe levels required")
        return self


class SwingLevelEvidence(OptionRecord):
    version: Literal["swing-level-retest-v1"] = "swing-level-retest-v1"
    level_key: LevelKey
    level_price: Money = Field(gt=0)
    source_start: datetime
    source_end: datetime
    breakout_at: datetime | None
    reference: Money = Field(gt=0)
    invalidation: Money = Field(gt=0)
    test_number: int = Field(ge=1, strict=True)
    daily_direction: Literal["bullish", "bearish", "neutral"]
    confirmations: tuple[Name, ...]
    warnings: tuple[Name, ...]
    reasons: tuple[Name, ...]
