"""Exact mixed tape/script enrollment; old adapters retain their own contracts."""

from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.mixed.replay_model import MixedReplayModel, MixedReplayScript
from app.options.engine import fingerprint
from app.options.entry_reasoning import Digest
from app.options.models import OptionRecord


class MixedReplayEnrollment(OptionRecord):
    version: Literal["mixed-native-series-model-v1"] = "mixed-native-series-model-v1"
    tape_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=60)
    request_hash: Digest
    script_hash: Digest

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.tape_hashes)) != len(self.tape_hashes):
            raise ValueError("Distinct original mixed session tapes required")
        return self


def validate_adapter(enrollment, adapter):
    enrollment = MixedReplayEnrollment.model_validate(enrollment.model_dump(warnings=False))
    if (
        type(adapter) is not MixedReplayModel
        or fingerprint(adapter.script) != enrollment.script_hash
    ):
        raise ValueError("Exact complete mixed replay adapter required")
    return enrollment


def validate_stored(config):
    try:
        enrollment = MixedReplayEnrollment.model_validate(config["mixed_replay"])
        script = MixedReplayScript.model_validate(config["replay_model"])
        entry = config["entry_model"]["entry_policy"]
        if (
            fingerprint(script) != enrollment.script_hash
            or config["model"]["key_file"] != "None"
            or "scope_replay" in config
            or (script.arm == "D") != ("position_model" in config)
            or entry.get("mixed_selection") != "mixed-paid-entry-v1"
            or (entry.get("mixed_shortlist") == "mixed-choice-only-v1") != (script.arm == "B")
            or config["stocks"].get("paid_selection") != "mixed-paid-entry-v1"
            or (
                script.arm == "D"
                and config["position_model"]["position_policy"].get("mixed_management")
                != "mixed-stock-position-v1"
            )
        ):
            raise ValueError("Mixed replay configuration changed")
    except (KeyError, ValueError, TypeError) as exc:
        raise ExecutionBlocked("MIXED_REPLAY_CONFIGURATION_REQUIRED") from exc
    return enrollment
