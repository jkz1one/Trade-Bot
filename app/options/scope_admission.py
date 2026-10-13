"""Frozen Scope debit envelope; native sizing remains in the common governor."""

from typing import Literal

from pydantic import Field

from app.options.models import Money, OptionRecord


class ScopeAdmissionPolicy(OptionRecord):
    version: Literal["scope-owned-admission-review-v1"] = "scope-owned-admission-review-v1"
    max_entry_debit: Money = Field(gt=0, le=500)
