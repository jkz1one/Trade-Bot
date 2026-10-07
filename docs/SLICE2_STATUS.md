# Slice 2 — Robinhood READ / SHADOW Status

## Current checkpoint — 2026-10-07 UTC

Branch: `slice2/robinhood-read-shadow`. PR #1 remains draft. `main` remains untouched.
The authenticated core path is verified: strict OpenAI output, real Robinhood reads,
model judgment, deterministic governor and persisted SHADOW audit. Scheduling is
installed and its closed-session behavior is verified on the Mac. A scheduled
authenticated regular-session cycle remains to be observed. Forward quote outcome
tracking and a persistent Linux SHADOW service are implemented and verified offline.
The service and private read-only observer are now running on the permanent
DigitalOcean server, with both containers healthy. The opt-in synthetic bankroll
profile is initialized but has no market-session cycles yet. Automatic container
restart and experiment configuration persistence passed the operator's host reboot
check. The operator confirmed the HTTPS dashboard login/page works. An integrity-checked
local backup succeeded and a nightly cron job is installed. Off-host protection,
mobile inspection, failure recovery and authenticated scheduled model-process
evidence remain deployment gates. LIVE is disabled.

Parallel engineering now includes a separate offline execution lifecycle rehearsal,
informed by SignalFlow's reservation and authoritative reconciliation contracts.
It has no broker write adapter or connection to the deployed experiment. The latest
full local suite passed **399 tests in 31.77 seconds**, including 40 execution
lifecycle tests, 26 position-supervision tests, 35 execution-limit/dispatch tests
and 22 isolated-process/durable-venue tests.
The deployed application release remains the one recorded below.

## Target-host evidence — 2026-10-06 UTC

Evidence below comes from the operator's pasted deployment output, not remote
execution by this workspace. Deployed application release:
`de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`.

- Fresh Ubuntu 24.04.5 amd64 server; application cloned from the Slice 2 branch.
  Docker build completed on `python:3.12.15-slim-bookworm`, including package
  installation and `pip check`.
- Resolved Python base digest:
  `sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`.
  Built application image index digest:
  `sha256:734ec19a3fba9238ed5faeb3b4e988dc2624abd066da95b10b26ffac292ade45`.
- OpenAI authentication accepted for `gpt-6-luna`; exact structured-output smoke
  returned `structured_output: true`, action HOLD, without touching Robinhood.
  This smoke is not the worker's isolated scheduled model process.
- Fresh Robinhood OAuth authorization and safe probe passed: reconciliation true,
  no positions, no working orders, all 20 candidates and mixed regime. No broker
  identifier or private account values are copied into this public document.
- Operator chose a fresh server database, preserving the Mac database separately.
  No bootstrap migration occurred. Only one worker may run across machines.
- `virtual-v1` initialized with $10 virtual capital, 5 bps per-side slippage,
  zero fixed fee, SPY benchmark and frozen `gpt-6-luna` prices/prompt/risk inputs.
  Prompt version: `v3-session-shadow:virtual-account-v1`.
- Preflight passed. Scheduled one-off and detached service returned MARKET_CLOSED
  with exit 0 and population SYNTHETIC_PAPER. At 20:22:06 UTC, heartbeat status was
  RUNNING; worker and observer were healthy. Observer port remained localhost-only.
- Schedule had no active claim or slots. Experiment revision was 0, with no cycles,
  fills or unaccounted model attempts. An empty cohort has no signal/performance
  evidence. No order placement, cancellation or LIVE path was enabled.
- Mac editable installation and full suite passed: **276 tests in 23.55 seconds**
  on Python 3.14.5, independently of the earlier locked Linux suite.
- Operator's post-reboot output at 20:56:46 UTC showed both containers healthy
  after automatic restart, RUNNING heartbeat and MARKET_CLOSED. The same release,
  experiment ID, frozen configuration and revision-0 empty cohort persisted.
- Host Caddy service reported active after restart. Operator selected DuckDNS plus
  Caddy HTTPS access instead of an SSH tunnel, retaining the observer's localhost
  bind and application authentication. See SHADOW_SERVER.md for the proxy boundary.
  At 20:58 UTC the operator confirmed dashboard login and the website page work.
  This is operator browser evidence; exact HTTP headers, mobile inspection, firewall
  configuration have not been supplied.
