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
