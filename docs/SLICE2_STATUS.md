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
full local suite passed **809 tests in 123.91 seconds with warnings treated as errors**,
including the previous 757 cases and 52 new signed cycle-recovery cases. Interrupted
PAPER claims now support reviewed no-replay resolution through the existing control
transport, preserving the original cycle and its halt until a separate RESUME.
Changed-code checks and installed native HTTPS/runtime continuation proof passed;
see the latest follow-up below.
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

## Offline authenticated recovery follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `9b95db444bfa8bd01b481118be4c57469281ef03`
before editing. The isolated execution journal now supports explicit operator
capability enrollment, signed command envelopes and durable replay receipts.
HMAC commands bind an immutable journal UUID, actor label, reason, action/target,
reviewed audit revision and a maximum-five-minute lifetime. The key and signature
are not persisted in audit records or supplied to the trader/model processes.
Shared-key capability authentication is not per-person login; trusted local
Python/filesystem owners retain authority. No HTTP mutation route was added.

HALT reduces authority even if review/config changed. RESUME, local PREPARED
abandonment and alert acknowledgment require the exact current reviewed revision.
Mutation, event and receipt commit together. Repeats return the original receipt
without reapplying, including after expiry; content reuse under the same ID fails.
Expired/future and risk-rejected requests have durable rejected receipts.
Recovery additionally requires fresh owned-position supervision/quotes, retains
complete account/order reconciliation and cannot release an uncertain attempt or
waive original stops, frozen limits or terminal-evidence requirements.

Critical events and changed blocked/exit-required supervision create persistent
alert rows atomically with their source events. Pagination retains older pending
alerts beyond the report's 100-row page; acknowledgment records operator/time/ID
but never clears a halt, delivers an external message or releases reservations.
Repeated identical supervision is deduplicated. Compatible current journals gain
only additive tables on writable open; read-only prior reports do not migrate or
enroll. Historical events are not backfilled as new alerts.

Verification: **434 tests passed in 32.58s**, including **35 new operator/alert
tests in 0.85s**, on Linux CPython 3.12.14. Coverage includes invalid/tampered/cross-
journal signatures, immutable enrollment, secret/MAC audit exclusion, expiry,
replay/conflicting IDs, concurrent duplicate/stale requests, late fills invalidating
review, receipt/alert storage rollback, uncertain-order recovery restrictions,
fresh position supervision, stop persistence, alert pagination/deduplication,
read-only legacy reports and an exclusive-file offline CLI proof.
Ruff check/format, dependency and whitespace checks passed. The wheel installed
outside the repo and its optimized-Python operator scenario persisted one canceled
fake order, three command receipts, one acknowledged alert and no retry. Read-only
reporting left the private database unchanged. No broker/model calls, credential
loading, server changes or external notification occurred.

Estimated v1 execution-engine completeness: **about 72%**, a rough component estimate.
Remaining: actual broker identity/order/fill/deadline contract proof, real-account
enablement/capital gates, deployed independent supervision, integrated model costs,
secure operator transport/key lifecycle/restore handling, external alert delivery
and host failure testing. LIVE readiness and profitability remain unverified.
The deployed release and earlier host/market-session gates remain unchanged.

## Offline credential lifecycle and restore follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `e029afa3a8b9b77dafccfd1b8be0350c3f04addf`
before editing. Signed ROTATE_KEY/REVOKE_KEY and credential generations now retire
old capabilities and latch dispatch halts. Retired keys cannot be reused, including
through trusted local recovery. Revoked-capability recovery requires a new key and
reason, advances generation and preserves the halt, active reservation and ledger.
Recovery still needs definitive venue evidence and ordinary signed RESUME.
Retired controls cannot read a review or replay old command receipts. Shared key
capability authentication remains local; no per-person login or HTTP control exists.

Explicit restore-fence enrollment creates a private separate authority file. Fenced
writes verify journal UUID, commit generation and complete logical-state digest
under attached-database locks before mutation, then advance both checkpoints in
one transaction. Files use DELETE journal mode and writer connections synchronous
FULL; unsupported modes fail without persistent-mode changes. Missing/replaced
authority, journal-only rollback, a restore before fence enrollment, or same-audit-
revision state changes block writes and cannot silently rebind authority. Reports
remain read-only and show VERIFIED, BLOCKED or UNFENCED. The fence is opt-in for
offline rehearsals; nothing is enrolled on the server.