- At 21:00:16 UTC, the operator ran the server backup helper successfully:
  `/data/backups/robinhood-20261006T210016Z.db`, status OK, no network calls.
  The helper creates an integrity-checked SQLite snapshot. The same successful
  shell block installed `/etc/cron.d/trade-bot-backup` for 01:15 UTC daily and
  enabled cron, with output in `/var/log/trade-bot-backup.log` (mode 600).
  Installation is verified; a cron-triggered run and off-host copy are not yet observed.

Next: verify off-host backup protection and mobile
dashboard rendering; then observe a regular-session scheduled
model cycle, stored usage/decision/risk evidence and subsequent virtual transitions.
Target-host failure recovery remains unverified. Keep PR #1 draft and main untouched.

## Offline execution foundation — 2026-10-06 UTC

The operator requested execution engineering while SHADOW collects evidence, using
SignalFlow for inspiration and integration. Fresh GitHub refs were recovered before
editing: Trade-Bot `e1e846e3a5c0b28e2e3ccbf7666c472db3654128`, SignalFlow `main`
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Relevant broker capability, reservation,
reconciliation, ledger and partial-fill sources were read at that pinned snapshot.

Implemented `app.execution` with existing decision/packet/governor integration,
current journal account authority, pre-dispatch reapproval, durable intent/attempt
identity, one active reservation, cumulative partial fills, Decimal cash/fees,
original invalidation, daily entries/cooldown, atomic ledger/fill/order updates and
persistent halt/manual recovery. Missing orders never expire an attempted reservation
or authorize replay. Startup latches interrupted attempts as UNKNOWN. Only a built-in
local fixture venue can be attached; PAPER/LIVE-disabled configuration is required.
The journal is separate from all existing PAPER/SHADOW/synthetic tables and refuses
their databases. No Robinhood calls, model calls, broker writes or SignalFlow runtime
imports were added. The server runner, `virtual-v1`, prompt and risk policy are unchanged.

Verification: **40 execution tests passed**; the full suite passed **316 in 10.18s**
on Linux CPython 3.12.14. Coverage includes a real child-process exit after the
committed attempt, concurrent/repeated dispatch, lost acknowledgment, partial and
terminal outcomes, immutable/missing/stale evidence, budget/limit violations,
fees/cash, persistent limits/halt, transactional failure rollback and read-only,
network-free reporting. Changed-code Ruff checks/format checks and dependency
`pip check` passed. A built wheel was installed outside the repository and its
standalone fixture command also passed under optimized Python, saving two simulated
fills, terminal orders and a flat final account. These scripted results are execution
verification, not trading performance or real broker capability evidence.

See [EXECUTION_REHEARSAL.md](EXECUTION_REHEARSAL.md) for the reproducible command,
SignalFlow adaptation and remaining adapter/deadline/operator-control engineering.
Do not rebuild the deployed server for this offline foundation. Its first regular
market-session model cycle and the previously listed host verification gates remain
pending; LIVE remains disabled.

## Offline position-supervision follow-up — 2026-10-06 UTC

Fresh GitHub branch state matched `e8dfa23c8e54f0f5e26012c873e0fc53f965f64b`
before editing. SignalFlow's pinned stop-authority source was read alongside the
current engine and settled synthetic stop/session policy. The fixture engine now
persists original entry management, latches stop/session exits across HOLD/rebound/
restart, marks the owned position and prepares governor-approved protective exits
without a model. Explicit overnight permission preserves the existing policy; it
never disables stop invalidation. Missing/stale/regressing evidence halts execution.
Partial entry remainder must be definitively resolved before an exit; active sells
are reused and known canceled residual shares get a new intent. Entry preparation
and dispatch both enforce the final-15-minute session gate and current invalidation.

