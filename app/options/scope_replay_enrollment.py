"""Explicit local tape enrollment, separate from legacy scripted model cohorts."""

from typing import Literal

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.entry_reasoning import Digest
from app.options.models import OptionRecord
from app.options.scope_replay_model import ScopeReplayModel, ScopeReplayScript


class ScopeReplayEnrollment(OptionRecord):
    version: Literal["scope-native-tape-model-v1"] = "scope-native-tape-model-v1"
    tape_hash: Digest
    request_hash: Digest
    script_hash: Digest


def validate_adapter(enrollment, adapter):
    enrollment = ScopeReplayEnrollment.model_validate(enrollment.model_dump(warnings=False))
    if (
        type(adapter) is not ScopeReplayModel
        or fingerprint(adapter.script) != enrollment.script_hash
    ):
        raise ValueError("Exact full Scope replay script enrollment required")
    return enrollment


def validate_stored(config):
    try:
        enrollment = ScopeReplayEnrollment.model_validate(config["scope_replay"])
        script = ScopeReplayScript.model_validate(config["replay_model"])
        if (
            fingerprint(script) != enrollment.script_hash
            or config["model"]["key_file"] != "None"
            or (script.arm == "D") != ("position_model" in config)
        ):
            raise ValueError("Scope replay configuration mismatch")
    except (KeyError, ValueError, TypeError) as exc:
        raise ExecutionBlocked("SHARED_SCOPE_REPLAY_CONFIGURATION_REQUIRED") from exc
    return enrollment