Verification: **460 tests passed in 32.76s**, with **26 new credential/restore tests
in 1.48s**, on Linux CPython 3.12.14. Tests cover retirement/re-enrollment, stale
review, competing rotations, preservation of uncertainty, retired-generation
re-signing, receipt/authority rollback, private/idempotent provisioning, restores
before/after enrollment, accepted-order retry prevention, missing/foreign files,
unsupported WAL, unchanged read-only reports, concurrent writers, failed fence
initialization and an actual child `os._exit(97)` while both files are uncommitted.
Both files recovered consistently after reopening. This is not a host power-loss
or mid-COMMIT crash test. A saved exclusive-file `recovery-run` proves rotation,
revocation, unknown-order blocking, definitive fake cancellation and rollback
rejection, then restores the exact known-current fixture bytes without changing
authority. No arbitrary database restore/reset utility was introduced.

Ruff check/format, pip check and whitespace checks passed. The built wheel installed
outside the repo; its optimized-Python recovery scenario verified credential
generation 4, two retired keys, four receipts, one canceled fake order, blocked old
journal retry and a VERIFIED current pair. Read-only reports left both private
files unchanged. Wheel SHA-256:
`b343bd90c56ae2aad357051cc5ff2aaca5c761c78affa182882e370f7671bad9`.
No broker/model calls, external notifications, deployment changes or LIVE path.

Estimated v1 execution-engine completeness: **about 74%**, a rough component estimate.
Remaining: actual broker identity/order/fill/deadline contract proof, real-account
enablement/capital gates, deployed independent supervision, model-cost integration,
secure operator transport, external alert delivery, off-host/multi-host checkpoint
protection, verified restoration and host failure testing. Rolling back both local
files together or duplicating the valid pair across machines is not detected by
this local safeguard; full-history digest growth is also unmeasured. LIVE readiness
and profitability remain unverified. Deployed release/experiment remain unchanged.

## Offline model-cost and economics follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `f3ec2445a94d2bfa47abb784604c13b001dd6871`
before editing. Opt-in engine cost enrollment freezes model, configured standard
rates, total/daily budgets and a per-call reservation. A durable receipt commits
before a future model invocation; exact source/packet replay never calls again.
Unknown usage blocks additional calls/entries and suppresses net economics.
Current account/session/quote evidence and no active order are required before
granting a new invocation receipt. This module never invokes an API.

Trusted local usage evidence must carry pinned model, positive input tokens,
nonnegative output tokens and unique request identity. Decimal charges, immutable
decision fingerprint and audit commit atomically. Duplicate settlement is a no-op;
conflicts cannot double-charge or erase uncertainty. All charges above the assumed
per-call bound remain counted, produce an alert and block further calls/entries.
Every new attempt reserves room in total and New York daily budgets. Daily charges
belong to the attempt date, including late settlement; total costs persist.

BUY admission requires matching settled decision and original packet evidence.
Fresh dispatch retains decision/cost authority and reruns cost-aware entry gates.
Total/daily loss floors include known reasoning charges alongside trading equity
or fee-adjusted realized P&L. Brokerage/simulated cash and buying power are not
debited by external model costs. HOLD costs count; deterministic protective CLOSE
still works with uncosted reasoning, subject to normal reconciliation/ownership/
quote/halt rules. Reports expose known/unknown costs and net equity/return only
with complete usage and fresh account/position marks.

Verification: **490 tests passed in 33.46s with warnings treated as errors**,
including **30 new model-cost/economics tests**, on Linux CPython 3.12.14. Coverage
includes receipt/settlement replay, concurrent requests, source/decision/packet
binding, missing/invalid/foreign usage, provider ID conflicts, frozen/runtime-policy
changes, reserved/exhausted budgets, full over-bound charges, daily attribution,
economic loss gates, preserved broker cash, protective exit under unknown costs,
stale/mismatched net marks, rollback/restore fencing and actual child `os._exit(98)`
after receipt commit. Restart retains the potentially charged call and cannot replay.

Ruff check/format, pip check and whitespace checks passed. The installed wheel ran
outside the repo under optimized Python with warnings as errors: two fake fills,
protective exit while a HOLD cost was unknown, $0.00030 final scripted model cost,
exact cash-minus-cost net equity, VERIFIED restore pair and unchanged read-only
files. Wheel SHA-256:
`0c2063a16a01e70a59aab1de8117f2fbf393dd443e9277dd804754cbba2f0d09`.
No broker/model calls, actual billing proof, server changes or LIVE capability.
The saved `economics-run` exclusively creates a new fixture file.

