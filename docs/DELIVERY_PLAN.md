# Trade-Bot delivery plan

Plan recorded November 10, 2026, New York time. This is the current work order
referenced by [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md). Historical milestones and
proof documents remain evidence, not competing instructions to initialize another
account. [PAPER_NEXT_SESSION.md](PAPER_NEXT_SESSION.md) owns host operation.

## Destination and current baseline

Deliver a dependable, understandable trading product: automatic daily preparation,
fresh original Robinhood data, eligible strategy evaluation, local simulated entry
and protection, exits, restart reconciliation, clear operating status and retained
results. Then complete a separately governed Robinhood live-execution path. Broader
strategy evaluation and controlled improvement follow operational acceptance.

The verified implementation baseline is
`d2046f6363084ca26fc850130eb94cba51f07b6d`. It includes independent dashboard status
and a reproduced collector/runtime contention repair. The operator confirmed its
host installation, in-place dashboard reader update and reviewed schedule resume
on November 11; see [PAPER_HOST_DEPLOYMENT_20261111.json](PAPER_HOST_DEPLOYMENT_20261111.json).
The next worker launch and sustained effectiveness remain unobserved. Tuesday's
worker on 7db7475 failed after 802.3 seconds, with 26 delivered and 22 failed
collections, one confirmed
setup, no fills and no AI spend. A reported QQQ quote was 22.472 seconds old against
the unchanged ten-second admission limit. The exact delayed native subprocess
stage remains unresolved; the contention reproduction is not proof of that cause.

599 installed-package tests passed on the implementation baseline. One cross-UID
publication test and browser visual acceptance remain unverified in this workspace.
These results do not establish sustained host operation, connected fills or profit.

The account remains `local-simulation`, population `connected-simulation-1000-v1`,
with $1,000 initial virtual capital, at most two simultaneous plays, $1/day and
$5 total AI budgets, and an eight-contract catalog. Preserve balances, positions,
journals, halts, enrollment and original timestamps. Robinhood stays the only market
provider. No additional broker paper account, account reset, fabricated connected
data, substituted SPY-for-SPX strategy, relaxed validation or live orders belong to
this plan's PAPER work. Offline fixtures are isolated, explicitly synthetic, and
cannot be adopted as connected evidence or execution state.

## Delivery checklist

This is the active checklist for the work below. Start with **A1 and A2**.
Existing implementation and regression tests are the starting point; an unchecked
item means its complete acceptance condition is still open, not that all related
code is missing. Do not repeat completed work merely to check a broader item.

Check an item only when its stated result is demonstrated. Record the code commit,
test/report artifact and remaining limits beside the item in the same change.
Keep code-tested, host-deployed, operationally accepted and economically evaluated
distinct. A blocked item stays unchecked and names the exact missing input and
next action. Do not replace missing evidence with a date estimate.

### Established baseline

- [x] **P1 — One work order:** this plan is linked from SOURCE_OF_TRUTH.md and
  PAPER_NEXT_SESSION.md; current account constraints and responsibilities are
  recorded here. Original plan commit: a569e7f.
- [x] **P2 — Runtime repair published and tested:** d2046f6 contains the reproduced
  collector contention repair and installed-package proof. This checks that narrow
  code result only; Tuesday's exact delayed stage and host effectiveness remain open.
- [x] **P3 — Independent status implemented:** d2046f6 contains dashboard failure
  and missing-update states with authenticated HTTP tests. The operator confirmed
  the reader update on November 11; real-browser visual acceptance and failure
  visibility during a subsequent host run remain open under B and D.

### A — Integrated reliability and latency

- [x] **A1 — Whole-system harness:** exercise the installed collector, scanner,
  simulator, local subprocesses, publisher, dashboard and controller/report boundaries
  together, reusing existing fixtures and isolating all external calls.
  Published implementation: `29ef510748ea4fe0b18592d8483c7dcf836b15bb`.
  [PAPER_SYSTEM_CHECK_PROOF.json](PAPER_SYSTEM_CHECK_PROOF.json) retains 401 installed
  passes, including two synthetic round trips and restart in each scenario.
  Source/wheel/install identity was reverified during recovery. Provider/model and
  Docker boundaries remain fixtures; full-duration/host/browser gates stay open.
