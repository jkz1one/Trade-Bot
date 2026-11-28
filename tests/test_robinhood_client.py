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


@pytest.mark.anyio
async def test_tool_inventory_follows_opaque_cursor_and_preserves_aliases():
    calls = []
    class Paged:
        async def list_tools(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(tools=[FakeToolModel()], next_cursor="opaque-page-2" if len(calls) == 1 else None)
    tools = await McpSdkToolClient(Paged()).list_tools()
    assert calls == [{}, {"cursor": "opaque-page-2"}]
    assert len(tools) == 2 and all("inputSchema" in t for t in tools)


@pytest.mark.anyio
@pytest.mark.parametrize("problem", ["repeat", "too_many_pages", "too_many_tools"])
async def test_partial_inventory_never_silently_looks_complete(problem):
    calls = []
    class Paged:
        async def list_tools(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                tools=[FakeToolModel()] * (257 if problem == "too_many_tools" else 1),
                next_cursor="repeat" if problem == "repeat" else str(len(calls)),
            )
    with pytest.raises(ValueError):
        await McpSdkToolClient(Paged()).list_tools()
    assert len(calls) <= 8


@pytest.mark.anyio
async def test_connection_progress_distinguishes_imports_from_session_initialization(tmp_path, monkeypatch):
    import mcp
    from app.robinhood.client import RobinhoodMcpConnection

    # No network is used; unrelated executor proxy configuration must not
    # instantiate an optional proxy transport before the fake MCP context.
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.delenv(name, raising=False)

    stages = []
    class OfflineClient:
        def __init__(self, transport):
            self.transport = transport
        async def __aenter__(self):
            assert stages == ['SDK_IMPORTS', 'OAUTH_SETUP', 'MCP_INITIALIZE']
            raise RuntimeError('PRIVATE_SESSION_DETAIL')
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(mcp, 'Client', OfflineClient)
    async def no_login(*args):
        pytest.fail('unexpected authorization')
    connection = RobinhoodMcpConnection(url='https://example.invalid/mcp',
        redirect_uri='http://127.0.0.1:8765/callback', oauth_storage_path=tmp_path/'unused.json',
        redirect_handler=no_login, callback_handler=no_login)
    connection.connection_progress = stages.append
    with pytest.raises(RuntimeError, match='PRIVATE_SESSION_DETAIL'):
        async with connection.client():
            pytest.fail('failed session yielded a client')
    assert stages == ['SDK_IMPORTS', 'OAUTH_SETUP', 'MCP_INITIALIZE']
    assert not (tmp_path/'unused.json').exists()