Estimated v1 execution-engine completeness: **about 76%**, a rough component estimate.
Remaining: actual broker/order/fill/deadline verification, real-account/capital
enablement, deployed independent supervision and operator transport, external
alerts, off-host/multi-host restore protection and host failure testing. Actual API
request/token ceilings, invoice/discount treatment and verified noncharge recovery
must still support this cost ledger before integration; its rates are configured
assumptions, not current-price verification. Isolated economics exclude SPY pairing,
corporate actions, taxes, hosting/setup charges and real invoice adjustments. The
server's paired synthetic SPY experiment remains separate and unchanged. LIVE
readiness and profitability remain unverified.

## Bounded model judgment follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `3f377a146c1e009dfecc72cab8e329473002f09f`
before editing. The optional fixture-engine `JudgmentCoordinator` now connects
frozen cost authority to a private OpenAI Responses child. Existing Trader
instructions, strict `AgentOutputSchema(TradeDecision)` and runtime validation
remain the judgment contract; the deployed Agents SDK/SHADOW path is unchanged.

Enrollment before model receipts freezes prompt/schema/cost hashes and request
bounds. Defaults: 16,000 input tokens, 1,024 output tokens, 30-second process and
20-second request deadlines. Their maximum configured token cost must fit the
existing per-call reservation. Reconciled journal cash/position replaces proposed
account values in the model packet. A revision check atomically binds that review
to the durable pre-model receipt. Receipt commit/storage failure and replay cannot
launch another child or silently charge zero.

The fixed child gets only an explicit model key plus basic locale/path environment,
with a pinned OpenAI API origin, no SDK retries, suppressed logs and no tracing.
It counts the exact instruction/input/tools/schema payload, rejects bad/excessive
counts and generates at most once with bounded output, empty tools, no tool choice,
disabled truncation, no streaming/background and `store=false`. A watchdog exits on
parent death/deadline; parent cleanup kills/drains/reaps even after repeated cancel.

Provider response identity/usage is captured before structured decision parsing.
Incomplete/refused/invalid output becomes HOLD with full valid reported usage cost;
failed requests or absent usage stay unknown. Exact model, usage bounds and counted
versus returned input are checked. Violations preserve reported evidence, count all
valid pinned-rate charges and persist a new-call/entry block. Foreign model usage
cannot inherit pinned pricing. Settlement, decision audit and violation state commit
together; enrolled BUY authority requires the matching bounded judgment record.
No model judgment prepares or dispatches an order. Protective closes retain their
existing deterministic path under cost/evidence entry gates.

Verification: **526 tests passed in 37.82s with warnings treated as errors**, with
**36 new bounded-judgment tests**. Native pinned SDK calls use local HTTP mock
transport to prove count/generation payload equality, empty tools/strict schema,
output cap, missing usage, invalid/incomplete/refused/unexpected output and no
retry after quota failure. Tests cover source restart, frozen/runtime policy,
review races, cash reconstruction, receipt/audit rollback, direct-settlement entry
rejection, full usage under violations, private child environment, real deadlines,
crash/oversized protocol, repeated cancellation and a real parent `os._exit(94)`.
The actual worker watchdog exits its orphan with code 99; the cost receipt remains
unknown and cannot replay after restart, with the authority pair still VERIFIED.

Ruff check/format, pip check and whitespace checks passed. The installed wheel ran
outside the repo with optimized Python and warnings as errors. Both real subprocesses
loaded installed package code and the pinned SDK used mock transport, producing a
valid entry and a billed incomplete HOLD, two fake fills, flat final state, exact
$0.00030 cost/net conservation, private files, a VERIFIED authority pair and
unchanged read-only report bytes. The first proof's alert-count assertion was adjusted
to account for the existing protective-exit alert alongside the model HOLD alert;
the corrected proof completed. Wheel SHA-256:
`013026d933f9f3dc5886e83fdbb5cd547d09837a5842592e40813a5c3d4f76c8`.
No authenticated API or broker call, server update or LIVE capability was added.

Estimated v1 execution-engine completeness: **about 78%**, a rough component estimate.
Remaining: authenticated token-count/generation/model-identity verification before
adopting this optional interface; invoice/discount treatment and verified noncharge
recovery; actual broker/order/fill/deadline contracts and account/capital enablement;
deployed independent supervision, secure operator transport, external alerts and
off-host/multi-host restore protection with host-failure proof. First scheduled
authenticated market-session evidence from the deployed cohort remains unobserved.
The existing server and paired synthetic SPY experiment remain unchanged. This
mocked execution proof establishes neither live readiness nor profitable signal.

## Independent fixture supervisor follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `dcf1b5fd2771bb5b81c56aa6eae06c9fe1d1a9ef`
before this slice; PR #1 remains draft and main is unchanged. A new opt-in
`ExecutionSupervisor` runs account reconciliation and stop/session supervision
without awaiting model reasoning. It accepts only the built-in execution engine,
durable fake venue and private manually published `DurableQuoteFeed`.

