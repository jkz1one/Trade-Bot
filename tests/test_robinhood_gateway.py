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
            {"name": "delete_alert", "inputSchema": {"type": "object"}},
            {"name": "exercise_option", "inputSchema": {"type": "object"}},
            {"name": "mark_alerts_read", "inputSchema": {"type": "object"}},
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
    assert snapshot.missing_required_input_schemas == ()
    assert "place_equity_order" in snapshot.advertised_write_tools
    assert "cancel_equity_order" in snapshot.advertised_write_tools
    assert "delete_alert" in snapshot.advertised_write_tools
    assert "exercise_option" in snapshot.advertised_write_tools
    assert "mark_alerts_read" in snapshot.advertised_write_tools
    assert client.calls == []

    output = tmp_path / "schemas.json"
    snapshot.save(output)
    saved = json.loads(output.read_text())
    assert set(REQUIRED_SLICE2_READ_TOOLS).issubset(saved["tools"])
    assert all("inputSchema" in saved["tools"][name] for name in REQUIRED_SLICE2_READ_TOOLS)
    assert "tokens" not in output.read_text().lower()


@pytest.mark.anyio
async def test_discovery_normalizes_mcp_v2_snake_case_schema_keys():
    client = FakeToolClient()

    async def snake_case_tools():
        return [
            {"name": name, "input_schema": {"type": "object", "properties": {}}}
            for name in sorted(REQUIRED_SLICE2_READ_TOOLS)
        ]

    client.list_tools = snake_case_tools
    snapshot = await RobinhoodSafeGateway(client, "endpoint").discover_schemas()
    assert snapshot.missing_required_input_schemas == ()
    assert snapshot.tools["get_accounts"]["inputSchema"]["type"] == "object"


@pytest.mark.anyio
async def test_discovery_reports_required_tool_without_input_schema():
    client = FakeToolClient()
    original = client.list_tools

    async def missing_schema():
        tools = await original()
        for tool in tools:
            if tool["name"] == "get_portfolio":
                tool.pop("inputSchema", None)
        return tools

    client.list_tools = missing_schema
    snapshot = await RobinhoodSafeGateway(client, "endpoint").discover_schemas()
    assert snapshot.missing_required_input_schemas == ("get_portfolio",)


@pytest.mark.anyio
async def test_safe_read_and_review_calls_are_forwarded():
    client = FakeToolClient()
    gateway = RobinhoodSafeGateway(client, "https://agent.robinhood.com/mcp/trading")
    await gateway.call_safe("get_portfolio", {"account_number": "fixture"})
    await gateway.call_safe("review_equity_order", {"fixture": True})
    assert [name for name, _ in client.calls] == ["get_portfolio", "review_equity_order"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name",
    [
        "place_equity_order",
        "cancel_equity_order",
        "create_watchlist",
        "delete_alert",
        "exercise_option",
        "mark_alerts_read",
    ],
)
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
