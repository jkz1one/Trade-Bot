"""Frozen execution contract primitives shared with the fixed native children."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value):
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Execution timestamps must be timezone-aware")
        return value