Enrollment before orders freezes venue/feed/account identity, paths, universe and
poll/tick/freshness limits. Defaults are 5/10/20 seconds respectively; poll plus
whole-tick deadline must fit the lease, which cannot exceed quote freshness. A
single-host lifetime file lock prevents duplicate owner claims. Completed OK ticks
alone renew entry health. After enrollment, BUY preparation/dispatch and new model
receipts require that fresh RUNNING result. STOPPING revokes health before child
cleanup completes; failed/interrupted/stopped-with-risk runners retain a dispatch halt.
Interrupted recovery needs explicit reasoned review; reads never auto-resume.

The loop reads complete fixture history in the existing bounded private child,
validates quote feed identity/sequence/freshness, supervises owned risk, and may
prepare/reuse only a governed protective SELL. It never creates a BUY or cancellation.
Original invalidation, session policy, one active reservation and partial-fill
ownership stay in the existing engine. Read fencing captures account/order/fill
state before awaiting and atomically discards superseded results before applying
them, without renewing health. Unchanged-epoch mismatches still halt. Quote/account
freshness is checked again at completion. Blocked result alerts deduplicate.

Verification: **557 tests passed in 51.80s with warnings treated as errors**, including
**31 new supervisor tests**. They cover protective fake SELL while a real model child
is blocked with an unknown receipt; idempotent polls; stop/session exits; unresolved
partial BUY and definitively canceled partial SELL; stale/future/missing/oversized/
foreign/regressed quote evidence; freshness gates before preparation, dispatch and
model receipt; shutdown admission while cleanup is pending; immutable/runtime
policy; duplicate owner; read/tick deadlines; health-commit rollback; repeated
cancellation; and older read completion after new intent/fill evidence. A real
parent `os._exit(93)` leaves an interrupted owner and its actual read child exits
through the parent-death watchdog. Restart cannot claim healthy entry authority
until fresh reconciliation and explicit review; the authority pair stays VERIFIED.

Changed-code Ruff checks/format, pip check and whitespace checks passed. The wheel
installed outside the checkout passed an optimized-Python, warnings-as-errors proof.
The installed supervisor completed a governed fake SELL and reconciled flat with
two fake fills while the installed model child was blocked in mocked SDK generation.
The cancelled model attempt stayed unknown, prior known cost remained $0.00015 and
net economics stayed unavailable. Children were reaped; all journal/authority/venue/
feed files remained private, the authority pair was VERIFIED, and read-only reporting
did not change bytes. Wheel SHA-256:
`c7bb42c651abdd0d57c3da689a4595d279fdb0ff0d06b5508c755b80d57d94c3`.

Estimated v1 execution-engine completeness: **about 80%**, a rough component estimate.
This loop is local fixture library infrastructure, not a deployed daemon, broker
stop order or hard real-time guarantee. Synchronous local storage/calendar work can
still stall its parent event loop. Actual broker contracts, authenticated model
validation/adoption, deployed supervision/operator transport/alerts, off-host
protection and host-failure proof remain. The server release, SHADOW experiment and
first scheduled regular-session evidence gate are unchanged. No authenticated
model/broker call, server update or LIVE capability was introduced.

## Isolated operator transport follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `97aa22b7718b1c65f028777d90d6e38019cedd9d`
before editing. PR #1 remains draft and main is unchanged. The opt-in fixture
engine now has a separate native-TLS control application exposing only authenticated
bounded review and the six existing signed operator commands. Startup requires
explicit prior key enrollment and a VERIFIED journal/authority pair; it never
creates an engine, enrolls credentials, migrates state or resumes execution.

The read token and signing key are separate 32-byte hex secrets in private,
owner-only regular files. Files/capability retirement are rechecked per request.
The API pins an exact HTTPS origin, rejects forwarding/ambiguous headers and
cross-origin requests, provides no cookie/CORS or order/LIVE/enrollment/recovery
routes, and disables documentation. Native ASGI TLS with proxy-header handling
disabled is required; this is not wired into the current observer's Caddy route.

Review binding/revision/evidence share one read-only snapshot and omit prompts,
full event/order/fill history and signing material. Responses are capped at 64 KiB.
Commands require the read token and exact HMAC envelope. Existing expiry, reviewed
revision, generation, reservation ownership, fresh recovery evidence and atomic
action/audit/receipt rules are preserved. Replays never reapply an action or turn
a rejection into approval. Signed rotation/revocation retain the halt, retired
keys cannot obtain replay receipts, and trusted local key provisioning/recovery
remains required.

