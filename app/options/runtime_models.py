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
from app.options.scope_arbitration import SharedScopePolicy
from app.options.scope_watch import ScopeWatchChoice
from app.options.selection import ContractSelectionPolicy
from app.options.swing import SwingPolicy


class RuntimePolicy(OptionRecord):
    version: Literal["option-local-runtime-v1"] = "option-local-runtime-v1"
    scope_inputs: Literal["scope-runtime-inputs-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
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
    scope_policy: SharedScopePolicy | None = Field(default=None, exclude_if=lambda v: v is None)
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
        if (
            self.execution.loss_control is not None
            and self.execution.loss_control.entry_cost_attribution is not None
            and self.entry_policy is None
        ):
            raise ValueError("Later-entry attribution requires native full-entry enrollment")
        if self.swing_policy is not None and model and self.entry_policy is None:
            raise ValueError("Shared AI families require full entry reasoning")
        if (self.scope_policy is not None) != (self.runtime.scope_inputs is not None) or (
            (self.scope_policy is not None) != (self.execution.scope_arbitration is not None)
        ):
            raise ValueError("Explicit matching Scope runtime/owner enrollment required")
        if self.scope_policy is not None:
            p = self.scope_policy.watch.context.structure.preflight
            if (
                self.scope_policy.version != self.execution.scope_arbitration
                or self.execution.scope_execution != "scope-native-v1"
                or (self.scope_policy.version == "shared-scope-entry-v1") != model
                or (self.swing_policy is not None) != ("SWING" in self.scope_policy.family_priority)
                or self.execution.loss_control is None
                or not set(self.scope_policy.family_priority)
                <= {f.family for f in self.execution.loss_control.families}
                or "SPX" not in self.limits.allowed_underlyings
                or p.provider != self.limits.provider
                or p.quote_source != self.limits.option_source
                or (
                    model
                    and (
                        self.entry_policy is None
                        or self.entry_policy.scope_selection != "scope-fixed-plan-v1"
                    )
                )
                or (
                    self.position_policy is not None
                    and (self.position_policy.scope_management != "scope-fixed-position-v1")
                )
            ):
                raise ValueError("Complete native Scope runtime configuration required")
        from app.options.scope_carry import validate_enrollment

        validate_enrollment(
            self.execution,
            self.scope_policy,
            self.swing_policy,
            self.entry_policy,
            self.position_policy,
        )
        age = self.execution.process_timeout_seconds + self.runtime.tick_seconds
        if age >= min(
            self.runtime.heartbeat_max_age_seconds,
            self.execution.supervisor_max_age_seconds,
            self.limits.account_max_age_seconds,
        ):
            raise ValueError("Supervisor process/tick budget must fit all freshness bounds")
        if not set(self.setup.symbols) <= set(self.limits.allowed_underlyings) or (
            (
                self.selection.max_quote_contracts
                + (
                    2
                    if self.swing_policy and self.swing_policy.family_batch
                    else 1
                    if self.swing_policy
                    else 0
                )
            )
            * len(self.setup.symbols)
            + (1 if self.scope_policy else 0)
            > 8
        ):
            raise ValueError("Frozen strategy universe must fit the options owner")
        return self


class _RuntimeEnvelope(OptionRecord):
    version: Literal["option-normalized-fixture-v1"] = "option-normalized-fixture-v1"
    population_id: Name
    sequence: int = Field(ge=1, le=2**63 - 1, strict=True)
    recorded_at: datetime
    frame: DegenFrame


class RuntimePacket(_RuntimeEnvelope):
    version: Literal["option-normalized-fixture-v1"] = "option-normalized-fixture-v1"

    @model_validator(mode="after")
    def legacy_boundary(self):
        if self.frame.scope is not None:
            raise ValueError("Scope inputs require an explicitly enrolled Scope runtime packet")
        return self


class ScopeRuntimeAction(OptionRecord):
    key: Name
    kind: Literal["CALL", "OBSERVE_ARMING", "ADVANCE", "NEUTRALIZE", "OBSERVE_QUOTE"]
    play_key: Name
    choice: ScopeWatchChoice | None = None

    @model_validator(mode="after")
    def locked_choice(self):
        if self.kind == "CALL":
            if self.key != self.play_key or self.choice is None:
                raise ValueError("CALL requires its own play key and locked choice")
        elif self.choice is not None:
            raise ValueError("Only CALL selects a locked choice")
        return self


class ScopeRuntimePacket(_RuntimeEnvelope):
    version: Literal["option-scope-fixture-v1"] = "option-scope-fixture-v1"
    kind: Literal["WATCH", "MARKET", "CYCLE"]
    action: ScopeRuntimeAction | None = None

    @model_validator(mode="after")
    def exact_inputs(self):
        if (self.kind == "WATCH") != (self.action is not None):
            raise ValueError("Only WATCH packets carry exactly one watch action")
        if self.action is not None:
            if self.frame.scope is None:
                if self.action.kind != "ADVANCE":
                    raise ValueError("Watch evidence required except for timer-only advance")
            elif self.action.play_key != self.frame.scope.play_key:
                raise ValueError("Exact watch play identity required")
        if self.kind != "CYCLE" and (
            self.frame.histories
            or self.frame.inventories
            or self.frame.swing
            or self.frame.swing_batches
        ):
            raise ValueError("Only CYCLE packets carry ordinary strategy inputs")
        return self