- [ ] **A2 — Complete timing evidence:** connect attempt/packet/cycle identities;
  report each phase, quote age, receive lag, p95/p99/max and failed-attempt counts.
  `aad4e08` established native and common option traces. `d35d318` adds stock and
  Scope scans/quality, paid refresh waits, stock admission/dispatch and all three
  management-model paths, with original quote clocks and concurrent trace checks.
  `c787281` adds history phases, scheduler wakeup delay, native diagnostic overflow
  and committed native slot/model denominators, including actual abrupt-process
  exits before/within a trace. Work before any commitment remains explicitly
  unobservable. [Current proof](PAPER_CONTENTION_PROOF.json): 521 distinct installed
  passes and one known cross-UID skip. Full-session timing/capacity profiling
  remains under A6; A2 acceptance is still open.
- [ ] **A3 — Measured repairs:** reproduce and close the actual bottlenecks with
  before/after evidence; decide connection reuse from measurements and validate
  its isolation, refresh ownership, deadlines and cleanup if adopted.
  `c787281` reproduces and repairs synchronous history work and display/report
  read-lock contention, with three failing baseline cases and passing installed
  repairs. Tuesday's actual native-process cause and provider connection-reuse
  measurements remain unresolved; these repairs do not establish those causes.
  `194563c` separately fixes the November 12 pre-launch schema rejection: the
  exact operator-observed revision changes only two interval descriptions from
  the already reviewed metadata. Ten baseline failures become passing cases;
  502 installed regressions pass. [Review and host boundary](PAPER_SCHEMA_REVISION_20261112.md).
  This is not a loaded-journal latency repair or a confirmed host rollout.
- [ ] **A4 — Independent protection:** prove that model waits, history work and
  display/report failures cannot improperly stop management of an owned position.
  `aad4e08` isolated in-run publisher failure. `d35d318` adds verified-held startup
  protection for missing/partial display snapshots, read-only protection-only host
  review and entry-resume rejection. Both startup scenarios retain the damaged
  display and complete the held QQQ exit without another entry-model call. A
  management/display-failure overlap case preserves protection, model cost and
  single-exit accounting. `c787281` moves history validation off the protection loop
  and releases native display/report read locks before processing. A combined
  one-CPU case exits while history, advice and display work wait and a report is
  open; final accounting is verified and no duplicate exit/model call occurs.
  [Current proof](PAPER_CONTENTION_PROOF.json); [contract and limits](PAPER_TIMING_PROTECTION.md).
  Sustained full-duration resource-profile proof remains under A6. Unverified
  startup exposure retains its authority/accounting rejection boundary.
- [ ] **A5 — Failure/restart matrix:** exercise every condition in A's matrix;
  preserve accounting, unknown outcomes and bounded recovery without duplicates.
- [ ] **A6 — Duration and capacity:** pass accelerated calendar/multi-day cases
  and a full configured-duration wall-clock soak under the host resource profile,
  including journal growth; identify any residual host-only restriction tests.
  The new [duration/capacity preflight](PAPER_DURATION_CAPACITY.md) runs real elapsed
  time on one CPU. A small-journal 90-second lifecycle passes, but the 73 MB case
  still expires its admission lease and retains an uncertain-attempt halt.
  Exact row-encoding reuse improves restore hashing; bounded snapshot setup retries
  repair a separate SQLite lock race. The full 21,480-second run was not started
  after the loaded failure. Sampled RSS is not host cgroup proof, and synthetic
  padding/linear growth projection is not month-history acceptance.
  [Retained evidence](PAPER_SOAK_CAPACITY_PROOF.json).

