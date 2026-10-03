# Slice 2 — Robinhood Read / Shadow Status

## Implemented

- Robinhood OAuth completed successfully against the user's Agentic Trading account on 2026-10-03.
- Live MCP discovery found 76 tools, 76 input schemas, and every required Slice 2 tool.
- MCP SDK v2 tool models are serialized with `by_alias=True` so `inputSchema` / `outputSchema` are preserved.
- OAuth state remains outside the repository.
- Exact live-schema adapters now cover:
  - accounts
  - portfolio / buying power
  - open equity positions
  - working equity orders
  - quotes
  - historical OHLCV bars
  - technical indicators
  - tradability
  - equity order review
- The account adapter uses Robinhood's unleveraged buying power as the v1 ceiling, so margin leverage cannot increase deterministic size.
- The market adapter batches quotes (up to 20) and tradability (10 per call). Historical OHLCV is intentionally fetched one symbol per call to remain below the MCP SDK's 1 MiB SSE-event ceiling; ATR, realized volatility, day change, and session VWAP relationship are then derived deterministically.
- Broker/local reconciliation halts new trading for unsupported asset value, multiple positions, unowned/missing positions, quantity/symbol disagreement, non-long positions, or working orders.
- SHADOW decisions use the same deterministic risk governor as PAPER.
- An approved SHADOW action may call `review_equity_order`; it never calls `place_equity_order` or a cancellation/mutation tool.
- PAPER and Robinhood state use separate SQLite files by default (`trader.db` and `robinhood.db`).
- The original PAPER runtime remains unchanged.
- Full local suite after this slice: **43/43 passing**. Python compile validation also passes.

## Commands

Safe live-read probe:

```bash
git pull
source .venv/bin/activate
python -m app.robinhood.cli probe
```

One SHADOW cycle with the deterministic stub agent:

```bash
python -m app.robinhood.cli shadow-cycle --agent stub
```

Once live-read evidence is clean, a reasoning-agent SHADOW cycle is available with:

```bash
python -m app.robinhood.cli shadow-cycle --agent openai
```

That requires the normal OpenAI API credentials. The Trader Agent receives no brokerage tools.

## Current empirical boundary

The request/response mappings are grounded in the authenticated Robinhood schemas, but the new adapters
have not yet been exercised against the user's live account responses. The next empirical checkpoint
is the `probe` command above. Its output masks the account number and makes no writes.

## Live authority

No live brokerage placement or cancellation path exists in Slice 2. The capability firewall still
permits only approved read tools plus `review_equity_order`.
