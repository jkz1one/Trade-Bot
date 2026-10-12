"""Frozen local PAPER runtime and explicitly supplied normalized fixture packets."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenFrame
from app.options.degen import DegenPolicy
from app.options.entry_reasoning import EntryReasoningPolicy
from app.options.lifecycle import OptionExecutionPolicy
from app.options.models import Name, OptionLimits, OptionRecord
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.selection import ContractSelectionPolicy
from app.options.swing import SwingPolicy


class RuntimePolicy(OptionRecord):
    version: Literal["option-local-runtime-v1"] = "option-local-runtime-v1"
    feed_file: str = Field(min_length=1, max_length=4096)
    operator_key_file: str | None = Field(
        default=None, min_length=1, max_length=4096, exclude_if=lambda v: v is None
    )
    tick_seconds: float = Field(ge=0.2, le=5, strict=True)
    heartbeat_max_age_seconds: int = Field(ge=2, le=30, strict=True)
    feed_max_age_seconds: int = Field(ge=1, le=30, strict=True)

    @field_validator("feed_file", "operator_key_file")
    @classmethod
    def absolute(cls, value):
        if value is None:
            return value
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("Explicit absolute normalized fixture feed path required")
        return value

    @model_validator(mode="after")
    def separate(self):
        if self.operator_key_file == self.feed_file:
            raise ValueError("Operator key must be separate from the feed")
        return self


class RuntimeSettings(OptionRecord):
    limits: OptionLimits
    execution: OptionExecutionPolicy
    swing_policy: SwingPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    setup: DegenPolicy
    selection: ContractSelectionPolicy
    runtime: RuntimePolicy
    judgment_limits: JudgmentLimits | None = None
    key_file: str | None = Field(default=None, min_length=1, max_length=4096)
    entry_policy: EntryReasoningPolicy | None = None
    position_policy: PositionReasoningPolicy | None = None

    @model_validator(mode="after")
    def bounded(self):
        if self.key_file is not None and self.key_file == self.runtime.operator_key_file:
            raise ValueError("Operator and model credentials must be separate")
        model = self.key_file is not None
        if model != (self.judgment_limits is not None) or model != (
            self.execution.cost_policy is not None
        ):
            raise ValueError("Model key, limits and frozen costs must be explicitly paired")
        if self.key_file is not None and (
            not Path(self.key_file).is_absolute()
            or "\x00" in self.key_file
            or self.key_file == self.runtime.feed_file
        ):
            raise ValueError("Separate absolute private model key path required")
        if (self.entry_policy is not None and not model) or (
            self.position_policy is not None and self.entry_policy is None
        ):
            raise ValueError("Management requires an explicitly configured full-entry cohort")
        if self.swing_policy is not None and model and self.entry_policy is None:
            raise ValueError("Shared AI families require full entry reasoning")
        age = self.execution.process_timeout_seconds + self.runtime.tick_seconds
        if age >= min(
            self.runtime.heartbeat_max_age_seconds,
            self.execution.supervisor_max_age_seconds,
            self.limits.account_max_age_seconds,
        ):
            raise ValueError("Supervisor process/tick budget must fit all freshness bounds")
        if not set(self.setup.symbols) <= set(self.limits.allowed_underlyings) or (
            (self.selection.max_quote_contracts + (1 if self.swing_policy else 0))
            * len(self.setup.symbols)
            > 8
        ):
            raise ValueError("Frozen strategy universe must fit the options owner")
        return self


class RuntimePacket(OptionRecord):
    version: Literal["option-normalized-fixture-v1"] = "option-normalized-fixture-v1"
    population_id: Name
    sequence: int = Field(ge=1, le=2**63 - 1, strict=True)
    recorded_at: datetime
    frame: DegenFrame
