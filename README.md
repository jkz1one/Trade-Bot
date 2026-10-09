# Autonomous Compounding Trader

Small, auditable experiment for testing whether an autonomous reasoning trader can add value while deterministic software owns authority and risk.

## Current product direction

Read [SOURCE_OF_TRUTH.md](docs/SOURCE_OF_TRUTH.md) first for the authoritative goal,
rules, implementation milestones, acceptance gates and continuation discipline.
M1 option identity and deterministic admission is **fixture verified**. Read
[OPTIONS_ADMISSION.md](docs/OPTIONS_ADMISSION.md) for its delivered API and boundaries.
The M2 local options PAPER lifecycle is implemented. Read
[OPTIONS_EXECUTION.md](docs/OPTIONS_EXECUTION.md) for durable attempts, fills,
reconciliation and independent exits. The first **M3 Degen path is fixture verified**:
[completed setups, bounded exact contract selection and durable PAPER coordination](docs/DEGEN_PAPER.md).
The [headless options schema/sample capture](docs/OPTIONS_READ_CAPTURE.md) now has
fixture and native-process proof. The next gate is authenticated samples and exact
normalized collection, followed by optional model selection.
The [second operator report](docs/SHADOW2_EVIDENCE.md) records the October 8 frozen
synthetic results separately from new-engine acceptance.

The user clarified the goal on 2026-10-09: **stocks and options, with eventual
governed LIVE trading**, adapting SignalFlow's Degen/0DTE, Swing, Scope Wizard and UI.
The [source-backed pivot research](docs/OPTIONS_LIVE_PIVOT_RESEARCH.md) records reuse,
current broker capabilities, profitability evidence limits and the ordered delivery
queue. Exact option contracts and deterministic whole-contract admission now exist
as an offline PAPER module, with a separate durable local options fixture engine.
Existing deployed/runtime service support remains equities PAPER/SHADOW;
authenticated options integration remains open and LIVE stays disabled. The deployed $10
synthetic experiment remains frozen and separate.

Progress is reported as delivered capabilities, evidence and remaining acceptance
gates. Local tests do not close target-host/provider/recovery or LIVE gates.

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
Existing model events now retain measured count/generation and parent child-reaping
evidence. [Bounded model acceptance](docs/PAPER_MODEL_ACCEPTANCE.md) keeps provider
and billing verification separate from local process fixtures.
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
The independent `app.execution.alert_cli` now attaches without trader recovery and
retains its own lifetime lease, delivering halt alerts even after the trader stops.
New populations may explicitly enroll with `init --alert-origin --alert-token-file`;
its run/once/report commands retain existing receipt, retry and backlog gates.
This is verified with a local TLS sink; no external notifications or server changes were made.
Private [execution evidence checkpoints](docs/EXECUTION_CHECKPOINTS.md) now capture the
journal/authority pair consistently, support explicit verified-TLS archive retention/retrieval,
and require an independently retained hash before recovery staging. Recovery preserves
unresolved evidence and supplies no usable execution authority. Archive provisioning and
actual off-host/host-failure verification remain pending; deployed SHADOW backups are unchanged.
The standalone [native TLS archive receiver](docs/CHECKPOINT_ARCHIVE.md) provides
private bounded append-only storage, durable receipts and original-byte retrieval.
It is opt-in, independently provisioned and not installed on the trader host.
Its separate [archive host service](docs/CHECKPOINT_ARCHIVE_HOST.md) supplies reviewed
UID/storage/credential boundaries and bounded restart/shutdown without trader coupling.
Inspection/staging bind the exact extracted envelope bytes to the independent pin
before SQLite validation, rejecting in-place changes between scanning and extraction.
An opt-in private capture catalog now freezes source identity and capacity, preserves
incomplete attempts after crashes, and verifies local artifacts without restoring
authority. Its optional isolated nightly systemd timer has no network or credentials;
local captures do not provide off-host protection or automatic retention deletion.

A separate [isolated PAPER host layout](docs/PAPER_HOST.md) now provides independent
systemd units for runtime, operator control and alerts, with frozen paths and separate
credential namespaces. Runtime failure does not automatically restart trading or
terminate the companions. Native fixture lifecycle tests and parser validation are
separate from actual target-host installation and sandbox verification.
The installed read-only `app.execution.host_audit` collects reviewed unit/process/
credential-mount metadata for those three services. Matching snapshots retain
`host_acceptance=UNVERIFIED`; boot, lifecycle, provider and recovery gates remain open.
An opt-in [disposable sandbox harness](docs/PAPER_SANDBOX_ACCEPTANCE.md) now tests
the four reviewed role credential patterns on a systemd host with harmless files,
including peers created after startup. Local harness proof is separate from an
actual target-host run and full application acceptance.

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
The isolated collector rejects ambiguous symbol rows and malformed historical
indicator inputs before publication. Its full 20-symbol native-child fixtures
remain local contract proof; authenticated market timing is still a separate gate.
Successful isolated collection now returns measured read/reaping/publication time,
observed safe-tool counts and saved sample lineage. The
[full-universe procedure](docs/PAPER_MARKET_ACCEPTANCE.md) preserves explicit
one-shot ownership and keeps provider acceptance unverified until actual evidence.

The isolated PAPER operator API now has a native TLS entry point:
`python -m app.execution.control_cli`. It attaches to existing verified state
without running trader startup recovery, so starting the companion cannot convert
an active submission to UNKNOWN. New populations can explicitly enroll their signing
capability with `init --operator-key-file`; credentials and TLS must be provisioned
separately. This companion is not deployed to the current SHADOW server.

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