Verification: **26 supervision tests passed as part of 342 full-suite tests in
10.57s** on CPython 3.12.14. Tests include early closes, overnight permissions,
legacy lineage recovery, stale/missing/crossed/regressing quotes, stale account
evidence, failed calendar, concurrent preparation, partial fills, expired unattempted
exits, persistence rollback and unchanged original stop. Changed-code Ruff checks,
format checks, dependency integrity and whitespace checks passed. The new wheel
installed outside the repository and passed the optimized-Python fixture command,
with two simulated fills and a flat final account. This is offline fixture
evidence only. No broker adapter, deployment change or authenticated call was added.
Bounded executor deadlines, actual broker contract proof, deployed supervision,
bankroll/account gates and operator recovery/alerts remain future engineering.

## Offline account/dollar-envelope follow-up — 2026-10-06 UTC

Fresh canonical branch state matched `fdd6d5ad80eb9fbc04fd7eb79a5aed1a459367d7`
before editing. Each new offline journal now freezes its fixture account identity,
entry/position dollar ceilings and total/daily loss limits. Current journal/account
truth owns authority. Profits, model account proposals, runtime configuration changes
or manual resume cannot raise these limits. Daily realized net P&L includes all fill
fees, persists across restart and updates once with the atomic fill ledger. Loss
gates block new entries while protective closes remain available. Existing journals
without this envelope remain read-only reportable; execution requires a fresh journal
rather than silently adopting new authority.

PREPARED dispatch now requires a supplied fresh market packet and rechecks the saved
proposal against it. Current stop invalidation, tradability, volatility and account
limits can reject the old approval. Duplicate/crossed/nonfinite/stale/regressing
evidence never authorizes an attempt. Buy risk covers the original maximum executable
limit even if the current ask falls. Observed and governed packets and snapshot/risk
identity are saved; blocked admission/dispatch retains an audit reason. Attempted
orders still cannot replay and do not need a new packet simply to return their status.

Verification: **377 tests passed in 10.80s**, including 35 new limit/dispatch tests.
Changed-code Ruff checks/format checks, `pip check` and whitespace checks passed.
The wheel installed outside the repository and passed optimized-Python rehearsal
and independent account-pin/$2-ceiling/fresh-invalidation checks without network calls.
No server, existing experiment, model prompt, broker API or LIVE path was changed.

Estimated v1 execution-engine completeness: **about 60%**, a rough engineering
estimate of implemented components, not a LIVE-readiness or profitability score.
Remaining work includes bounded executor deadlines, actual broker identity/order/fill
contract proof, real account/capital enablement gates, operator recovery/alerts,
deployed supervision and integrated failure verification. The pending market-session
and host evidence above remains separate.

## Offline bounded executor follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `24069cd6d523a2dd7cbe3f743aa80cce8c888d63`
before editing. Isolated submission/read calls now use only the built-in durable
fake venue, separate from engine and server experiment databases. Acceptance and
complete order/fill/account truth persist independently across process deaths.
The journal binds a venue UUID/account and rejects replacement/transport bypass.
Write-ahead receipts precede launch; the frozen monotonic process deadline is also
capped by the intent's remaining admission lifetime and checked before acceptance.

Timeout, crash, lost/malformed/oversized acknowledgment and cancellation preserve
UNKNOWN/reservation/halt rather than retrying. Cleanup terminates, escalates if needed,
drains and reaps the child even under repeated cancellation or cancellation during
launch. The child receives no broker/model credentials or LIVE settings. Parent-death
checks stop diagnostic fake stalls while already accepted orders remain durable.
Failed complete-history reads halt without fabricating account or terminal evidence.

Verification: **399 tests passed in 31.77s** on Linux CPython 3.12.14, including
**22 new process/venue tests in 20.95s**. Tests use real children, native timeout/
SIGTERM-ignore/crash faults, cancellation races, an abrupt parent `os._exit(95)` and
reaped orphan child, bounded short admission lease, immutable venue binding, safe
database isolation and a saved end-to-end partial-entry/protective-exit scenario.
The Linux parent-death test owns/reaps its orphan using a temporary test-process
subreaper flag; this does not change a host service or the deployed server.
Ruff checks/format checks, dependency and whitespace checks passed. The wheel
installed outside the repo and its optimized-Python `deadline-run` saved a timeout,
two simulated fills, terminal orders and a flat final account; read-only reporting
passed. No broker/model calls, credential loading or server changes occurred.