### B — Operating dashboard and control

- [ ] **B1 — Complete operating view:** show schedule, controller/worker/feed/account
  freshness separately, scans, failures, latency, recovery allowance, fills and costs.
- [ ] **B2 — Explain the trading path:** show family eligibility, understandable
  HOLD/blockers, exact positions/protection and signal-to-fill incident timelines.
- [ ] **B3 — Durable controls:** integrate authenticated pause and reviewed recovery
  through existing authority; verify CSRF protection, receipts and changed-state
  rejection; acknowledgment alone must not resume trading.
- [ ] **B4 — Independent notification plumbing:** test deduplication, delivery
  failure and missing-heartbeat detection locally; record the chosen destination
  and authorized delivery evidence separately before claiming alerts work.
- [ ] **B5 — Browser acceptance:** retain actual desktop/phone screenshots and
  keyboard/contrast/layout checks for healthy, failed, stale, empty and held-position
  states. Workspace restrictions remain an explicit blocker until resolved.

### C — Strategies and shared execution

- [ ] **C1 — Shared lifecycle closure:** verify the complete known-trigger CALL/PUT
  path, two-play contention, fills, protection, exits, costs and restart together;
  reuse existing passing cases and add only missing integration coverage.
- [ ] **C2 — DEGEN closure:** cover completed bars, confirmation, exact contracts,
  pre/post-model freshness, sizing and session exits on the installed path.
- [ ] **C3 — Swing closure:** distinguish implementation/geometry failures from
  invalid originals; complete target, seed, carry and restart cases; retain the
  exact original-history/binding requirement if provider evidence is still missing.
- [ ] **C4 — Scope closure:** complete SPX/SPXW input/watch/admission/protection/exit
  integration and pacing cases; keep missing original history and reviewed
  contract/session/pattern bindings explicit, within eight catalog slots.
- [ ] **C5 — Truthful family readiness:** maintain separate implementation,
  configuration, provider-evidence and setup-dependent blockers for each family;
  show stock capability blockers without implying options acceptance closes them.

### D — Consolidated release and connected acceptance

- [ ] **D1 — Offline release gate:** satisfy A, essential B and the selected family's
  C; retain installed-package identity, regression/soak/timing/visual evidence and
  the exact residual environmental gaps against the acceptance budgets below.
- [ ] **D2 — One host handoff:** verify stopped-host upgrade, capacity, existing
  reader/schedule/account preservation, preflight and rollback compatibility;
  record the actual installed image/release and any residual host-only test results.
- [ ] **D3 — Automatic diagnosis:** retain the bounded private support export on
  failure and session end; display the actionable incident without manual log probes.
- [ ] **D4 — Sustained operation:** observe two consecutive full scheduled sessions
  meeting coverage/health gates without manual repair; retain all outages and HOLDs.
- [ ] **D5 — Connected lifecycle:** observe an authentic eligible entry and full
  exit with reconciled cash, positions and model costs. Synthetic proof and a
  healthy no-setup day do not check this item.
- [ ] **D6 — Remaining family evidence:** accept Swing/Scope only against their
  required valid originals and exact bindings; preserve independent blockers
  without delaying an otherwise accepted DEGEN path.

### E — Live integration and strategy evaluation

- [ ] **E1 — Adapter contracts and offline proof:** cover exact identity, preview,
  submit/cancel races, partial/unknown outcomes, restart, settled funds and expiry
  semantics without real brokerage writes.
- [ ] **E2 — Actual capability and recovery evidence:** verify the selected
  account/product, protective exits, independent alerts and backup/restore; prepare
  a concrete funded-release review with outstanding evidence clearly named.
- [ ] **E3 — Explicit funded release:** obtain reviewed bankroll/loss limits and
  real-write authorization for a pinned candidate before a supervised canary.
  PAPER work and this checklist do not authorize LIVE.