Known-length/chunked request bodies are capped at 16 KiB, with a default five-second
body deadline and four admitted requests (maximum eight). Malformed/duplicate/
nonfinite/extra JSON is rejected without echoing validation details. All responses
carry privacy/no-store headers. A cancellation test caught early admission release
in the generic HTTP middleware wrapper; the final pure ASGI boundary retains the
slot until cancelled local thread work drains, even after repeated cancellation.
A lost response does not prove nonapplication: inspect/replay the same signed
command while its capability remains active. A body timeout cannot abort a
committing SQLite transaction or establish a hard real-time storage guarantee.

Verification: **614 tests passed in 54.07s with warnings treated as errors**, including
**57 new control-transport tests**. Tests cover read-only bytes; startup provisioning,
restore and private-file requirements; auth/TLS/origin/header rejection; parser,
body and admission bounds; cancellation/committed receipt retention; durable replay;
stale reviews; unknown/attempted-order recovery rejection; unattempted abandonment;
alert acknowledgment without resume; fresh owned-position supervision; rotation,
revocation and read-token changes; runtime engine changes; journal-only rollback;
and oversized review rejection. Changed-code Ruff check/format, pip check and
whitespace checks passed.

The wheel installed outside the checkout passed a native Uvicorn HTTPS proof under
optimized Python and warnings as errors. The client validated the generated
loopback certificate, anonymous and forwarded-header requests were denied, signed
halt/resume and exact replay succeeded, and a client closed its connection after a
third command committed but before receiving the reply. Replaying that same command
returned its original receipt without reapplying it. Three durable command receipts,
private credentials/state, VERIFIED restore authority, unchanged read-only bytes,
zero broker/model calls and a reaped server were verified. The proof harness was
corrected to treat HTTP header names case-insensitively before its completed run.
Wheel SHA-256:
`06993ae79c130b449c4d9d99dec138035ce3e2c8f29b0f47062d02104fe50fbf`.

Estimated v1 execution-engine completeness: **about 82%**, a rough component estimate.
This proves the isolated fixture transport, not actual-host TLS/certificate lifecycle,
key provisioning, deployed recovery, user identity or broker authority. Actual broker
contracts, authenticated model validation/adoption, deployed supervision and alerts,
off-host restoration and host-failure proof remain. The deployed release and SHADOW
cohort are unchanged; first scheduled regular-session evidence remains unobserved
in this workspace. No LIVE capability, actual server update or outbound broker/model
call was introduced.

## Durable alert delivery follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `7d2e41c2b246e94dbf09ed06083eac8fc6a063a7`
before editing. PR #1 remains draft; main and the deployed worker are unchanged.
The opt-in fixture engine now freezes an HTTPS sink/limits/private token path and
requires VERIFIED restore authority before delivery enrollment. It sends minimal
alert identities rather than account, order, money, prompt or full event payloads.

Attempts are committed before the fixed isolated child runs. An exact strict sink
receipt is required; redirects, malformed/foreign/oversized/compressed receipts,
TLS/credential failures and timeouts cannot mark delivery complete. Native TLS
verifies hostname/trust; optional CA file/hash and private token are checked per
request. Broker/model secrets, proxies and engine database handles are excluded.
A nonblocking single-host lifetime lock spans awaits and child cleanup; a watchdog
bounds orphan work after parent death. Idle polls are read-only.

Lost responses/restart/cancellation retain the identical alert ID, payload and hash.
Default retry delays are 60 then 120 seconds, with at most three attempts per batch.
Exhausted alerts stop automatic retries. Trusted-local reasoned rearm audits a new
bounded batch while keeping cumulative attempts and identity; it neither resumes
trading nor acknowledges an alert. There is no HTTP rearm route. Other due alerts
are not starved by a waiting or exhausted earlier alert.

Once enrolled, overdue (default 120 seconds), future/invalid-clock or exhausted
undelivered alerts block new entries and model-call receipts. HOLD remains first-class;
governed protective SELLs retain their existing checks. Delivery confirmation and
operator acknowledgment remain independent, and neither clears a dispatch halt.
Journal and authenticated operator review expose delivery backlog health. The sink
must durably deduplicate IDs before returning a receipt; remote receipt acceptance
is not evidence of human notification or resolution.