Estimated v1 execution-engine completeness: **about 70%**, a rough component estimate.
Remaining: actual broker identity/order/fill/deadline contract verification, real-account
enablement/capital gates, authenticated operator recovery and alerts, deployed
supervision and integrated failure testing. This is not LIVE-readiness or profitability
evidence; the previously listed host and market-session gates still apply.

## Sequential synthetic portfolio and build hardening

The opt-in synthetic profile runs the sole trader against its own virtual cash and
position. It uses safe Robinhood reads, real broker/local reconciliation, the same
persistent scheduler/lifetime lock and the existing isolated model process. It
rejects broker review as well as writes. Real-account SHADOW journals, cost reports
and ownership remain separate; default PAPER/SHADOW behavior is preserved.

Approved proposals queue for a later fresh quote and deterministic revalidation.
The ledger persists virtual fills/cash, original stops, session exits, daily entries,
cooldown, fees, all reported model costs, paired SPY liquidation equity and observed
net drawdown. Configurations are immutable named cohorts, including model/prices,
market inputs, prompt and risk policy. A pre-model receipt exposes potentially
billed calls after crashes/rollback; missing usage blocks new entries and makes net
economics unavailable. Future/naive quote timestamps now fail closed in the governor.
See [SYNTHETIC_EXPERIMENT.md](SYNTHETIC_EXPERIMENT.md) for execution assumptions,
profile selection and reporting limitations.

The complete updated suite passed **276 tests in 8.45 seconds** in a fresh Linux
CPython 3.12.14 environment installed exclusively from the new exact dependency
locks. `pip check` and lock/environment comparison passed. Tests include sequential
fills/accounting, restart/isolation, bad quotes, gap/session exits, cost uncertainty,
atomic rollback, cancellation, durable halt, backup restoration, CLI selection,
read-only gateway and authenticated read-only observer integration. These are
synthetic fixtures; no new authenticated broker/model or profitability evidence is
claimed. An actual installed-package Uvicorn run also passed authenticated synthetic
HTML/JSON, denied anonymous reads, unchanged DB and completed lifespan shutdown
with three simulated cycles/two fills. The earlier 229-test observer checkpoint
remains recorded below.

Server runtime and build dependency closures are pinned and the Docker build disables
both dependency resolution and build isolation. The official Python base tag is
explicit; target-host build and basic mounted credential/database access now pass
as recorded above. Normal host restart now passes. Authenticated regular-session
operation, failure recovery and desktop/mobile visual review remain host gates.
PR #1 stays draft; no merge has occurred.

## Private SHADOW observer

A separate `app.web.shadow:create_shadow_app` now reads stored worker/slot/cycle,
account, risk/reconciliation, review completion, linked model usage and forward
quote outcomes. The PAPER/demo app and its controls remain separate. Observer
startup requires SHADOW mode, LIVE disabled and an independent private password.
No broker/model clients are initialized or called; there are no mutation routes.

The database is opened read-only without bootstrap/repair. Reports use a single
committed snapshot, bounded pagination and source-linked outcome cohorts. Latest
account values carry their saved timestamp/age; heartbeat readiness is a separate
signal. Model HOLD, deterministic HOLD, unattributed legacy HOLD and failure remain
distinct. Missing usage is unknown; quote marks are not portfolio profit/alpha.
Raw broker reviews/identifiers, working orders and claim-owner tokens are omitted.

Compose mounts only read-only data and the independent observer password, without
broker OAuth or API credentials, and publishes only `127.0.0.1:8787`. Access uses an
SSH tunnel and password authentication. `prepare` generates the password privately
without overwriting existing files; `observer` can start inspection without starting
the worker. See [SHADOW_SERVER.md](SHADOW_SERVER.md) for consolidated operations.

The full updated suite passed **229 tests** in 7.60 seconds. Observer validation
includes authentication and password failure/rotation, denied
SQLite writes, absent mutation routes, empty/corrupt history, escaping and secret
projection, heartbeat freshness, paged cohort linkage, one committed WAL snapshot,
and progress with default-journal writes plus concurrent readers. Wheel packaging,
Compose schema/private-boundary checks and shell syntax are also verified. Actual
Uvicorn startup/private HTTP reads/graceful shutdown passed with synthetic history
and no remote calls. HTML responses render in tests; desktop/mobile visual review remains a host gate because
the browser download failed in this workspace. No deployment or live calls occurred.

