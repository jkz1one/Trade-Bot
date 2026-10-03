# Slice 2 — Robinhood Read / Shadow Status

## Implemented

- Robinhood OAuth completed successfully against the user's Agentic Trading account on 2026-10-03.
- Live MCP discovery found 76 tools and all required Slice 2 tool names.
- Endpoint remains `https://agent.robinhood.com/mcp/trading`.
- Uses the official MCP Python SDK v2 Streamable HTTP client path.
- OAuth tokens and dynamic client registration metadata persist outside the repository by default.
- MCP SDK v2 tool models are serialized with `by_alias=True` so wire-format `inputSchema` /
  `outputSchema` fields are preserved.
- Discovery now fails evidence validation when a required tool exists but its input schema is absent.
- A compact `var/robinhood-required-schemas.json` snapshot is emitted for the Slice 2 tools.
- The capability firewall allows only read tools plus `review_equity_order`.
- Write-like prefixes including `place_`, `cancel_`, `create_`, `delete_`, `exercise_`,
  `update_`, `add_`, `remove_`, `follow_`, `unfollow_`, and `mark_` are blocked.
- Robinhood's non-fatal HTTP 400 response to MCP session DELETE is avoided with
  `terminate_on_close=False`.

## Current empirical boundary

The first authenticated capture proved the tool catalog but exposed an SDK-v2 serialization bug:
the saved snapshot contained descriptions/annotations but no `inputSchema` fields. That bug is now
fixed and covered by focused tests. The authenticated discovery must be run once more so the exact
request schemas can be captured before request/response adapters are implemented.

Next command on the already-authorized machine:

```bash
git pull
python -m app.robinhood.cli discover
cat var/robinhood-required-schemas.json
```

Do not commit or share `~/.trade-bot/robinhood-oauth.json`.

## Remaining after schema recapture

1. Exact request/response adapters for account, portfolio, positions, orders, quotes, historicals,
   technical indicators, and tradability.
2. Broker-state reconciliation against real Robinhood account state.
3. Live-market `MarketPacket` construction.
4. SHADOW hypothetical order generation.
5. `review_equity_order` comparison against deterministic paper assumptions.

## Live authority

No live brokerage placement or cancellation path is enabled in Slice 2. The Trader Agent still has
no brokerage write tools.
