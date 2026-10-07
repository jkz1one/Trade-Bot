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

An offline [execution lifecycle rehearsal](docs/EXECUTION_REHEARSAL.md) now tests durable
approved intents, partial fills, uncertain acknowledgments, restart recovery,
deterministic stop/session exits and a persistent dispatch halt using a local fake
venue. Frozen account/dollar limits and fresh-market dispatch reapproval also pass
offline verification. A separate durable fake venue now verifies killable submission/read
deadlines and cancellation/crash recovery. It has no broker write adapter and
does not change the deployed SHADOW experiment.
Signed local operator commands now test atomic halt/recovery, revision checks,
replay receipts and persistent alert acknowledgment. Deployed notification and
recovery integration remain pending.
Credential rotation/revocation retain a dispatch halt and reject retired keys.
An opt-in separate authority file blocks journal-only rollback before any write.
Rolling back both files together remains outside this local safeguard.
Opt-in model-cost receipts now freeze configured rates/budgets, block entries on
unknown costs, and include reasoning charges in economic loss limits. Broker cash
stays separate and deterministic protective exits remain available.
The optional fixture-engine judgment coordinator now counts the exact Responses
request before one tool-less generation, caps output, and atomically records response
identity/usage with the decision. It has no broker capability or deployed-worker wiring.
An opt-in independent fixture supervisor now reconciles complete account history,
checks a durable quote feed and dispatches only governed protective SELL intents.
Fresh completed supervision is required for new model calls and BUY admission;
stale reads, duplicate runners and interrupted recovery cannot renew entry authority.
This remains offline infrastructure, with no deployed service or broker writes.
An isolated native-TLS control API now exposes bounded operator review and signed
recovery actions, including reviewed interruption resolution without replay. Separate read/signing credentials, reviewed revisions,
restore fencing and durable replay receipts remain mandatory. It is not deployed and
adds no routes to the current SHADOW observer or PAPER app.
Opt-in HTTPS alert delivery now freezes a dedicated sink, persists attempts before sending,
requires an exact acceptance receipt and retries the same alert ID within a bounded batch.
Overdue/exhausted delivery blocks new entries and model calls; governed protective exits
retain their existing checks. Delivery never acknowledges an alert or resumes execution.
This is verified with a local TLS sink; no external notifications or server changes were made.
Private [execution evidence checkpoints](docs/EXECUTION_CHECKPOINTS.md) now capture the
journal/authority pair consistently, support explicit verified-TLS archive retention/retrieval,
and require an independently retained hash before recovery staging. Recovery preserves
unresolved evidence and supplies no usable execution authority. Archive provisioning and
actual off-host/host-failure verification remain pending; deployed SHADOW backups are unchanged.

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

New isolated PAPER populations can explicitly bind their quote feed to the bounded
Robinhood market-only collector. Its headless child returns no real account values;
the engine supplies virtual ledger authority. Existing fixture populations and the
deployed worker remain separate. Add `--continuous-market` at initialization to
compose repeated bounded refreshes into that population's PAPER runtime. Cold flat
accounts have bounded warmup; failed refreshes halt and revoke entry/model admission.
Authenticated timing and deployment remain pending; see `docs/PAPER_RUNTIME.md`.

Quote freshness conservatively uses the oldest bid, ask and selected trade clock.
A fresh component cannot hide stale executable prices; missing, naive or future
required timestamps fail collection closed. The governor retains its configured
age limit. This adapter change is locally verified, not deployed or authenticated
against the current account; see `docs/SLICE2_STATUS.md`.

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

## Isolated PAPER engine service

The opt-in [fixture PAPER service](docs/PAPER_RUNTIME.md) now connects independent
supervision, durable XNYS cycle claims, bounded judgment, deterministic admission and
fake dispatch. Default is audited stub HOLD. Restarts never replay an attempted slot;
shutdown revokes entry health and retains interrupted claims for signed review.
Resolution requires fresh reconciled truth, settled model evidence and terminal
orders, preserves the original cycle and retains the halt until separate RESUME. It requires
separate fixture stores and does not upgrade the deployed SHADOW worker or enable LIVE.

## Sequential virtual bankroll

The opt-in [synthetic portfolio experiment](docs/SYNTHETIC_EXPERIMENT.md) adds persistent
virtual cash/one position, later-quote fills, deterministic stops/session exits,
model-cost-adjusted returns, a paired SPY portfolio and observed drawdown. The sole
model sees that virtual account, so its decisions and costs form a separately named
population. This profile uses Robinhood READ only, including rejecting order review.
Initialize an immutable experiment ID, select it for the existing scheduled worker
and inspect its own report/private dashboard section. The default SHADOW profile
continues to use real-account context.

Linux server dependencies are pinned in `requirements-runtime.lock` and
`requirements-build.lock`; the worker image installs them without resolving newer
versions. For a matching Linux Python 3.12 development environment:

```bash
pip install --no-deps -r requirements-build.lock -r requirements-dev.lock
pip install --no-deps --no-build-isolation -e .
pytest -q
```

`scripts/lock-dependencies.py --check` verifies those pins against an installed,
tested Linux Python 3.12 environment. Refreshing pins requires a clean install and
full verification. OS/image artifacts and authenticated host operation remain
separate deployment checks.