## Model subprocess hardening

The SignalFlow review exposed the earlier `asyncio.to_thread` cancellation limitation.
OpenAI SHADOW decisions now execute in an isolated, tool-less child process. The child
receives only the MarketPacket, model name and request timeout through stdin. It owns
no broker connection or database handle. Success returns validated TradeDecision and
exact usage; errors return a sanitized class and fail-closed HOLD. Child stdout/stderr
diagnostics cannot enter the protocol or application logs.

Defaults: 60-second SDK request timeout, zero SDK retries, 120-second entire process
deadline (startup/import included). Model timeout or outer cycle cancellation terminates
the process group, escalates to SIGKILL after two seconds if needed and reaps the child.
Cancellation during startup or cleanup cannot leave an orphan or turn cancellation
into a successful proposal. The original strict schema, runtime limits, tools=[] and
one-turn policy remain unchanged. SDK tracing is disabled only in the subprocess;
application audit/usage persistence remains authoritative.

A model deadline persists HOLD/ModelProcessTimeout, no review and exit 8, then latches
HALTED. An outer cycle deadline leaves its active claim interrupted and blocks replay.
Missing usage remains unknown; local termination cannot guarantee cancellation of
remote computation or billing. No model calls are retried or reconstructed by recovery.

Updated local suite: **198 tests passed**, including 17 new process tests. They use real
blocking synchronous children that ignore SIGTERM, prove forced kill/reaping, cover
startup/repeated/success-cleanup cancellation, malformed/oversized/crashed output, exact
packet/decision/usage transport, no retries/tools, durable service halt and claim state,
no review/replay after timeout, and shutdown draining a blocked model call.
Compilation, fatal-error lint and whitespace checks passed. No live API/broker calls
were made. Container build, authenticated subprocess output, host memory/latency and
first scheduled regular-session cycle remain target-host gates.

## SignalFlow architectural review

[SIGNALFLOW_REUSE_ASSESSMENT.md](SIGNALFLOW_REUSE_ASSESSMENT.md) records a targeted,
source-linked comparison against SignalFlow `f9eaf2c1b5d13dca287ee7138126883065b00395`
and Trade-Bot `87319600d44524840010ccb3d4b3c084c0b00e74`. SignalFlow was read only;
no runtime features or integration were added by this review. Twelve isolated pure
SignalFlow rejection/replay/outcome tests passed; Trade-Bot's 181 tests passed again.

Reusable patterns are stored-evidence dashboard/reporting, complete decision cohorts,
point-in-time replay and separately measured synthetic execution. Options/flow feeds,
multi-bot coordination and SignalFlow's narration-only AI schema are not a direct fit.
The existing web app remains PAPER/demo only; the separate SHADOW observer is now
implemented above.

An important limitation in the reviewed snapshot was reproduced locally: the cycle timeout cancels an
awaiting task but cannot terminate the synchronous model thread used by `to_thread`.
Durable halt/claim blocking prevented another cycle; subprocess hardening above now
fixes local cleanup/shutdown for OpenAI SHADOW. The observer is implemented; the next
experiment slice is the sequential experiment ledger. No live model/broker
calls or server changes occurred during the review.

## Persistent server follow-up

The foreground Mac runner is a local verification tool. Continuous operation now
has a separate `compose.shadow.yml` worker and `scripts/shadow-server.sh` helper,
with a consolidated migration/operations guide in [SHADOW_SERVER.md](SHADOW_SERVER.md).
SignalFlow's separate Docker worker, persistent state, restart and container-hardening
patterns informed the deployment. SignalFlow itself is not changed or reused.

The worker uses a lifetime process lock, local heartbeat, graceful signal handling,
a bounded cycle timeout and durable HALTED state. Model, review, authentication,
calendar and interrupted-claim failures stop further attempts until explicit local
operator recovery. Resuming never replays an attempted slot. Docker restart does not
clear a halt. Scheduled idempotency and crash blocking remain in the existing SQLite
claim ledger. The service always disables interactive OAuth; an explicit stopped-worker
authorization command remains available for operators.

