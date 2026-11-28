"""Separate combined carry response fixtures; no native or execution authority."""

from typing import Literal

from pydantic import Field

from app.options.scope_replay_model import (
    ScopeReplayModel,
    ScopeReplayScript,
    ScopeScriptedDecision,
)
from app.options.scope_shortlist_replay import ScopeShortlistModel, ScopeShortlistScript


class ScopeCarryDecision(ScopeScriptedDecision):
    horizon_seconds: int | None = Field(default=None, gt=0, le=5184000, strict=True)


class ScopeCarryScript(ScopeReplayScript):
    version: Literal["scripted-scope-carry-judgment-v1"] = "scripted-scope-carry-judgment-v1"
    decisions: tuple[ScopeCarryDecision, ...] = Field(max_length=100)


class ScopeCarryShortlistScript(ScopeShortlistScript):
    version: Literal["scripted-scope-carry-shortlist-v1"] = "scripted-scope-carry-shortlist-v1"


class ScopeCarryReplayModel(ScopeReplayModel):
    script_type = ScopeCarryScript
    carry_policy = "shared-scope-carry-v1"


class ScopeCarryShortlistModel(ScopeShortlistModel):
    script_type = ScopeCarryShortlistScript
    carry_policy = "shared-scope-carry-v1"
