# Autonomous Compounding Trader

Small, auditable experiment for testing whether an autonomous reasoning trader can add value while deterministic software owns authority and risk.

## PAPER

`main` is the known-good deterministic PAPER core.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

The default PAPER database is `./trader.db` and starting capital is `$10.00`.

## Safety boundary

The Trader Agent returns only a structured proposal. It has no brokerage write tools. The deterministic governor independently approves, clips, or rejects size.

## Slice 2 — Robinhood read / SHADOW

Development lives on `slice2/robinhood-read-shadow`.

Robinhood OAuth state is stored outside the repository at `~/.trade-bot/robinhood-oauth.json` by default. Never commit or share that file.

Schema discovery:

```bash
python -m app.robinhood.cli discover
```

Safe authenticated read/reconciliation probe:

```bash
python -m app.robinhood.cli probe
```

One SHADOW cycle, no model cost:

```bash
python -m app.robinhood.cli shadow-cycle --agent stub
```

One SHADOW cycle using the reasoning agent:

```bash
python -m app.robinhood.cli shadow-cycle --agent openai
```

SHADOW uses real Robinhood account/market data and may call `review_equity_order` to preview a hypothetical order. It cannot place or cancel an order. Robinhood-backed state is stored separately in `./robinhood.db` by default.