Credentials are private files; the OpenAI key is mounted as a secret and OAuth state
is writable for refresh. SQLite, claims, audit history and service state persist outside
the code checkout. Export/backup commands use consistent SQLite snapshots, check
integrity and print no secrets. Initial server import refuses to overwrite existing
history. Only SHADOW is configured. The observer follow-up now publishes a
localhost-only port through an SSH tunnel; no public web listener is configured.

Verification: **181 tests passed** locally. The 14 new service/backup tests cover
locks, in-flight heartbeats/shutdown, timeouts, sanitized persistent failures, local
credential checks, explicit claim abandonment/resume and private migration bundles.
The actual CLI booted healthy with MARKET_CLOSED and synthetic credentials, then
handled SIGTERM with exit 0 and STOPPED state. Compose configuration validation,
shell syntax, compilation, fatal-error lint and whitespace checks passed.

This workspace has no Docker daemon, real broker OAuth state, API key or confirmed
droplet connection. The image has not been built here and no server has been deployed.
Target-host image build, authenticated read probe, restart verification and the first
regular-session model cycle remain deployment gates. No new live-account/model evidence
is claimed by these offline checks.

## Installation follow-up

The user's next Mac batch pulled `0a6167681ea1b5e1694b8b6f5d334325ec505a6d`
but stopped at `pip install -e '.[dev]'`: setuptools discovered both `app` and
the runtime `var` directory as top-level packages. Tests and both scheduler commands
in that chained batch did not run.

Package discovery now explicitly includes only `app` and `app.*`, with implicit
namespaces disabled. The web HTML template is explicitly included as package data;
generated build directories are ignored. The original failure was reproduced locally
with an empty `var` directory. With that directory still present, the full editable
installation and wheel build succeeded. Wheel contents were checked for application
code and the template, with no runtime `var` files included. The installed CLI's
Saturday tick returned MARKET_CLOSED, exit 0.

The subsequent Mac batch pulled `32f0d23c6b7eeb9bedbd958e081c583353344d51`:
installation succeeded, **136 tests passed** in 33.95 seconds, the scheduled tick
returned MARKET_CLOSED with exit 0, and status showed CLOSED, no active slot, no
attempted slots and `network_calls: false`. The whole chained batch completed.
Installation and the closed-session gate are now verified on Python 3.14/macOS.

## Authenticated evidence from the user's Mac

The earlier authenticated model batch pulled `7abcf284ee84a787020ba5913c5cc8d504ee930c` and passed
**105 tests** in 3.66 seconds. Every subsequent command completed:

- `openai-structured-check`: OK, `gpt-6-luna`, HOLD, structured output accepted;
  Robinhood untouched.
- `shadow-cycle --agent openai`: reconciled account, no position or working orders,
  20 candidates and mixed regime. Model returned HOLD; governor rejected entry with
  `NO_ENTRY_REQUEST`; execution SKIPPED. No broker review or order submission.
- `shadow-audit`: cycle 6, packet timestamp `2026-10-03T17:52:06.028989`, prompt
  `v2-live-shadow`, model `gpt-6-luna`, latency 12,730 ms and explicitly linked evidence.
  Usage: 2,999 input / 322 output tokens; estimated cost **$0.00046090**.
  SPY observations: 769.86 to 769.86.
- `shadow-history --limit 100`: six HOLDs, including four historical agent failures,
  one earlier stub HOLD and this real model HOLD. Five legacy cycles were unlinked;
  only cycle 6 had explicitly linked evidence and usage. Zero broker reviews.

The model cited stale quotes and the Saturday session as reasons to stay in cash.
This verifies plumbing and a valid HOLD, not useful trading signal or profitability.
The governor-approved `review_equity_order` path has full simulated-cycle tests;
an authenticated approved review has not yet been observed.

Earlier batches passed 58, 95 and 105 tests but stopped respectively at an unsupported
Decimal schema regex and exhausted API credits. Those failures did not reach the
subsequent Robinhood cycle. The successful batch above supersedes the credit blocker.
Price wire schemas now accept number/string without the unsupported regex; Decimal
precision, positivity, finiteness and application limits still validate after parsing.

