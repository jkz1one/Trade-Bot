"""Fixed market-read capability and schema-pinned raw evidence, never execution inputs."""

import hashlib
import json
from datetime import datetime
from typing import Literal

from jsonschema.validators import validator_for
from pydantic import Field, JsonValue, model_validator
from referencing import Registry

from app.domain.models import utc_now
from app.options.models import Name, OptionRecord
from app.robinhood.gateway import UnsafeRobinhoodToolError, _normalize_tool_metadata

ENDPOINT = "https://agent.robinhood.com/mcp/trading"
ReadTool = Literal[
    "get_equity_historicals",
    "get_equity_quotes",
    "get_option_chains",
    "get_option_instruments",
    "get_option_quotes",
    "get_option_historicals",
]
READ_TOOLS = frozenset(ReadTool.__args__)
MAX_SCHEMA_BYTES = 128 * 1024
MAX_SAMPLE_BYTES = 128 * 1024
# Exact reviewed metadata revisions. The latter changes only the top-level
# get_equity_historicals description (completed-bar timing documentation).
# It does not change any input/output schema, tool identity or annotation.
REVIEWED_SCHEMA_SHA256 = "d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15"
COMPLETED_BARS_DESCRIPTION_SHA256 = "77f5aaac0e67dd9fb194d35bdbfb3779a351f52db8c6594a90dadd4f3fc5e272"
REVIEWED_SCHEMA_DIGESTS = frozenset({REVIEWED_SCHEMA_SHA256, COMPLETED_BARS_DESCRIPTION_SHA256})


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def schema_digest(tools):
    return hashlib.sha256(encoded(tools)).hexdigest()


class ReadSchemas(OptionRecord):
    endpoint: Literal[ENDPOINT] = ENDPOINT
    captured_at: datetime
    tools: dict[str, dict[str, JsonValue]]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    missing_tools: tuple[Name, ...]
    missing_input_schemas: tuple[Name, ...]
    missing_output_schemas: tuple[Name, ...]

    @model_validator(mode="after")
    def binding(self):
        if (
            set(self.tools) - READ_TOOLS
            or len(encoded(self.tools)) > MAX_SCHEMA_BYTES
            or schema_digest(self.tools) != self.sha256
        ):
            raise ValueError("Bounded fixed read schemas and matching digest required")
        if set(self.missing_tools) != READ_TOOLS - self.tools.keys():
            raise ValueError("Missing-tool evidence mismatch")
        for field, key in (
            (self.missing_input_schemas, "inputSchema"),
            (self.missing_output_schemas, "outputSchema"),
        ):
            if set(field) != {n for n, t in self.tools.items() if not isinstance(t.get(key), dict)}:
                raise ValueError("Missing-schema evidence mismatch")
        return self


def same_schema_contract(left, right):
    """Keep exact pins, with one reviewed description-only metadata revision.

    Never rewrite original schemas/digests, extend this exception to arbitrary
    descriptions, or ignore annotations and nested schema metadata.
    """
    if left is None or right is None:
        return False
    left = ReadSchemas.model_validate(left.model_dump(warnings=False))
    right = ReadSchemas.model_validate(right.model_dump(warnings=False))
    a, b = (s.model_dump(exclude={"captured_at"}) for s in (left, right))
    if a == b:
        return True
    if {left.sha256, right.sha256} != REVIEWED_SCHEMA_DIGESTS:
        return False
    for value in (a, b):
        del value["sha256"]
        value["tools"]["get_equity_historicals"].pop("description", None)
    return a == b


class ReadSample(OptionRecord):
    label: Name
    tool: ReadTool
    arguments: dict[str, JsonValue]

    @model_validator(mode="after")
    def bound(self):
        if len(encoded(self.arguments)) > 8192:
            raise ValueError("Read arguments exceed bound")
        return self


