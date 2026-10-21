"""Explicit local tape enrollment, separate from legacy scripted model cohorts."""

from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.entry_reasoning import Digest
from app.options.models import OptionRecord
from app.options.scope_replay_model import ScopeReplayModel, ScopeReplayScript
from app.options.scope_shortlist_replay import ScopeShortlistModel, ScopeShortlistScript


class ScopeReplayEnrollment(OptionRecord):
    version: Literal["scope-native-tape-model-v1"] = "scope-native-tape-model-v1"
    tape_hash: Digest
    request_hash: Digest
    script_hash: Digest


class ScopeSeriesEnrollment(OptionRecord):
    version: Literal["scope-native-series-model-v1"] = "scope-native-series-model-v1"
    tape_hashes: tuple[Digest, ...] = Field(min_length=2, max_length=60)
    request_hash: Digest
    script_hash: Digest

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.tape_hashes)) != len(self.tape_hashes):
            raise ValueError("Distinct ordered series tapes required")
        return self


def parse_enrollment(value):
    return TypeAdapter(ScopeReplayEnrollment | ScopeSeriesEnrollment).validate_python(value)


def validate_adapter(enrollment, adapter):
    enrollment = parse_enrollment(enrollment.model_dump(warnings=False))
    if (
        type(adapter) not in (ScopeReplayModel, ScopeShortlistModel)
        or fingerprint(adapter.script) != enrollment.script_hash
    ):
        raise ValueError("Exact full Scope replay script enrollment required")
    return enrollment


def validate_stored(config):
    try:
        enrollment = parse_enrollment(config["scope_replay"])
        script_type = (
            ScopeShortlistScript if config["replay_model"].get("arm") == "B" else ScopeReplayScript
        )
        script = script_type.model_validate(config["replay_model"])
        if (
            fingerprint(script) != enrollment.script_hash
            or config["model"]["key_file"] != "None"
            or (script.arm == "D") != ("position_model" in config)
            or config["entry_model"]["entry_policy"]["scope_selection"]
            != ("scope-fixed-shortlist-v1" if script.arm == "B" else "scope-fixed-plan-v1")
        ):
            raise ValueError("Scope replay configuration mismatch")
    except (KeyError, ValueError, TypeError) as exc:
        raise ExecutionBlocked("SHARED_SCOPE_REPLAY_CONFIGURATION_REQUIRED") from exc
    return enrollment
