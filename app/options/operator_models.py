"""Options-specific signed recovery envelopes, never trading proposals."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.options.models import Name, OptionRecord


class OptionsCommand(OptionRecord):
    version: Literal["options-operator-v1"] = "options-operator-v1"
    journal_id: str = Field(min_length=1, max_length=64)
    population_id: Name
    command_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    credential_generation: int = Field(ge=1, strict=True)
    actor: str = Field(min_length=1, max_length=80)
    action: Literal["HALT", "RESUME", "REVOKE_KEY", "RESET_LOSS_LOCK"]
    loss_family: Literal["DEGEN", "SWING"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    reason: str = Field(min_length=1, max_length=300)
    expected_revision: int = Field(ge=0, le=2**63 - 1, strict=True)
    issued_at: datetime
    expires_at: datetime

    @field_validator("journal_id", "actor", "reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Nonblank operator fields required")
        return value

    @model_validator(mode="after")
    def lifetime(self):
        if self.loss_family is not None and self.action != "RESET_LOSS_LOCK":
            raise ValueError("A family target is valid only for a loss reset")
        if not 0 < (self.expires_at - self.issued_at).total_seconds() <= 300:
            raise ValueError("Positive command lifetime of at most five minutes required")
        return self


class SignedOptionsCommand(OptionRecord):
    command: OptionsCommand
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")