- [ ] **E4 — Economic evaluation:** retain chronological validation, untouched
  evaluation, benchmarks, costs, drawdowns, attempted variants and coverage
  denominators; distinguish execution success from evidence supporting a strategy.

### F — Controlled improvement

- [ ] **F1 — Operational automation:** accept diagnosis, bounded recovery,
  reporting and evaluation against the reliable foundation.
- [ ] **F2 — Isolated challengers:** version and evaluate proposed changes without
  mutating the active population, risk limits, bankroll or validation rules.
- [ ] **F3 — Reviewed promotion/rollback:** record evidence and explicit authority;
  prevent self-promotion to LIVE or automatic capital/risk escalation.

## Work order and responsibilities

| Package | Concrete result | Dependency and completion gate |
| --- | --- | --- |
| A. Integrated reliability and latency | Reproducible whole-system failures; a stable, measured collection-to-exit loop | First coding priority. Pass the offline gates below on the installed package. |
| B. Operating dashboard and control | The user can understand operation, failures, blockers and recovery without shell diagnostics | Develop alongside A using fixtures; validate actual browser rendering and independent failure visibility before acceptance. |
| C. Strategy and execution closure | Each family has explicit inputs, exact contracts, complete lifecycle and truthful eligibility | Reuse existing code. Complete DEGEN's shared path first; finish Swing/Scope offline work while authentic inputs remain separate. |
| D. Consolidated release and connected acceptance | One verified deployment, automatic evidence capture and a measurable scheduled run | A, essential B, and the selected family's C must pass. Missing Scope evidence does not block independently eligible DEGEN. |
| E. Live integration and evaluation | A separately tested Robinhood adapter and a concrete funded-release review | The selected family must have operational PAPER acceptance. Documentation, protocol design and read-only capability work can proceed earlier. |
| F. Controlled improvement | Versioned challengers, offline evaluation and reviewed promotion | Requires reliable operation and credible data coverage; never autonomous risk-limit changes or capital escalation. |

The assistant owns implementation, retained-evidence analysis, test automation,
documentation, branch publication and one consolidated deployment procedure. The
operator owns the host access that is not available here, choosing a notification
destination when needed, and any later explicit funded limits/authorization. There
is no routine daily command assignment. No subagents are used without an explicit
request. Independent development tasks can proceed while a soak runs or provider
evidence is unavailable; they do not require parallel agents.

## A. Make the whole trading loop dependable

### Build one integrated acceptance harness

Extend the existing connected runtime, feed, replay, portfolio and host tests;
do not build another execution engine. Exercise the installed package with real
local subprocesses, SQLite journals, collector normalization, scanner, execution,
publisher and authenticated dashboard reader together. Include controller/report
boundaries and exact worker identity handling. Provider/model fixtures replace
only external boundaries and report themselves as fixtures.

Use retained originals unchanged for parsing and negative regressions. Use a
separate, labeled synthetic stream when a known qualifying setup or fill path is
needed. Do not refresh old originals into current market evidence. Test both
advancing wall/monotonic timing and explicitly isolated replay clocks; compressed
replay alone cannot prove real process deadlines or sustained resource behavior.

Run accelerated regular-session, half-day and multi-day scenarios. Also run an
unattended wall-clock soak for the full configured daily-worker duration, with one
logical CPU and the measured host memory limit. Grow journals beyond Monday's
67,133,440-byte source and through a projected month of activity. Profile SQLite
queries, disk growth, CPU, memory, child lifetime and event-loop delay. Verify
projections stay bounded without pruning the native accounting/evidence ledger.
The soak can run outside market hours while other work continues. If the workspace
cannot reproduce Docker, UID or kernel restrictions, deliver one credential-free,
disposable host harness for those residual cases; preserve the missing proof until
that harness actually runs. It must not mount the connected account writable.

### Measure the critical path before redesigning it