class CapturePlan(OptionRecord):
    purpose: Literal["SCHEMA_MAPPING_EVIDENCE"]
    symbols: tuple[Literal["SPY", "QQQ"], ...] = Field(min_length=1, max_length=2)
    instrument_ids: tuple[Name, ...] = Field(default=(), max_length=10)
    calls: tuple[ReadSample, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def distinct(self):
        if (
            len(set(self.symbols)) != len(self.symbols)
            or len(set(self.instrument_ids)) != len(self.instrument_ids)
            or len({c.label for c in self.calls}) != len(self.calls)
        ):
            raise ValueError("Unique declared subjects and call labels required")
        if any(c.tool == "get_option_quotes" for c in self.calls) and not self.instrument_ids:
            raise ValueError("Declare reviewed exact quote subjects")
        return self


def _validator(schema):
    # Explicit registry disables deprecated automatic remote reference retrieval.
    stack = [schema]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if any(
                k in value and (not isinstance(value[k], str) or not value[k].startswith("#"))
                for k in ("$ref", "$dynamicRef")
            ):
                raise ValueError("Only embedded schema references are supported")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    cls = validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, registry=Registry())


class OptionReadGateway:
    def __init__(self, client):
        self.client = client
        self.schemas = None
        self.inventory = None

    async def discover(self, *, include_inventory=False):
        self.inventory = None
        raw = await self.client.list_tools()
        if not isinstance(raw, list) or len(raw) > 256:
            raise ValueError("Bounded tool inventory required")
        seen, tools = set(), {}
        for item in raw:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or item["name"] in seen
            ):
                raise ValueError("Unique named tool metadata required")
            seen.add(item["name"])
            if item["name"] in READ_TOOLS:
                tools[item["name"]] = _normalize_tool_metadata(item)
        if include_inventory:
            from app.options.capability_inventory import build

            self.inventory = build(raw, READ_TOOLS)
        self.schemas = ReadSchemas(
            captured_at=utc_now(),
            tools=tools,
            sha256=schema_digest(tools),
            missing_tools=tuple(sorted(READ_TOOLS - tools.keys())),
            missing_input_schemas=tuple(
                sorted(n for n, t in tools.items() if not isinstance(t.get("inputSchema"), dict))
            ),
            missing_output_schemas=tuple(
                sorted(n for n, t in tools.items() if not isinstance(t.get("outputSchema"), dict))
            ),
        )
        return self.schemas

    def _pin(self, expected):
        if not same_schema_contract(self.schemas, expected):
            raise ValueError("Authenticated read schemas changed or were not discovered")

    def _validate_call(self, call):
        metadata = self.schemas.tools.get(call.tool)
        if metadata is None or not isinstance(metadata.get("inputSchema"), dict):
            raise ValueError("Required read input schema unavailable")
        annotations = metadata.get("annotations", {})
        if not isinstance(annotations, dict) or annotations.get("readOnlyHint") is False:
            raise ValueError("Conflicting read capability metadata")
        _validator(metadata["inputSchema"]).validate(call.arguments)
        if isinstance(metadata.get("outputSchema"), dict):
            _validator(metadata["outputSchema"])

    def validate_plan(self, plan, expected):
        self._pin(expected)
        plan = CapturePlan.model_validate(plan.model_dump(warnings=False))
        # Validate every call before the first request, including an invalid late call.
        for call in plan.calls:
            self._validate_call(call)
        return plan

    async def sample(self, call, expected):
        # Literal capability check precedes all client access, including malformed callers.
        if call.tool not in READ_TOOLS:
            raise UnsafeRobinhoodToolError("Outside fixed option market-read capability")
        call = ReadSample.model_validate(call.model_dump(warnings=False))
        self._pin(expected)
        self._validate_call(call)
        result = await self.client.call_tool(call.tool, call.arguments)
        if (
            not isinstance(result, dict)
            or len(encoded(result)) > MAX_SAMPLE_BYTES
            or not isinstance(result.get("isError", False), bool)
            or result.get("isError", False)
        ):
            raise ValueError("Failed, malformed or oversized MCP read sample")
        schema = self.schemas.tools[call.tool].get("outputSchema")
        checked = isinstance(schema, dict)
        if checked:
            if not isinstance(result.get("structuredContent"), dict):
                raise ValueError("Advertised structured output missing")
            _validator(schema).validate(result["structuredContent"])
        return result, checked
