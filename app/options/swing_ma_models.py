"""Explicit daily moving-average enrollment; no implicit upgrade of frozen cohorts."""

from typing import Literal

from pydantic import Field, model_validator

from app.options.models import Money, Name, OptionRecord

MAPeriod = Literal[8, 21, 50]
MA_FAMILIES = {8: "SWING_DAILY_8_EMA", 21: "SWING_DAILY_21_EMA", 50: "SWING_DAILY_50_SMA"}


class SwingMAPolicy(OptionRecord):
    version: Literal["swing-ma-pullback-v1"] = "swing-ma-pullback-v1"
    periods: tuple[MAPeriod, ...] = Field(min_length=1, max_length=3)
    hourly_source: Name
    hourly_lookback: int = Field(ge=54, le=260, strict=True)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("Unique frozen moving-average variants required")
        return self


class SwingMAEvidence(OptionRecord):
    version: Literal["swing-ma-pullback-v1"] = "swing-ma-pullback-v1"
    period: MAPeriod
    reference: Money = Field(gt=0)
    invalidation: Money = Field(gt=0)
    moving_average: Money = Field(gt=0)
    slope_pct: Money
    atr: Money = Field(gt=0)
    volume_ratio: Money = Field(gt=0)
    test_number: int = Field(ge=1, strict=True)
    hold_bars: int = Field(ge=0, strict=True)
    confirmations: tuple[Name, ...]
    daily_direction: Literal["bullish", "bearish", "neutral"]
    hourly_direction: Literal["bullish", "bearish", "neutral"]
    warnings: tuple[Name, ...]
    reasons: tuple[Name, ...]