Collect bounded timings/counts for child startup, authentication/connect, schema
work, each provider tool, response close/serialization, normalization, feed
publication/acceptance, native account read, scan, model wait, final admission and
execution. Join them by attempt, packet and cycle identity. Show median, p95, p99,
maximum and timeouts with denominators; successful-only averages hide the problem.
Separate original quote age from network receive lag and local processing delay.

The present capture path creates a read child and opens a connection per attempt.
Measure its cost. If it dominates, implement bounded connection/session reuse in
the read-only isolated boundary: one OAuth refresh owner, a serialized request
protocol, per-request deadlines/limits, checked schema identity, explicit reconnect
and child cleanup. Validate failures and cancellation before switching the production
path. Reuse is a design candidate, not an already delivered optimization or an
excuse to widen capabilities/deadlines. Keep the simpler path if measurement shows
the bottleneck elsewhere.

Keep quote protection and native reconciliation schedulable during history work,
scanning, model waits and dashboard publication. Cache only immutable, verified
inputs with exact invalidation. Prefer incremental indexed reads and bounded
projections. A failed history read must not erase usable independent protection
quotes; a partial response must not fabricate a complete scan. Preserve the one
execution owner and durable ambiguity handling. Do not introduce a second owner,
overlapping collectors or concurrent token refresh writers.

Review supervisor coupling: display/reporting failure must not itself terminate
protection for an owned position. Separate halting new entries from stopping
position management. Continue protection only with valid original market input
and durable native authority; if either is unavailable, preserve the held/unknown
state and alert explicitly. No component may invent a successful exit or restart
an ambiguous order. Prove this behavior with a position open when publication fails.

### Failure matrix

| Injected condition | Required observable behavior |
| --- | --- |
| Slow connection/tool/close; stalled child | Original deadline is enforced; child is reaped; phase is retained; stale evidence is rejected. |
| Busy normalization/history; growing SQLite; slow publisher | Execution/protection deadlines remain serviceable or the owner halts with an explicit failure; status remains independently available. |
| Stale, future, missing, reordered or partial quotes | Exact rejection; no invented freshness, fabricated fills or hidden gap. |
| Model timeout, invalid output or unknown charge | No unauthorized entry; uncertainty and reserved cost persist; exits remain independent of model judgment. |
| Crash before/after submission, fill, journal commit or publication | Reconcile the original attempt; no duplicate order, slot, fill or model charge; uncertain state stays uncertain. |
| Two plays, simultaneous candidates, one position exiting | Shared capital and capacity remain conserved; owned-play protection cannot be displaced by entry work. |
| Pause, SSH disconnect, reboot, clock boundary or early close | Durable stop/launch rules, exact container identity and date-specific enrollment hold; no unintended same-day rerun. |
| Missing/stale snapshot, dead trader, dead controller or lost browser connection | Distinct failed/stopped/unknown UI states; no false healthy state or assumed flat account. |
| Low disk, failed write or unavailable archive | Clear capacity/failure evidence; no unjournaled execution or automatic deletion of original state. |

Recovery remains bounded. The two enrolled flat-feed recoveries are the whole run
allowance; an exhausted allowance is visible. Arbitrary exceptions do not trigger
silent restarts. A new recovery class needs its own exact-state proof. Recovery of
an open position is distinct from resuming new entries while flat.

## B. Finish the operating product

Use the existing dashboard, reader, daily controller and signed operator concepts.
The independent status in d2046f6 is the starting point, not finished visual proof.

The top of the page must answer: Is automation scheduled? Is the trader alive?
Are valid quotes arriving? Are scans completing? Is it waiting for a setup, missing
an input, halted, stopped or failed? When was each fact observed? Are positions or
orders unresolved? What action, if any, is required? Keep controller freshness,
worker heartbeat, market freshness and account-snapshot freshness separate.

Provide a compact session view with release/mode/account identity, next scheduled
action, elapsed/planned runtime, completed/expected scans, read failures, latency,
recovery allowance, actual entry/exit fills, costs and strategy-specific blockers.
Show a candidate-to-decision-to-order-to-fill timeline with the exact admission
reason. Explain HOLD in ordinary language. Present positions with protection,
executable prices and their ages. Unknown values stay unknown. Performance charts
must distinguish realized results, marked values, external funding and costs.

