from __future__ import annotations

import argparse
import asyncio
import json
import webbrowser
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.robinhood.client import RobinhoodMcpConnection
from app.robinhood.gateway import RobinhoodSafeGateway


async def _open_browser(url: str) -> None:
    print("Open this Robinhood authorization URL if a browser does not open automatically:")
    print(url)
    webbrowser.open(url)


async def _wait_for_callback():
    try:
        from mcp.client.auth import AuthorizationCodeResult
    except ImportError as exc:
        raise RuntimeError("Install project dependencies before Robinhood OAuth") from exc

    redirected = input("Paste the full URL Robinhood redirected your browser to: ").strip()
    params = parse_qs(urlparse(redirected).query)
    if "code" not in params or "state" not in params:
        raise RuntimeError("OAuth callback URL is missing code/state")
    return AuthorizationCodeResult(
        code=params["code"][0],
        state=params["state"][0],
        iss=params.get("iss", [None])[0],
    )


async def discover(settings: Settings, output: str) -> int:
    connection = RobinhoodMcpConnection(
        url=settings.robinhood_mcp_url,
        redirect_uri=settings.robinhood_redirect_uri,
        oauth_storage_path=settings.robinhood_oauth_storage,
        redirect_handler=_open_browser,
        callback_handler=_wait_for_callback,
    )
    async with connection.client() as client:
        gateway = RobinhoodSafeGateway(client, settings.robinhood_mcp_url)
        snapshot = await gateway.discover_schemas()
    snapshot.save(output)
    print(json.dumps({
        "saved": output,
        "tool_count": len(snapshot.tools),
        "missing_required_tools": snapshot.missing_required_tools,
        "advertised_write_tools": snapshot.advertised_write_tools,
    }, indent=2))
    return 2 if snapshot.missing_required_tools else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Robinhood MCP schema discovery for Trade-Bot")
    parser.add_argument("command", choices=["discover"])
    parser.add_argument("--output", default="var/robinhood-tool-schemas.json")
    args = parser.parse_args()
    settings = Settings()
    raise SystemExit(asyncio.run(discover(settings, args.output)))


if __name__ == "__main__":
    main()
