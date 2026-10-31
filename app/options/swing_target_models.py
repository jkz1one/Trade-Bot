"""Original Swing price objectives, separate from held execution schedules."""

from typing import Literal

from pydantic import Field

from app.options.models import Money, OptionRecord


class SwingTargetGeometry(OptionRecord):
    version: Literal["original-risk-ladder-v1"] = "original-risk-ladder-v1"
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    inputs_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference: Money = Field(gt=0)
    invalidation: Money = Field(gt=0)
    risk: Money = Field(gt=0)
    targets: tuple[Money, Money, Money]