Integrate a persistent stop/pause control through an authenticated, authorized,
CSRF-protected path with durable receipts. Reuse existing authority; do not add a
browser flag that clears halts. Separate acknowledging an incident from resuming
execution. Resumption displays the actual reviewed state and rejects intervening
changes. Do not assume the current host has operator control configured.

Make failed/stale status conspicuous independently of account publication. Add
deduplicated incident/recovery records and notification delivery health. Build and
test external notifications with a local receiver first; sending requires the
operator's chosen destination. An independent missing-heartbeat monitor is needed
for host loss because a failed host cannot publish its own alarm. No outbound
message, subscription or new service account is authorized by this plan alone.

Validate desktop and phone layouts, keyboard access, contrast, long reasons, empty
history, two positions, losses, stale data and unavailable snapshots in a real
browser. Keep screenshots with the tested release. HTTP/template checks do not
replace visual acceptance. If browser access is unavailable, record that exact
remaining gate rather than declaring the UI finished.

## C. Close strategies and execution without forcing trades

| Area | Code/fixture work | Authentic evidence or configuration still needed |
| --- | --- | --- |
| Shared execution | Known CALL/PUT setups through scan, model proposal, deterministic admission, reservation, later executable simulated fill, protection, partial/full exit and restart; two-play/cash/cost conservation | One connected entry-to-exit lifecycle using accepted original quotes and the configured model; retained usage/cost records |
| DEGEN | Six completed five-minute bars; 5/15-minute confirmations; exact affordable contracts; source-age checks before/after model; cutoff and liquidation paths | Eligible current-session bars, contracts and quotes; real setup occurrence is not guaranteed |
| Swing | Separate source validity from target geometry; reproduce interpolation, missing first target, chase, seed invalidation and carry/restart cases; verify original target/stop authority | Valid original required history and exact binding; investigate new originals only when the needed evidence can differ |
| Scope | Finish existing SPX input/watch/admission/owned-play/exit integration cases; exact SPXW metadata and session/pattern identity; pacing, arming, cutoff and cost attribution | Usable original SPX history plus reviewed SPXW contract/session/pattern bindings and explicit catalog allocation within eight |
| Stocks and other advertised capability | Identify implemented paths and their exact readiness in the UI | Existing executable-size/catalog blockers remain visible; an options pass does not imply stock readiness |

For each family maintain one list split into implementation, configuration,
provider-evidence and setup-dependent blockers. A family is enabled only when its
own contract is met. Preserve existing enrollment; any required future catalog or
policy amendment must be exact and versioned. Never silently evict held contracts
or reviewed bindings to fit Scope. No strategy threshold is relaxed to manufacture
the first trade, and no model-off fallback replaces the enrolled decision policy.

Reuse the already audited SignalFlow setup, sizing, management and UI concepts.
When adopting additional code, pin and inspect the relevant source and its tests,
then adapt the smallest useful part. Do not restart a broad audit, import the whole
service graph, or treat an unverified broker interface as a working live adapter.

## D. Release once, then measure connected operation

### Explicit acceptance budgets

These are proposed release criteria, not claims about current performance. They
do not amend enrolled risk, market freshness, spending or timeout policies.

