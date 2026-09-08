from __future__ import annotations

import json
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol


RedirectHandler = Callable[[str], Awaitable[None]]
CallbackHandler = Callable[[], Awaitable[Any]]


class ToolClient(Protocol):
    async def list_tools(self) -> list[dict[str, Any]]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class JsonOAuthStorage:
    """Persistent MCP OAuth storage with owner-only file permissions.

    The file is deliberately outside the repository by default. Both OAuth tokens and
    dynamic-registration client metadata are retained so subsequent connections can reuse
    the same authorization rather than registering a new client every run.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OAuth storage is invalid JSON: {self.path}") from exc

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp_name = tempfile.mkstemp(prefix=".oauth-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    async def get_tokens(self):
        raw = self._read().get("tokens")
        if raw is None:
            return None
        from mcp.shared.auth import OAuthToken

        return OAuthToken.model_validate(raw)

    async def set_tokens(self, tokens) -> None:
        payload = self._read()
        payload["tokens"] = tokens.model_dump(mode="json")
        self._write(payload)

    async def get_client_info(self):
        raw = self._read().get("client_info")
        if raw is None:
            return None
        from mcp.shared.auth import OAuthClientInformationFull

        return OAuthClientInformationFull.model_validate(raw)

    async def set_client_info(self, client_info) -> None:
        payload = self._read()
        payload["client_info"] = client_info.model_dump(mode="json")
        self._write(payload)


class McpSdkToolClient:
    """Thin adapter over the official MCP Python SDK v2 client.

    Imports are lazy so the deterministic PAPER core and unit tests do not require the MCP
    dependency unless Robinhood integration is actually used.
    """

    def __init__(self, client: Any):
        self._client = client

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._client.list_tools()
        return [tool.model_dump(mode="json") for tool in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._client.call_tool(name, arguments)
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        raise RuntimeError(f"Unexpected MCP result type for {name}: {type(result)!r}")


class RobinhoodMcpConnection:
    """Authenticated Streamable-HTTP connection to Robinhood Trading MCP.

    The OAuth provider performs discovery/PKCE/token refresh. This class does not know or
    store Robinhood credentials; it only persists OAuth tokens/client registration metadata.
    """

    def __init__(
        self,
        *,
        url: str,
        redirect_uri: str,
        oauth_storage_path: str | Path,
        redirect_handler: RedirectHandler,
        callback_handler: CallbackHandler,
    ):
        self.url = url
        self.redirect_uri = redirect_uri
        self.storage = JsonOAuthStorage(oauth_storage_path)
        self.redirect_handler = redirect_handler
        self.callback_handler = callback_handler

    @asynccontextmanager
    async def client(self) -> AsyncIterator[ToolClient]:
        try:
            import httpx2
            from mcp import Client
            from mcp.client.auth import OAuthClientProvider
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared.auth import OAuthClientMetadata
            from pydantic import AnyUrl
        except ImportError as exc:
            raise RuntimeError(
                "Robinhood integration requires the MCP Python SDK v2 dependencies. "
                "Install the project dependencies before running schema discovery."
            ) from exc

        oauth = OAuthClientProvider(
            server_url=self.url,
            client_metadata=OAuthClientMetadata(
                client_name="Trade-Bot",
                redirect_uris=[AnyUrl(self.redirect_uri)],
            ),
            storage=self.storage,
            redirect_handler=self.redirect_handler,
            callback_handler=self.callback_handler,
        )
        async with httpx2.AsyncClient(auth=oauth, follow_redirects=True) as http_client:
            transport = streamable_http_client(self.url, http_client=http_client)
            async with Client(transport) as client:
                yield McpSdkToolClient(client)
