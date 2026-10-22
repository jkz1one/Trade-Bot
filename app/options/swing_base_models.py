"""Explicit completed-daily base family enrollment and reproducible evidence."""

from typing import Literal

from pydantic import Field

from app.options.models import Money, Name, OptionRecord

SwingFamily = Literal["SWING_DAILY_BREAKOUT", "SWING_DAILY_BASE"]
SWING_FAMILIES = ("SWING_DAILY_BREAKOUT", "SWING_DAILY_BASE")


class SwingBasePolicy(OptionRecord):
    version: Literal["swing-daily-base-v1"] = "swing-daily-base-v1"
    hourly_source: Name
    hourly_lookback: int = Field(ge=54, le=260, strict=True)


class SwingBaseEvidence(OptionRecord):
    version: Literal["swing-daily-base-v1"] = "swing-daily-base-v1"
    reference: Money = Field(gt=0)
    invalidation: Money = Field(gt=0)
    base_high: Money = Field(gt=0)
    base_low: Money = Field(gt=0)
    prior_atr: Money = Field(gt=0)
    width_fraction: Money = Field(ge=0)
    compression_ratio: Money = Field(ge=0)
    volume_ratio: Money = Field(gt=0)
    close_location: Money = Field(ge=0, le=1)
    extension_atr: Money = Field(ge=0)
    daily_direction: Literal["bullish", "bearish", "neutral"]
    hourly_direction: Literal["bullish", "bearish", "neutral"]
    reasons: tuple[Name, ...]