| Dimension | Gate |
| --- | --- |
| State integrity | Zero duplicated execution/charges, lost accounting, unauthorized state resets or untracked unknown outcomes across the failure matrix. |
| Local timing | Zero deadline failures in the nominal full-duration soak. Target native-read p99 below half its configured deadline; report maxima and sample counts. |
| Entry freshness | Every admitted quote obeys the original strict age/clock/identity rules. Engineering headroom target: p95 quote age at admission at most five seconds, and no systematic exhaustion of the ten-second bound. If no eligible admissions occur, this metric is unmeasured. |
| Scan coverage | Account for every expected slot. Initial connected target: at least 99% of expected DEGEN slots after warmup get an actual evaluation. HOLD counts; feed-unavailable skips do not. Declare deliberate operator pauses separately; retain the full-session denominator and all outages. |
| Protection and stop | Protection does not wait for model completion. Stop, drain and child cleanup meet their existing bounds; no claimed flat state without accounting evidence. |
| Dashboard health | Worker failure visible within two one-minute controller ticks under healthy host/dashboard access; controller age over 180 seconds becomes unknown; browser polling failures explicitly show lost contact. These are monitoring bounds, not execution deadlines. |
| Durability/capacity | Full-duration and month-growth fixtures pass; restore verifies original hashes/accounting; measured disk headroom and growth are reported. Do not silently prune native evidence. |
| Strategy execution | Isolated known-trigger scenarios complete entry/protection/exit/restart now. Connected lifecycle remains a separate gate until actually observed. |

Build one immutable candidate from A, essential B and DEGEN's completed C. Run
scoped regressions during coding; run the combined installed-package suite and
soak at the release boundary, repeating only when changed code or failures justify
it. Keep application/wheel identity, dependency pins, benchmark evidence, failure
matrix and browser results together. A skipped environmental test remains a
named gap. No broad rebuild merely for a documentation/status change.

The consolidated stopped-host deployment must preserve the account, enrollment,
credentials, login, dashboard binding and scheduler pause. It checks capacity,
installs the pinned image, upgrades the existing reader, runs offline/read-only
preflight, publishes status, and retains an exact rollback predecessor. Do not
repeat initial dashboard activation or overwrite newer host work. Application
rollback cannot undo account mutations; compatibility must be checked before reuse.

Add a bounded private support export to the daily report: release/image/config
identity, Docker exit/OOM/resource data, sanitized terminal stages, timing summaries,
feed/scan coverage, run accounting, disk growth and incident history. Automatically
retain it on abnormal exit and at session end. Keep secrets and raw credentials out.
Expose a concise explanation in the dashboard. The user should supply one report
only if remote diagnosis still needs host-only evidence, not a chain of shell probes.

Use the existing calendar-driven schedule for connected acceptance. A short
automatic startup assessment detects broken collection promptly; it preserves
evidence and follows existing stop/recovery rules. It does not force a setup or
declare a healthy short run sufficient. After a failed run, the next market run
needs a documented changed hypothesis/fix/configuration or genuinely new required
provider evidence. Repeating the same failed conditions is not a test plan.

Unattended operational acceptance requires two consecutive full scheduled sessions
meeting the coverage/health budgets without manual repair, plus reconciliation and
clear final reports. A valid no-setup day can count toward operation. A real connected
entry and full exit are separately required to close the lifecycle gate. No fixed
number of days or trades establishes profitability, and no entries are forced to
meet a milestone. Swing and Scope remain independently gated.

If valid originals or timely delivery remain unavailable after measured local
overhead is removed, record the exact Robinhood capability/latency gap and keep the
affected feature blocked. Documentation defines expected capabilities; it cannot
replace a failed or missing response. Do not silently change provider, instrument,
freshness limits or repeatedly collect identical invalid overnight history.

## E. Complete the live path and establish strategy evidence

Use the same strategy, governor, accounting identities and operator semantics with
a separately reviewed execution adapter. Read-only protocol/capability design and
offline adapter tests can proceed while PAPER collects evidence. This plan does
not authorize real placement, cancellation, exercise, funding or live activation.

The adapter must cover exact account/product capability, order preview and
submission, stable client/order identity, partial fills, rejection, cancellation
races, disconnected/ambiguous responses, restart reconciliation, cash/settled-fund
limits, fees, broker cutoffs and exercise/expiry/settlement outcomes. Broker facts
are authoritative; local timeout never proves an order failed. Prove protective
exits and independent stop/alerts, including unexpected exposure. Verify backup
retrieval and recovery on an independent location before funded operation.