## Market-session runner

- `shadow-run --agent openai` polls locally every 30 seconds and starts at most one
  cycle per 15-minute slot, anchored to the XNYS regular-session open.
- The exchange calendar handles weekends, holidays, daylight saving and early closes.
  Closed sessions skip before initializing broker or model clients. Calendar errors
  and dates outside calendar coverage fail closed, with exit 12.
- Restart runs only the current slot; it never catches up missed slots.
- An additive SQLite table claims each slot before external calls. A unique active
  lock allows only one scheduled cycle in flight across workers sharing the database.
- Cycle evidence and slot completion commit together. Previously attempted slots
  never automatically retry, including model or review failures.
- A crash or interruption while a claim is active leaves it CLAIMED and blocks future
  scheduled cycles (exit 10). Inspect `shadow-schedule-status` and the audit before
  resolving an interrupted claim. No expiration or automatic replay is implemented.
- Session boundaries and scheduled time enter the packet. The session is checked
  again after reads and before review. If it has closed, model judgment or review is
  skipped as appropriate and the reason persists in execution evidence.
- Existing daily entry limits now count completed hypothetical entry reviews from
  persisted history, using the New York calendar day. Unreviewed proposals do not
  count. The existing exit cooldown uses the latest completed hypothetical close
  review and survives restarts. These are review controls, not simulated fills.
- Prompt version is now `v3-session-shadow`. The last authenticated model run used
  `v2-live-shadow`; the updated prompt has not yet been exercised against OpenAI.

The process runs in the foreground and must remain running on an awake machine.
It is not automatically installed as a service. Separate database files do not share
claims; use the same `robinhood.db` for this one-trader experiment.

## Persistent audit and history

New cycles save decision, exact usage, account/benchmark snapshots and reconciliation
in one transaction. Explicit evidence links prevent borrowing usage from an earlier
cycle. Legacy rows remain `LEGACY_UNLINKED`; missing usage is unknown.

`shadow-history` separates explicitly linked model HOLDs, deterministic stub/session
HOLDs, unattributed HOLDs and agent failures. For compatibility, `genuine_hold_count`
still means all non-failure HOLDs; it is not a model-only count. Session context and
blocked execution counts are included. SPY output is a raw quote-price return with
sample endpoints. Strategy/economic P&L remains null: there is no counterfactual fill
ledger yet, and SHADOW submits no trades.

## Forward quote outcomes

New cycles also atomically register two outcome rows per source cycle, for fixed
15- and 60-minute horizons anchored to its scheduled session slot. Policy:
`v1-forward-quote-marks`. This uses already-read packet quotes and adds no broker
or model calls. These rows are separate from orders, fills and owned positions.

- Eligible sources have clean reconciliation, explicit linked model usage and an
  available decision inside a scheduled regular session. Source quotes must be
  fresh, uncrossed and not future-dated. Stub/guard/failure/unscheduled sources and
  legacy cycles cannot silently become model performance evidence.
- Reviewed entries require deterministic approval and a completed broker review.
  The reference is the decision-packet ask and approved notional. It is a quote
  reference, not a claim that an execution-time fill was available at that price.
- Cash HOLD is first-class: the fixed reference notional is the source account's
  equity, price change is zero and the linked source model cost is deducted.
  HOLD with an existing position and CLOSE/REDUCE are explicitly excluded in this
  first measurement policy.
- SPY uses its packet ask and subsequent bid on the same fixed reference notional.
  A qualifying later cycle provides fresh quotes at/after the target, after source
  decision completion, in the same regular session. The first accepted observation
  is immutable and links to the exact later cycle and quote timestamps.
- The observation window ends five minutes after the target or at regular close,
  whichever comes first. Missing/stale/future/pre-target pairs remain PENDING;
  a later cycle marks overdue rows EXPIRED. Targets outside the regular session or
  before decision completion are EXCLUDED. No next-session backfill occurs.
- Source model cost is frozen with the baseline and deducted per horizon sample.
  The database's reported total cost is counted once from usage rows. Reports keep
  15/60-minute cohorts and reviewed entries/cash HOLDs separate. Overlapping marks
  are not independent samples and are never summed into a bankroll or compounding
  return. Fees, slippage and dividends are not modeled.
