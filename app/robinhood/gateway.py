from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.robinhood.client import ToolClient


# Exact names currently documented by Robinhood and required by the Slice 2 handoff.
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

# Additional non-mutating tools useful to the experiment. Review simulates/previews an order;
# it does not place one. The Trader Agent never receives this gateway directly.
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

FORBIDDEN_WRITE_PREFIXES = ("place_", "cancel_", "create_", "update_", "add_", "remove_", "follow_", "unfollow_")


class UnsafeRobinhoodToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSchemaSnapshot:
    captured_at: str
    endpoint: str
    tools: dict[str, dict[str, Any]]
    missing_required_tools: tuple[str, ...]
    advertised_write_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "endpoint": self.endpoint,
            "tools": self.tools,
            "missing_required_tools": list(self.missing_required_tools),
            "advertised_write_tools": list(self.advertised_write_tools),
        }

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")


class RobinhoodSafeGateway:
    """Capability firewall around a generic MCP tool client.

    No method accepts arbitrary live brokerage writes. Even if Robinhood advertises placement
    tools during discovery, this gateway rejects them before a network call is made.
    """

    def __init__(self, client: ToolClient, endpoint: str):
        self._client = client
        self.endpoint = endpoint

    async def discover_schemas(self) -> ToolSchemaSnapshot:
        tools = await self._client.list_tools()
        by_name: dict[str, dict[str, Any]] = {}
        advertised_writes: list[str] = []
        for tool in tools:
            name = str(tool.get("name", ""))
            if not name:
                continue
            # Persist only public tool metadata/schema. Tool-call results/account data are not
            # part of schema discovery and therefore cannot leak into this snapshot.
            by_name[name] = {
                key: tool[key]
                for key in ("name", "description", "inputSchema", "outputSchema", "annotations")
                if key in tool
            }
            if name.startswith(FORBIDDEN_WRITE_PREFIXES):
                advertised_writes.append(name)
        missing = sorted(REQUIRED_SLICE2_READ_TOOLS - by_name.keys())
        return ToolSchemaSnapshot(
            captured_at=datetime.now(timezone.utc).isoformat(),
            endpoint=self.endpoint,
            tools=dict(sorted(by_name.items())),
            missing_required_tools=tuple(missing),
            advertised_write_tools=tuple(sorted(advertised_writes)),
        )

    async def call_safe(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in SAFE_SLICE2_TOOLS:
            raise UnsafeRobinhoodToolError(f"Robinhood tool is not permitted in Slice 2: {name}")
        return await self._client.call_tool(name, arguments)
