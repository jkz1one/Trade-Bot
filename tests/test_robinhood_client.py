from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.robinhood.client import McpSdkToolClient


class FakeToolModel:
    def model_dump(self, *, mode, by_alias=False):
        assert mode == "json"
        assert by_alias is True
        return {"name": "get_accounts", "inputSchema": {"type": "object"}}


class FakeResultModel:
    def model_dump(self, *, mode, by_alias=False):
        assert mode == "json"
        assert by_alias is True
        return {"structuredContent": {"ok": True}}


class FakeSdkClient:
    async def list_tools(self):
        return SimpleNamespace(tools=[FakeToolModel()])

    async def call_tool(self, name, arguments):
        return FakeResultModel()


@pytest.mark.anyio
async def test_mcp_adapter_serializes_v2_models_with_wire_aliases():
    client = McpSdkToolClient(FakeSdkClient())
    tools = await client.list_tools()
    assert tools[0]["inputSchema"] == {"type": "object"}
    result = await client.call_tool("get_accounts", {})
    assert result == {"structuredContent": {"ok": True}}