Verification: **673 tests passed in 91.39s with warnings treated as errors**, including
**59 new delivery tests**. Changed-code Ruff check/format, pip check and whitespace
checks passed. Related tests also corrected fixture ordering so model evidence did
not mask the independent BUY gate, and verified specific restore rollback diagnostics.
Tests cover actual loopback verified-TLS child requests, strict receipts, lost replies,
retry caps/backoff, private credentials, trust changes, leases, duplicate owners,
repeated cancellation, actual parent crash/watchdog exit/reaping, storage failures,
restart, idle read-only bytes, audited outage rearm, no starvation, entry/model gates
and governed protective exits.

The installed wheel outside the checkout passed the native HTTPS sink/journal restart
proof under optimized Python and warnings as errors. The first request was durably
accepted by the local sink but lost its response. After sink and engine restart, the
same ID/payload/hash replay returned one durable unique receipt for two requests.
Both children were reaped; restore status remained VERIFIED, private files and
read-only byte checks passed, halt and acknowledgment state remained unchanged,
and there were zero broker/model calls. Wheel SHA-256:
`2c848ea63c78f11daaa419bf21102e26c71c3cdcd2370a04b2af7625df5bd84f`.

Estimated v1 execution-engine completeness: **about 84%**, a rough component estimate.
This verifies transport against a local contract sink, not deployed external alerts
or human delivery. Actual sink/notification provisioning, server integration and
credential lifecycle, off-host restoration/host-failure proof, actual broker
contracts and authenticated bounded-model adoption remain. Synchronous storage and
whole-history restore hashing are not hard real-time guarantees; paired rollback
and multi-host coordination remain outside local fencing. The deployed release,
SHADOW cohort and unobserved first scheduled regular-session evidence gate are
unchanged. No LIVE, broker write path or external recipient notification was added.

## Paired evidence checkpoint and archive follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `a4a154ca77d8f50c0a7c60a4f8781755646add8d`
before editing. PR #1 remains draft, main is unchanged and the deployed SHADOW
worker/backup cron remain on their existing release. This adds explicit fixture
execution evidence export, inspection, archive transfer and quarantine staging;
it does not update the deployed Robinhood database, secrets or services.

Export requires a compatible private journal and VERIFIED authority pair. It holds
both SQLite RESERVED locks and uses separate read connections for the two backup
copies, blocking source writers until both captures finish. It then rolls back the
lock transaction without changing source bytes or authority generation. Copies
pass integrity/logical authority verification. A fixed uncompressed envelope has
no arbitrary paths, caps the artifact at 64 MiB and the manifest at 4 KiB, binds
member hashes/sizes and records original authority identity/generation/state hash.
The private file is fsynced and published exclusively without overwriting targets.
Signing/API/OAuth credential files are not included; journal audit data remains
private and the envelope itself is not encrypted at rest.

An independent retained full-file SHA-256 pin is mandatory before inspection,
retrieval or staging. Wrong/truncated/trailing/duplicate/misbound/corrupt evidence
and complete older-pair substitution against a newer pin fail before publication.
A user-selected old pin still represents historical evidence; this does not create
an online latest-generation witness or cure paired rollback.

Explicit one-request PUT/GET archive operations use a separate exact HTTPS origin,
a dedicated private token, verified native TLS, optional bound CA and a fixed
isolated child. No redirects, proxy discovery, SDK retries, engine handles or
broker/model credentials are provided. Bounded pipes, a maximum-30-second process
deadline, cancellation TERM/KILL/drain/reap and parent-death watchdog retain the
existing capability boundary. A private receipt lock and fsynced IN_FLIGHT record
precede upload. Only an exact strict retention receipt becomes REMOTE_ACCEPTED;
lost replies/errors leave UNKNOWN and cancellation/crash leaves IN_FLIGHT. Same-ID
retry is explicit and destination-bound; attempts accumulate and no upload is
automatically repeated. A saved receipt records historical acceptance; retrieval
separately validates the stored bytes and publishes no failed/older download.

Recovery creates only a new private evidence directory with differently named
journal/authority files and a final verification marker. Original unresolved
orders, reservations, fills, costs, model receipts, halt and credential generations
are retained. No broker truth, terminal outcome, cost resolution or fresh risk
approval is invented. There is no normal journal authority sidecar; engine opening
fails before mutation. The tool cannot initialize, migrate, re-enroll, release,
resume or replay execution. A privileged filesystem owner remains outside this
local boundary.

Verification: **730 tests passed in 117.54s with warnings treated as errors**, including
**57 new checkpoint/archive tests**. Changed-code Ruff check/format, pip check and
whitespace checks passed. Tests cover private/bounded inputs, source-byte preservation,
concurrent source writes blocked across both copies, authority/pin/format/integrity
rejection, source-loss evidence recovery, original unknown model/order state, strict
TLS receipts, explicit retry, no retargeting, corrupt/older retrieval, copy/deadline/
receipt storage failures, repeated cancellation, actual parent death/watchdog exit
and reaping, and execution denial. Fixture registration was corrected before the
completed focused/full runs; the final source and transport checks passed.

