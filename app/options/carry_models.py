"""Frozen Swing carry terms, independent of execution and model workers."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.options.models import Money, OptionRecord


class SwingCarryPolicy(OptionRecord):
    version: Literal["swing-carry-preflight-v1"] = "swing-carry-preflight-v1"
    maximum_carry_sessions: int = Field(strict=True, ge=1, le=20)
    maximum_calendar_days: int = Field(strict=True, ge=1, le=60)
    exit_before_close_minutes: int = Field(strict=True, ge=1, le=120)
    expiry_session_buffer: int = Field(strict=True, ge=1, le=5)


class CarrySession(OptionRecord):
    session: date
    opens_at: datetime
    closes_at: datetime


class SwingCarryTerms(OptionRecord):
    version: Literal["bounded-swing-carry-v1"] = "bounded-swing-carry-v1"
    seed_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    sessions: tuple[CarrySession, ...] = Field(min_length=2, max_length=21)
    exit_at: datetime
    first_target: Money = Field(gt=0)
    catalyst_valid_through: datetime

    @model_validator(mode="after")
    def ordered(self):
        if (
            any(s.opens_at >= s.closes_at for s in self.sessions)
            or any(a.closes_at >= b.opens_at for a, b in zip(self.sessions, self.sessions[1:]))
            or not self.sessions[-1].opens_at < self.exit_at < self.sessions[-1].closes_at
            or self.catalyst_valid_through < self.exit_at
        ):
            raise ValueError("Ordered carry sessions and covered final exit required")
        return self
