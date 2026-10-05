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

Inspect persisted evidence without network calls:

```bash
python -m app.robinhood.cli shadow-audit
python -m app.robinhood.cli shadow-history --limit 100
python -m app.robinhood.cli shadow-outcomes --limit 100
```

New SHADOW cycles save their decision, exact model usage, account/benchmark snapshots and
reconciliation evidence atomically. Older cycles remain available, with unlinked usage explicitly
marked. Stub cycles use model identity `stub`. Model failures save HOLD and exit 8;
broker-review failures save their evidence and exit 9. Neither failure submits an order.

History shows action/failure/review counts, known model cost and raw SPY price observations.
It does not infer fills, strategy P&L or alpha. The authenticated model-to-SHADOW core
is verified; see `docs/SLICE2_STATUS.md` for evidence and remaining experiment work.

Regular-session scheduling (install the updated dependencies with `pip install -e '.[dev]'`):

```bash
python -m app.robinhood.cli shadow-run --agent openai --once
python -m app.robinhood.cli shadow-schedule-status
python -m app.robinhood.cli shadow-run --agent openai
```

For continuous operation on a Linux server, use the detached SHADOW service in
[docs/SHADOW_SERVER.md](docs/SHADOW_SERVER.md). It keeps state outside the code checkout,
restarts with Docker and uses private credential files. A separate password-protected
SHADOW observer reads saved history on a localhost-only port through an SSH tunnel.
The Mac can be shut down after migration and server verification.

The observer shows worker heartbeat/halt state, account snapshot age, model proposals,
deterministic risk results, review completion, linked model cost and forward quote
outcomes. Opening or refreshing it never runs a cycle or calls a broker/model.
It has no trading or recovery controls. The existing `app.main` remains PAPER-only.
See the server guide for access and the separate `app.web.shadow:create_shadow_app`
application; it refuses startup without SHADOW mode, LIVE disabled and a private
password file.

The foreground runner remains useful for local checks. Both runners poll every
30 seconds and attempt the current 15-minute XNYS regular-session slot, handling
holidays, early closes and daylight saving. Closed sessions skip broker/model calls.
Run only one runner against the brokerage account, including across different machines.

Persistent SQLite claims prevent duplicate scheduled cycles across restarts/workers
using the same database; missed slots are not replayed. An interrupted active claim
blocks new scheduled cycles until inspected and resolved, with no automatic expiry.
Session closure prevents model judgment or broker review as appropriate. Daily entry
review limits and exit cooldown persist. History distinguishes actual model HOLDs
from deterministic guards, stub decisions and unattributed legacy HOLDs.

New scheduled cycles also collect fixed 15/60-minute forward quote outcomes for
approved reviewed entries and model cash HOLDs, using already-read quotes. Outcomes
require fresh paired quotes from the same regular session and persist their source
and measurement cycle IDs. Missing observations expire without next-session backfill.
The local `shadow-outcomes` report compares quote changes with SPY after linked source
model cost. Initial output is EMPTY until new cycles are collected. These overlapping
proposal samples are separate from portfolio fills, profit and compounding returns.
