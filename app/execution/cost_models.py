"""Frozen model cost limits; no ledger queries or entry-policy imports."""

from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.execution.contracts import Contract


class CostPolicy(Contract):
    model: str = Field(default="gpt-6-luna", min_length=1, max_length=128)
    input_per_million: Decimal = Field(default=Decimal(".10"), ge=0)
    output_per_million: Decimal = Field(default=Decimal(".50"), ge=0)
    total_budget: Decimal = Field(gt=0)
    daily_budget: Decimal = Field(gt=0)
    max_call_cost: Decimal = Field(default=Decimal(".01"), gt=0)

    @model_validator(mode="after")
    def bounded(self):
        if self.max_call_cost > min(self.total_budget, self.daily_budget):
            raise ValueError("Per-call cost reservation must fit both budgets")
        return self

    @field_validator("model")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("A model identity is required")
        return value

