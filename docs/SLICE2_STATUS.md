# Slice 2 — Robinhood Read / Shadow Status

## Implemented in bootstrap phase

- Re-verified Robinhood's public Agentic Trading documentation on 2026-09-08.
- Endpoint is configurable and defaults to `https://agent.robinhood.com/mcp/trading`.
- Uses the official MCP Python SDK v2 Streamable HTTP client path.
- OAuth authorization-code/PKCE flow is delegated to the MCP SDK.
- OAuth tokens and dynamic client registration metadata persist outside the repository by default.
- Tool schemas are discovered from the authenticated MCP server at runtime instead of guessed.
- Required Slice 2 tool names are checked against discovery.
- A capability firewall allows only read tools plus `review_equity_order`.
- `place_*`, `cancel_*`, and other mutation-oriented tools are rejected before any network call.
- Schema snapshots contain tool metadata/schema only, never account results or OAuth tokens.

## Empirical boundary / not yet proven

This environment is not authenticated to the user's Robinhood Agentic account and does not have
Robinhood's live tool schemas. Therefore the following remain intentionally unimplemented rather
than guessed:

1. Exact request/response adapters for account, portfolio, positions, orders, quotes, historicals,
   technical indicators, and tradability.
2. Broker-state reconciliation against real Robinhood account state.
3. Live-market `MarketPacket` construction.
4. SHADOW hypothetical order generation against the authenticated account.
5. `review_equity_order` request construction/comparison against paper assumptions.

The next empirical action is `python -m app.robinhood.cli discover` from an environment where the
account owner can complete Robinhood OAuth. Commit/redact only the schema snapshot if desired;
never commit the OAuth storage file.

## Live authority

No live brokerage placement or cancellation path is enabled in Slice 2 bootstrap. The Trader Agent
still has no brokerage tools.
