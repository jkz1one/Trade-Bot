from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.robinhood.client import ToolClient


REQUIRED_SLICE2_READ_TOOLS = frozenset(
    {
        "get_accounts",
        "get_portfolio",
        "get_equity_positions",
        "get_equity_orders",
        "get_equity_quotes",
        "get_equity_historicals",
        "get_equity_technical_indicators",
        "get_equity_tradability",
    }
)

SAFE_SLICE2_TOOLS = REQUIRED_SLICE2_READ_TOOLS | frozenset(
    {
        "get_realized_pnl",
        "get_pnl_trade_history",
        "get_equity_fundamentals",
        "get_equity_price_book",
        "get_indexes",
        "get_index_quotes",
        "review_equity_order",
    }
)

FORBIDDEN_WRITE_PREFIXES = (
    "place_",
    "cancel_",
    "create_",
    "delete_",
    "exercise_",
    "update_",
    "add_",
    "remove_",
    "follow_",
    "unfollow_",
    "mark_",
)


class UnsafeRobinhoodToolError(RuntimeError):
    pass


def _wire_field(tool: dict[str, Any], camel: str, snake: str | None = None) -> Any:
    if camel in tool:
        return tool[camel]
    if snake and snake in tool:
        return tool[snake]
    return None


def _normalize_tool_metadata(tool: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for camel, snake in (
        ("name", None),
        ("description", None),
        ("inputSchema", "input_schema"),
        ("outputSchema", "output_schema"),
        ("annotations", None),
    ):
        value = _wire_field(tool, camel, snake)
        if value is not None:
            normalized[camel] = value
    return normalized


@dataclass(frozen=True)
class ToolSchemaSnapshot:
    captured_at: str
    endpoint: str
    tools: dict[str, dict[str, Any]]
    missing_required_tools: tuple[str, ...]
    missing_required_input_schemas: tuple[str, ...]
    advertised_write_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "endpoint": self.endpoint,
            "tools": self.tools,
            "missing_required_tools": list(self.missing_required_tools),
            "missing_required_input_schemas": list(self.missing_required_input_schemas),
            "advertised_write_tools": list(self.advertised_write_tools),
        }

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    def save_required(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            name: self.tools[name]
            for name in sorted(REQUIRED_SLICE2_READ_TOOLS | {"review_equity_order"})
            if name in self.tools
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


class RobinhoodSafeGateway:
    """Capability firewall around a generic MCP tool client."""

    def __init__(self, client: ToolClient, endpoint: str):
        self._client = client
        self.endpoint = endpoint

    async def discover_schemas(self) -> ToolSchemaSnapshot:
        tools = await self._client.list_tools()
        by_name: dict[str, dict[str, Any]] = {}
        advertised_writes: list[str] = []
        for raw_tool in tools:
            tool = _normalize_tool_metadata(raw_tool)
            name = str(tool.get("name", ""))
            if not name:
                continue
            by_name[name] = tool
            if name.startswith(FORBIDDEN_WRITE_PREFIXES):
                advertised_writes.append(name)
        missing = sorted(REQUIRED_SLICE2_READ_TOOLS - by_name.keys())
        missing_schemas = sorted(
            name
            for name in REQUIRED_SLICE2_READ_TOOLS
            if name in by_name and not isinstance(by_name[name].get("inputSchema"), dict)
        )
        return ToolSchemaSnapshot(
            captured_at=datetime.now(timezone.utc).isoformat(),
            endpoint=self.endpoint,
            tools=dict(sorted(by_name.items())),
            missing_required_tools=tuple(missing),
            missing_required_input_schemas=tuple(missing_schemas),
            advertised_write_tools=tuple(sorted(advertised_writes)),
        )

    async def call_safe(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in SAFE_SLICE2_TOOLS:
            raise UnsafeRobinhoodToolError(f"Robinhood tool is not permitted in Slice 2: {name}")
        return await self._client.call_tool(name, arguments)
