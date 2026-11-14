"""Fixed bounded headless Robinhood market reader. No trading/account authority output."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

from app.domain.models import utc_now
from app.execution.market_reads import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MarketReadDiagnostics,
    MarketReadRequest,
    MarketReadResult,
    private_oauth,
    source_hash,
)
from app.execution.market_validation import PaperMarketReadGateway
from app.robinhood.client import JsonOAuthStorage, RobinhoodMcpConnection
from app.robinhood.market import RobinhoodMarketData
from app.robinhood.read import RobinhoodReadService


async def authorization_required(*args):
    raise RuntimeError("Existing headless authorization required")


class PrivateOAuthStorage(JsonOAuthStorage):
    def _read(self):
        return private_oauth(self.path)

    def _write(self, payload):
        private_oauth(self.path)
        if len(json.dumps(payload).encode()) > 64 * 1024:
            raise ValueError("OAuth refresh exceeded private storage bound")
        super()._write(payload)  # OAuth refresh persistence only, never a broker mutation.


def connection(policy):
    result = RobinhoodMcpConnection(
        url=policy.endpoint,
        redirect_uri=policy.redirect_uri,
        oauth_storage_path=policy.oauth_file,
        redirect_handler=authorization_required,
        callback_handler=authorization_required,
    )
    result.storage = PrivateOAuthStorage(policy.oauth_file)
    return result


class ObservedGateway(PaperMarketReadGateway):
    """Count/timestamp only the four fixed safe calls, retaining no arguments/results."""

    def __init__(self, client, endpoint):
        super().__init__(client, endpoint)
        self.observations = {
            name: {"attempted": 0, "completed": 0, "elapsed_seconds": 0.0}
            for name in (
                "get_accounts",
                "get_equity_quotes",
                "get_equity_tradability",
                "get_equity_historicals",
            )
        }

    async def call_safe(self, name, arguments):
        if name not in self.observations:
            return await super().call_safe(name, arguments)
        observation = self.observations[name]
        observation["attempted"] += 1
        started = time.monotonic()
        try:
            result = await super().call_safe(name, arguments)
            observation["completed"] += 1
            return result
        finally:
            observation["elapsed_seconds"] += time.monotonic() - started


async def collect(request):
    started = time.monotonic()
    private_oauth(request.policy.oauth_file)
    async with connection(request.policy).client() as client:
        gateway = ObservedGateway(client, request.policy.endpoint)
        account = await RobinhoodReadService(gateway).get_agentic_account()
        market = RobinhoodMarketData(
            gateway,
            interval=request.policy.interval,
            lookback_days=request.policy.lookback_days,
        )
        candidates = await market.candidates(account.account_number, request.symbols)
        collected_at = utc_now()
        regime = market.regime(candidates)
    return MarketReadResult(
        feed_id=request.feed_id,
        request_id=request.request_id,
        source_hash=source_hash(request.policy),
        collected_at=collected_at,
        candidates=candidates,
        regime=regime,
        diagnostics=MarketReadDiagnostics(
            collection_seconds=time.monotonic() - started, **gateway.observations
        ),
    )


def _watch(request):
    while os.getppid() == request.parent_pid and time.monotonic() < request.deadline_monotonic:
        time.sleep(0.05)
    os._exit(92)


def main():
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            return 1
        request = MarketReadRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid or time.monotonic() >= request.deadline_monotonic:
            return 1
        threading.Thread(target=_watch, args=(request,), daemon=True).start()
        result = asyncio.run(collect(request))
        output = result.model_dump_json().encode()
        if len(output) > MAX_RESPONSE_BYTES:
            return 1
        sys.stdout.buffer.write(output)
        return 0
    except Exception:  # noqa: BLE001 -- never echo account/token/MCP responses
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
