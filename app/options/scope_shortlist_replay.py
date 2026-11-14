"""Choice-only B fixture using the full native receipt and paid approval boundary."""

from typing import Literal

from pydantic import Field, model_validator

from app.options.models import Name, OptionRecord
from app.options.scope_replay_model import ScopeReplayModel


class ScopeShortlistDecision(OptionRecord):
    cycle_key: Name = Field(pattern=r"^degen:[0-9]+$")
    delay_seconds: int = Field(ge=0, le=600, strict=True)
    action: Literal["HOLD", "SELECT", "UNKNOWN"]
    scope: bool = Field(default=False, strict=True)
    candidate_index: int | None = Field(default=None, ge=0, le=23, strict=True)
    input_tokens: int = Field(default=1000, gt=0, le=1000000, strict=True)
    output_tokens: int = Field(default=100, ge=0, le=1000000, strict=True)

    @model_validator(mode="after")
    def choice(self):
        if (
            not self.cycle_key.startswith("degen:")
            or not self.cycle_key[6:].isascii()
            or not self.cycle_key[6:].isdigit()
        ):
            raise ValueError("Shortlist accepts only original entry slots")
        if self.action == "SELECT":
            if self.scope != (self.candidate_index is None):
                raise ValueError("Select the fixed Scope plan or one indexed ordinary candidate")
        elif self.scope or self.candidate_index is not None:
            raise ValueError("HOLD/UNKNOWN cannot select a candidate")
        return self


class ScopeShortlistScript(OptionRecord):
    version: Literal["scripted-scope-shortlist-v1"] = "scripted-scope-shortlist-v1"
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    arm: Literal["B"] = "B"
    decisions: tuple[ScopeShortlistDecision, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def slots(self):
        if len({d.cycle_key for d in self.decisions}) != len(self.decisions):
            raise ValueError("Unique shortlist slots required")
        return self


class ScopeShortlistModel(ScopeReplayModel):
    script_type = ScopeShortlistScript
    selection_policy = "scope-fixed-shortlist-v1"
