# Autonomous Compounding Trader — Slice 1

Deterministic paper-trading core for testing whether a reasoning trader has alpha. Live brokerage writes are intentionally absent.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

The default database is `./trader.db` and default starting paper capital is `$10.00`.

## Safety boundary

The agent returns a structured proposal. It never receives an execution tool. The deterministic governor independently calculates executable notional and may approve, clip, or reject the proposal. Only the paper broker can execute in Slice 1.

## Slice 2 — Robinhood read/shadow bootstrap

`main` remains the known-good PAPER core. Slice 2 integration work lives on its own branch and
starts by discovering Robinhood's live MCP schemas rather than hardcoding undocumented shapes.

After installing dependencies, authenticate and capture the current tool schemas with:

```bash
python -m app.robinhood.cli discover
```

OAuth tokens/client-registration metadata are stored at `~/.trade-bot/robinhood-oauth.json` by
default with owner-only permissions. The generated `var/robinhood-tool-schemas.json` contains tool
metadata/schema only and is gitignored. Schema discovery makes no brokerage tool calls. The
Slice 2 gateway permits documented read tools plus `review_equity_order`; live placement,
cancellation, watchlist mutation, and other writes are rejected before network invocation.