A funded candidate requires accepted PAPER operation and the selected family's
connected lifecycle; actual account capability evidence; reviewed real bankroll,
per-trade/full-premium/daily-loss/drawdown limits; a pinned release; an independent
failure alert; and explicit real-write authorization. Prepare the concrete review
before asking for those decisions. Small size belongs in a later supervised canary,
not as a workaround for the present timeout/data failures. LIVE remains disabled
until the separate release is approved and activated.

Operational success and strategy quality are separate. Preserve frozen strategy,
model/prompt and cost versions, every attempted variant and every missed/rejected
opportunity. Evaluate chronological development, validation and untouched periods;
avoid future data and overlapping-hold leakage. Compare against cash, a matched
SPY benchmark and a deterministic/model-off research comparator. Include spreads,
slippage, fees, model costs, allocated host costs, drawdown and data coverage. Missing
option paths remain excluded with denominators; underlying moves are not option
returns. A profitable small sample does not authorize scaling.

## F. Build controlled self-management on the accepted foundation

Automate evidence collection, diagnostics, bounded recovery, reporting and
evaluation first. A future research process may propose versioned strategies or
parameter changes in isolated populations, evaluate them chronologically and
present a promotion/rollback decision. It cannot rewrite active risk limits,
increase capital, remove validation, erase losses or promote itself to LIVE.
Versioned promotion needs recorded evidence and explicit authority. This work must
not displace the current reliability, UI and strategy-completion packages.

## Execution discipline and next checkpoint

| Work | Existing implementation surfaces to extend |
| --- | --- |
| Collection, timing and supervision | app/mixed/continuous_feed.py, app/mixed/connected_runtime.py, app/options/read_capture.py, app/options/read_worker.py, app/options/process.py |
| Acceptance harness and lifecycle | tests/test_portfolio_feed.py, connected/runtime/portfolio tests, app/mixed/portfolio_replay.py and existing replay/export code |
| Operations and release | scripts/paper-daily.py, scripts/paper-session-report.py, scripts/connected-session-host.py, scripts/connected-dashboard-host.py |
| Dashboard | app/mixed/paper_health.py, app/mixed/dashboard_reader.py, app/mixed/dashboard_snapshot.py, app/web/options.py and existing templates |
| Families | app/mixed/swing_feed.py, app/mixed/swing_binding.py, app/mixed/scope_setup.py, app/mixed/scope_feed.py and app/options family modules |

- Keep one task/evidence ledger in this document. Each package update names the
  defect or requirement, responsible code, reproduction, result, remaining input
  and next action. Mark code-tested, host-deployed, operationally accepted and
  economically evaluated separately; never collapse them into "ready."
- Start with the integrated reproduction/soak runner and complete phase timings.
  Use them to choose the runtime/collector repair. Develop dashboard incident
  states against the same failures. Complete missing known-trigger lifecycle
  scenarios before requesting another market-hours diagnostic run.
- Batch compatible changes into one tested runtime release. An urgent recovery
  fix may ship separately with its reason stated. Documentation-only changes need
  no host build. The existing d2046f6 deployment remains a pending recovery option;
  publishing this plan does not certify it installed or supersede its proof.
- Reuse already saved reports/captures before asking for data. Every host request
  must name the exact unanswered question and why local evidence cannot answer it.
  New original SPX/Swing inputs, genuine connected execution/model usage, actual
  host restrictions and later account entitlements are legitimate external gates.
- Keep main at b5359aaf396e692d2142d7e02908f1544e045ee6 and preserve
  feat/event-awareness-baseline. Publish on slice2/robinhood-read-shadow. PR #1
  stays draft; only its first paragraph may be replaced.

The next implementation checkpoint is one reproducible whole-system evidence
bundle, a measured latency bottleneck, and the repairs verified against both. It
is not another successful image build or a claim that a synthetic trade proves
the connected system works.