- Existing databases receive an additive `shadow_forward_outcomes` table. Legacy
  cycles are not reconstructed/backfilled. Reports make no network calls and do
  not expire rows on read; pending status is as of the last collected packet.

Inspect local evidence:

```bash
python -m app.robinhood.cli shadow-outcomes --limit 100
```

The result includes baseline/measurement cycle IDs, status/reasons, quote references,
fixed notional, linked model cost, forward quote changes and SPY excess after source
model cost. It reports arithmetic cohort means only when observations exist.
An existing database with only legacy/manual cycles initially reports EMPTY. Portfolio
strategy/economic P&L remains null because this is proposal evidence, not a fill ledger.

Audit, history and schedule status make no OpenAI or Robinhood calls:

```bash
python -m app.robinhood.cli shadow-audit
python -m app.robinhood.cli shadow-history --limit 100
python -m app.robinhood.cli shadow-schedule-status
python -m app.robinhood.cli shadow-outcomes --limit 100
```

## Authority and configuration

- Default remains PAPER, with a separate `trader.db`. Robinhood defaults to `robinhood.db`.
- Trader Agent has `tools=[]`, strict `TradeDecision` and `max_turns=1`.
- Deterministic software approves/rejects/sizes, capped by unleveraged buying power.
- SHADOW may use only `review_equity_order` after governor approval for hypothetical
  trading. It never submits or cancels an order. LIVE remains disabled.
- Broker/local mismatches fail closed, including unsupported assets, multiple positions,
  unowned/missing positions, quantity/symbol mismatch, non-long positions and working orders.
- Robinhood discovery proved 76 tools and schemas without required-tool/schema gaps.
  Accounts, portfolio, positions, working orders, quotes, historical OHLCV, indicators,
  tradability and regime construction work. Historical requests deliberately fetch
  one symbol per call to avoid the MCP SDK's 1 MiB SSE-event ceiling.
- Universe: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLI, XLV, XLY, AAPL, MSFT, NVDA,
  AMZN, META, GOOGL, TSLA, AVGO, JPM, COST.
- Model: `gpt-6-luna`; configured standard prices: $0.10 / 1M input tokens and
  $0.50 / 1M output tokens. Costs are estimates using these configured rates.
- Agent errors persist fail-closed HOLD and exit 8; review errors persist decision,
  risk and usage with sanitized error class and exit 9. No failure submits an order.

## Verification and next use

The Mac calendar installation is already verified. Validate this follow-up without
repeating dependency installation or the structured-output check:

```bash
git pull --ff-only && \
pytest -q && \
python -m app.robinhood.cli shadow-outcomes --limit 100
```

To collect regular-session history and future quote outcomes continuously, use the
Linux service in [SHADOW_SERVER.md](SHADOW_SERVER.md). The foreground runner is also
available for local checks. Outside a regular session either runner waits without
broker/model calls; during a session it attempts the current slot and persists its
result. Run only one worker against the account across machines:

```bash
python -m app.robinhood.cli shadow-run --agent openai
```

Forward-outcome checkpoint suite: **167 passed**. Compilation, fatal-error lint and whitespace
checks passed. The real CLI's Saturday tick returned MARKET_CLOSED with exit 0;
schedule status reported no active claim or slots and no network calls.

Local verification covers calendar boundaries, concurrent SQLite claims, restarts,
crash blocking, rollback, sanitized failures, persistent New York daily limits,
cooldown expiry, session-ending reads/model calls and review-only execution.
Outcome tests cover quote/cost arithmetic, cash HOLD, exclusion reasons, immutable
paired observations, concurrent SQLite connections, expiry/early close, atomic
rollback, restart persistence, existing database upgrades and local reporting.
No authenticated OpenAI or Robinhood calls were made in this execution workspace;
it has neither API credentials nor Robinhood OAuth state.

The separate sequential synthetic portfolio/fill ledger described above is now
implemented and selected on the server. Next experiment work is to collect enough
regular-session decisions and virtual transitions to evaluate signal. Real-account
SHADOW forward marks remain separate from the synthetic portfolio economics.
No profitability claim or LIVE enablement follows from this checkpoint.