The installed wheel outside the checkout passed under optimized Python and warnings
as errors with a separate durable native-TLS archive process. The first upload was
stored but its reply was lost. After archive restart, explicit same-ID/bytes retry
returned one durable object for two upload attempts. All original source journal,
authority and local bundle files were then deleted in the fixture. Download matched
the retained SHA-256; quarantine retained the dispatch halt and one active UNKNOWN
order, and ordinary engine opening was denied without changing evidence bytes.
Private-file checks passed and all three transfer children plus both archive server
instances were reaped. There were zero broker/model calls. Wheel SHA-256:
`0657480b6c7d50420e6708d54e8ad944c0852520bd71ce1c50d9785ee766758b`.

Estimated v1 execution-engine completeness: **about 86%**, a rough component estimate.
This proves simulated source loss and the archive client contract, not actual
cross-host retention, deployed backups, power-loss behavior or active-state recovery.
A real independent archive endpoint/pin custody, retention/encryption/credential
lifecycle, latest-generation witness and authenticated recovery still need proof.
Export can delay source writes and local storage/hash work is not hard real-time.
Actual broker contracts, authenticated bounded-model validation/adoption and deployed
supervision/control/notifications remain. The existing SHADOW cohort and unobserved
first scheduled regular-session evidence gate are unchanged. No LIVE capability,
broker mutation, external recipient notification or server update was introduced.

## Fixture PAPER runtime follow-up — 2026-10-07 UTC

The new opt-in PaperRuntime connects the exact durable fixture engine, venue, quote
feed, independent supervisor and optional bounded judgment coordinator. Default is
an explicit stub HOLD. This is isolated from the deployed SHADOW worker, Robinhood
account and frozen `virtual-v1` population. Operations: [PAPER_RUNTIME.md](PAPER_RUNTIME.md).

Enrollment requires VERIFIED paired authority, precedes orders/model attempts and
freezes source identities/paths, engine/supervisor/model policies, runtime limits and
current-slot XNYS cadence. A private single-host lease spans the whole service and
all child cleanup; the CLI takes it before writable startup recovery. Initialization
is exclusive, with private separate fixture files, and supplies PAPER/LIVE-disabled
settings explicitly. There is no automatic enrollment/rebind/reset on restart.

The independent supervisor, runtime heartbeat and scheduled cycle task run together.
Cycle admission requires the supervisor's exact freshly observed quote sequence/hash
and reconciled account truth. A durable current-slot claim plus governed packet
precedes any model call. One attempt per 15-minute regular-session slot; no missed-slot
backfill or interrupted replay. Known model cost remains counted when late judgment
crosses a slot and cannot prepare/dispatch. HOLD, risk rejection and fake execution
retain their decisions/results and existing detailed risk/usage/dispatch evidence.

Entry health is revoked during shutdown and after stopped/stale/failed ownership;
new model receipts and BUY admission/dispatch require it. Protective SELL retains
its existing checks and runs while model reasoning waits. Interrupted cycles persist,
halt and block later slots without an automatic resolution command. Failure stops
all components. Repeated cancellation drains fixed children before lease release,
then finishes bounded supervision; STOPPING ticks cannot renew supervisor authority.

Integration testing found a read/submission race: a supervisor read during SUBMITTING
could falsely interpret pre-acceptance absence as a missing attempted order. Fenced
supervisor reads now defer until the bounded attempt settles, renewing neither account
evidence nor heartbeat. UNKNOWN/missing orders still run the normal fail-closed checks.
No attempted order is replayed or reservation released by this deferral.

Verification: **757 tests passed in 126.65s with warnings treated as errors**, including
**27 new runtime cases**. Coverage includes scheduled HOLD/restart ownership,
duplicate-run admission before writes, known/unknown model usage, risk rejection,
slot crossing, service failure, stale/stopped entry/model gates, interruption/no replay,
protected cleanup during repeated cancellation, private key/lease files, immutable
policy, explicit paired authority, bounded publication and read-only CLI reports.
Related supervisor/process cases passed; changed-code Ruff/format, pip check and
whitespace checks passed.

