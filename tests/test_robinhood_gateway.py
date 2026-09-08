from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.robinhood.gateway import (
    REQUIRED_SLICE2_READ_TOOLS,
    RobinhoodSafeGateway,
    UnsafeRobinhoodToolError,
)


class FakeToolClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        tools = [
            {"name": name, "description": f"schema for {name}", "inputSchema": {"type": "object"}}
            for name in sorted(REQUIRED_SLICE2_READ_TOOLS)
        ]
        tools += [
            {"name": "review_equity_order", "inputSchema": {"type": "object"}},
            {"name": "place_equity_order", "inputSchema": {"type": "object"}},
            {"name": "cancel_equity_order", "inputSchema": {"type": "object"}},
        ]
        return tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"name": name, "arguments": arguments, "ok": True}


@pytest.mark.anyio
async def test_discovery_records_schemas_but_does_not_call_tools(tmp_path: Path):
    client = FakeToolClient()
    gateway = RobinhoodSafeGateway(client, "https://agent.robinhood.com/mcp/trading")
    snapshot = await gateway.discover_schemas()
    assert snapshot.missing_required_tools == ()
    assert "place_equity_order" in snapshot.advertised_write_tools
    assert "cancel_equity_order" in snapshot.advertised_write_tools
    assert client.calls == []

    output = tmp_path / "schemas.json"
    snapshot.save(output)
    saved = json.loads(output.read_text())
    assert set(REQUIRED_SLICE2_READ_TOOLS).issubset(saved["tools"])
    assert "tokens" not in output.read_text().lower()


@pytest.mark.anyio
async def test_safe_read_and_review_calls_are_forwarded():
    client = FakeToolClient()
    gateway = RobinhoodSafeGateway(client, "https://agent.robinhood.com/mcp/trading")
    await gateway.call_safe("get_portfolio", {"account_id": "fixture"})
    await gateway.call_safe("review_equity_order", {"fixture": True})
    assert [name for name, _ in client.calls] == ["get_portfolio", "review_equity_order"]


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["place_equity_order", "cancel_equity_order", "create_watchlist"])
async def test_live_writes_are_blocked_before_network_call(name):
    client = FakeToolClient()
    gateway = RobinhoodSafeGateway(client, "https://agent.robinhood.com/mcp/trading")
    with pytest.raises(UnsafeRobinhoodToolError):
        await gateway.call_safe(name, {})
    assert client.calls == []


@pytest.mark.anyio
async def test_missing_required_schema_fails_discovery_evidence():
    client = FakeToolClient()
    original = client.list_tools

    async def incomplete():
        return [tool for tool in await original() if tool["name"] != "get_equity_quotes"]

    client.list_tools = incomplete
    snapshot = await RobinhoodSafeGateway(client, "endpoint").discover_schemas()
    assert snapshot.missing_required_tools == ("get_equity_quotes",)
