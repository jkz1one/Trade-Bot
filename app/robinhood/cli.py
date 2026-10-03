from __future__ import annotations

import argparse
import asyncio
import json
import os
import webbrowser
from urllib.parse import parse_qs, urlparse

from app.agent.trader import OpenAIAgentsTrader, StubTraderAgent
from app.config import Settings
from app.robinhood.client import RobinhoodMcpConnection
from app.robinhood.gateway import RobinhoodSafeGateway
from app.robinhood.market import RobinhoodMarketData
from app.robinhood.read import RobinhoodReadService
from app.robinhood.reconcile import reconcile_truth
from app.robinhood.shadow import ShadowOrchestrator
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository


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


def _connection(settings: Settings) -> RobinhoodMcpConnection:
    return RobinhoodMcpConnection(
        url=settings.robinhood_mcp_url,
        redirect_uri=settings.robinhood_redirect_uri,
        oauth_storage_path=settings.robinhood_oauth_storage,
        redirect_handler=_open_browser,
        callback_handler=_wait_for_callback,
    )


def _repo(settings: Settings) -> Repository:
    engine = make_engine(settings.robinhood_db_url)
    init_db(engine)
    return Repository(make_session_factory(engine))


def _mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) >= 4 else "••••"


def _openai_key_problem(value: str | None) -> str | None:
    if not value:
        return "OPENAI_API_KEY is not set"
    cleaned = value.strip()
    placeholders = {
        "YOUR_API_KEY",
        "your-api-key",
        "your-key-here",
        "...",
        "sk-...",
    }
    if cleaned in placeholders or "YOUR_API_KEY" in cleaned.upper():
        return "OPENAI_API_KEY is still a placeholder, not a real API key"
    if len(cleaned) < 20:
        return "OPENAI_API_KEY is too short to look like a real API key"
    return None


async def discover(settings: Settings, output: str, required_output: str) -> int:
    async with _connection(settings).client() as client:
        gateway = RobinhoodSafeGateway(client, settings.robinhood_mcp_url)
        snapshot = await gateway.discover_schemas()
    snapshot.save(output)
    snapshot.save_required(required_output)
    schema_count = sum(
        1 for tool in snapshot.tools.values() if isinstance(tool.get("inputSchema"), dict)
    )
    print(json.dumps({
        "saved": output,
        "required_saved": required_output,
        "tool_count": len(snapshot.tools),
        "input_schema_count": schema_count,
        "missing_required_tools": snapshot.missing_required_tools,
        "missing_required_input_schemas": snapshot.missing_required_input_schemas,
        "advertised_write_tools": snapshot.advertised_write_tools,
    }, indent=2))
    incomplete = snapshot.missing_required_tools or snapshot.missing_required_input_schemas
    return 2 if incomplete else 0


async def probe(settings: Settings) -> int:
    repo = _repo(settings)
    async with _connection(settings).client() as client:
        gateway = RobinhoodSafeGateway(client, settings.robinhood_mcp_url)
        reads = RobinhoodReadService(gateway)
        truth = await reads.truth()
        market = RobinhoodMarketData(
            gateway,
            interval=settings.shadow_bar_interval,
            lookback_days=settings.shadow_lookback_days,
        )
        candidates = await market.candidates(
            truth.account.account_number,
            settings.initial_symbols,
        )
    reconciliation = reconcile_truth(repo, truth)
    print(json.dumps({
        "account": _mask(truth.account.account_number),
        "account_type": truth.account.type,
        "brokerage_account_type": truth.account.brokerage_account_type,
        "portfolio_value": str(truth.portfolio.total_value),
        "cash": str(truth.portfolio.cash),
        "safe_buying_power": str(truth.portfolio.buying_power),
        "equity_positions": [p.symbol for p in truth.positions],
        "working_order_count": len(truth.working_orders),
        "reconciled": reconciliation.reconciled,
        "reconciliation_reasons": reconciliation.reasons,
        "candidate_count": len(candidates),
        "candidate_symbols": [c.quote.symbol for c in candidates],
        "regime": market.regime(candidates),
    }, indent=2))
    return 0 if reconciliation.reconciled else 3


def shadow_audit(settings: Settings) -> int:
    repo = _repo(settings)
    rows = repo.recent_cycles(limit=1)
    if not rows:
        print(json.dumps({
            "status": "EMPTY",
            "message": "No SHADOW decision cycles are persisted yet.",
        }, indent=2))
        return 5
    row = rows[0]
    usage = repo.latest_model_usage()
    payload = {
        "cycle_id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "prompt_version": row.prompt_version,
        "model": row.model_identifier,
        "latency_ms": row.latency_ms,
        "decision": json.loads(row.decision_json),
        "risk": json.loads(row.risk_json),
        "execution": json.loads(row.execution_json),
        "latest_model_usage": (
            {
                "model": usage.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "estimated_cost": str(usage.estimated_cost),
            }
            if usage is not None
            else None
        ),
        "model_cost_total": str(repo.model_cost_total()),
        "benchmark_range": (
            [str(x) for x in repo.benchmark_range(settings.benchmark_symbol)]
            if repo.benchmark_range(settings.benchmark_symbol)
            else None
        ),
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


async def shadow_cycle(settings: Settings, agent_name: str) -> int:
    if agent_name == "openai":
        key_problem = _openai_key_problem(os.getenv("OPENAI_API_KEY"))
        if key_problem:
            print(json.dumps({
                "error": key_problem,
                "action": (
                    "No Robinhood calls or model calls were made. Set a real OpenAI API key, "
                    "not the example placeholder."
                ),
            }, indent=2))
            return 4
    settings = settings.model_copy(update={"mode": "SHADOW", "live_enabled": False})
    repo = _repo(settings)
    agent = (
        OpenAIAgentsTrader(settings.model_name)
        if agent_name == "openai"
        else StubTraderAgent()
    )
    async with _connection(settings).client() as client:
        gateway = RobinhoodSafeGateway(client, settings.robinhood_mcp_url)
        orchestrator = ShadowOrchestrator(settings, repo, gateway, agent)
        packet, decision, risk, execution, reconciliation, truth = (
            await orchestrator.cycle()
        )
    print(json.dumps({
        "account": _mask(truth.account.account_number),
        "reconciled": reconciliation.reconciled,
        "reconciliation_reasons": reconciliation.reasons,
        "candidate_count": len(packet.candidates),
        "regime": packet.regime,
        "decision": decision.model_dump(mode="json"),
        "risk": risk.model_dump(mode="json"),
        "execution": execution.model_dump(mode="json"),
    }, indent=2, default=str))
    return 0 if reconciliation.reconciled else 3


def main() -> None:
    parser = argparse.ArgumentParser(description="Robinhood MCP tools for Trade-Bot")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--output", default="var/robinhood-tool-schemas.json")
    d.add_argument(
        "--required-output",
        default="var/robinhood-required-schemas.json",
    )
    sub.add_parser("probe")
    sub.add_parser("shadow-audit")
    s = sub.add_parser("shadow-cycle")
    s.add_argument("--agent", choices=["stub", "openai"], default="stub")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "discover":
        code = asyncio.run(discover(settings, args.output, args.required_output))
    elif args.command == "probe":
        code = asyncio.run(probe(settings))
    elif args.command == "shadow-audit":
        code = shadow_audit(settings)
    else:
        code = asyncio.run(shadow_cycle(settings, args.agent))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