The wheel installed outside the checkout passed optimized-Python/Werror proof using
real fixture/model subprocesses and a mocked native SDK transport, with no external
calls. The runtime scheduled a governed entry, reconciled a scripted fill and began
its second scheduled judgment. While the model child remained blocked, independent
supervision dispatched a governed fake SELL and reconciled flat after the second
scripted fill. Shutdown reaped all children, preserved one interrupted cycle and an
unknown model receipt, kept the halt and withheld net economics. Known cost was
`0.00015`; the authority pair remained VERIFIED and reporting changed no store bytes.
A separate installed native CLI process, with an explicitly closed fixture calendar,
rejected a duplicate start, handled real SIGTERM with exit 0 and persisted STOPPED
without any cycles or network calls. Wheel SHA-256:
`423bfbeb7e5155af03acf1fde92e645c2507154c47d13ee7c5ec20e47e5b8f91`.

Estimated v1 execution-engine completeness: **about 87%**, a rough component estimate.
This connects fixture scheduling/supervision/judgment/execution; it is not production
market-data collection, automatic fake fills, an authenticated provider run or trading
signal evidence. Operator/alert/archive service provisioning, real data integration,
authenticated bounded-model validation/adoption, host failure/recovery and actual
broker capability contracts remain. The deployed worker stays at its recorded release;
no server update, real broker write, LIVE capability or experiment policy change occurred.

## Signed PAPER interruption recovery follow-up — 2026-10-07 UTC

RESOLVE_CYCLE extends the existing operator capability/control transport with a signed
exact cycle_slot target. Fresh revision, journal/generation/actor/reason/expiry/MAC
checks and atomic durable command receipts remain. The six original action envelopes
retain their canonical signatures and existing receipt fingerprints. No endpoint,
model tool, broker write adapter or automatic recovery path was added.

Resolution requires VERIFIED authority, a halted STOPPED/FAILED runtime and its free
lifetime lease through commit. Active-owner cleanup cannot race resolution. Only a
completed INTERRUPTED claim can be resolved; remaining CLAIMED rows first need normal
startup review. Fresh complete account reconciliation, no issues/active reservations
and fresh owned-position supervision are mandatory. Unknown model costs/violations
block it. Linked model evidence must match frozen policy, original packet, provider
identity/count/usage/decision/audit/token limits and pinned-rate cost. Any linked order
must already be terminal, with fresh matching terminal history after an actual fake
attempt. Unattempted PREPARED orders require the existing explicit abandonment first.

An immutable overlay saves the original-cycle hash, reviewed snapshot/ledger/model/
order evidence and signed command identity. The original cycle remains INTERRUPTED;
model usage, orders/fills, positions, alert acknowledgments, limits and dispatch halt
remain. Only a hash-matched resolved interruption ceases blocking future slots. The
original slot stays attempted forever, and other unresolved claims still block.
A separate reviewed RESUME retains its risk checks and fresh service/supervisor gates.
There is no declaration that an unknown model call was free and no automatic replay.

Verification: **809 tests passed in 123.91s with warnings treated as errors**, including
**52 new recovery cases**. These cover receipt replay across restart/expiry,
concurrent commands, exact target/signature/revision and six-action compatibility,
runtime lease/status/clock guards, fresh account/owned-position evidence, unknown
cost blocking, original packet/usage/decision/count/policy bindings, terminal order
reconciliation, immutable claim/halt/fill/cost preservation, storage/event/receipt/
authority rollback, changed resolution lineage, read-only bounded review, signed
HTTP transport and later-slot continuation only after separate resume. Changed-code
Ruff/format, pip check and whitespace checks passed.

The wheel installed outside the checkout passed optimized-Python/Werror proof via
real native verified loopback HTTPS. A signed resolution applied and its repeated
command returned the original receipt. Review confirmed the retained halt before a
separate signed RESUME. After the API process stopped and was reaped, the installed
runtime rejected the original slot, attempted one later scheduled stub HOLD and
stopped cleanly. Original interrupted evidence was unchanged, the resolution stayed
singular, read-only store bytes were unchanged and the authority pair remained
VERIFIED. Server and all bounded read children were reaped; zero broker/model calls
occurred. Wheel SHA-256:
`e1d929df12ae9b175104585a7638c865a73a52f43d564c5ee77d0c3820b83d30`.

Estimated v1 execution-engine completeness: **about 88%**, a rough component estimate.
This proves reviewed recovery of known fixture evidence, not active-order release,
unknown/no-charge cost recovery, authenticated provider semantics or deployed controls.
Actual read-data integration, bounded-provider validation/adoption, external control/
alert/archive provisioning, host failure/recovery and broker capability proof remain.
The deployed SHADOW release/cohort, main and LIVE state are unchanged. No broker
placement, cancellation, real-account mutation or server update was performed.

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
