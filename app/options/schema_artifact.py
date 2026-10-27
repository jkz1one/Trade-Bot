"""Load either a schema export or its completed discovery report, without auth."""

import json
from typing import Literal

from pydantic import Field

from app.options.models import OptionRecord
from app.options.operator_inbox import read
from app.options.read_capture import CaptureResult
from app.options.read_gateway import ReadSchemas
from app.options.read_mapping import reviewed_schemas


class DiscoveryArtifact(OptionRecord):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    operation: Literal["discover"]
    status: Literal["COMPLETE"]
    execution_authority: Literal[False]
    normalized_data_verified: Literal[False]
    result: CaptureResult


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate schema artifact JSON key")
        result[key] = value
    return result


def load_reviewed_schemas(path):
    value = json.loads(read(path, 256 * 1024), object_pairs_hook=_pairs)
    if isinstance(value, dict) and "result" in value:
        result = DiscoveryArtifact.model_validate(value).result
        if result.operation != "DISCOVER" or result.status != "COMPLETE" or result.schemas is None:
            raise ValueError("Completed discovery schemas required")
        schemas = result.schemas
    else:
        schemas = ReadSchemas.model_validate(value)
    return reviewed_schemas(schemas)
