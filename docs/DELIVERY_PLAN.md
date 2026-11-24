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

The November 11 implementation baseline is
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

### November 23 acceptance result

R3 guarded installation succeeded for `2d538b7`; R4 failed. The worker ran for
2h 57m 40s but made zero decisions. Three collections delivered and 341 failed;
all 13 supplied failure samples timed out at the broad `CONNECT` stage. The
terminal native snapshot timeout is separate. No publication failures were recorded.
[Evidence and next diagnostic gate](PAPER_SESSION_20261123_PROOF.json).

Keep the session-review hold. Read the saved runtime timings/resource configuration
before selecting a runtime or capacity change. The diagnostic patch closes the
report's missing collector/timing evidence and separates SDK loading from MCP
initialization. It does not resolve the connected failure or close R4. No limits,
worker lifecycle, freshness policy or account state changes are authorized by
this evidence alone.

### November 20 work order: repair the delivery process first

This section takes precedence over the older execution order below. The user
requested a process correction before another issue patch and then authorized
implementation. The host remains operator-managed. Retry resets and schedule
resumes are separate from candidate qualification and are not part of the handoff.

The operator confirmed `c03b628` installation and schedule resume. November 20
then failed preparation three times with `SchemaContractChanged`, zero market
reads and no worker. Adding only the optional string field
`get_equity_historicals.outputSchema.properties.data.properties.notice` to the
reconstructed November 18 schema produces the exact rejected metadata hash.
`data.required` remains `["results"]`. This establishes the specific mismatch;
it does not establish that every optional schema extension is safe.

The process defects are broader than this field: whole-catalog equality is used
as compatibility; an old worker failure can replace today's dashboard reason;
the persisted preparation error loses the detailed capture cause; and the release
handoff has required repeated operator commands without an operational acceptance
record. The existing installed-system harness is useful but uses fixtures at the
provider and Docker boundaries. Repeating its test count cannot close those gaps.

Work in this order, using the existing implementations and fixtures:

- [x] **R1 — Define the consumer contract, then implement compatibility.** Preserve
  exact raw metadata and validate each response against its discovered schema.
  Separately specify what the adapter consumes and which additive output fields
  it can ignore. Cover the reported `notice` with absent, present and empty-results
  responses; empty results never become usable bars. Reject changed required data,
  field types/units/clocks, unsafe permissions, removed capabilities and changed
  input requirements. Test changes to unrelated fields and schema constraints too.
  Do not solve this by adding a new accepted whole-catalog hash or ignoring all
  output changes. Review dependency scope so a family-specific failure cannot
  silently remove held-position data or masquerade as global readiness.
- [x] **R2 — One diagnostic report, current cause first.** Add one bounded,
  read-only command that reports installed release/image, current day and stage,
  original failure class, changed schema paths, receipt/evidence paths, worker
  identity/start/exit/restarts, feed/decision ages and publication state. No
  credentials, provider calls, account writes or retry-counter changes. Persist
  the safe capture cause rather than only `StepFailed`. The dashboard must lead
  with today's preparation failure and label older session reports as history;
  an old publisher error cannot override today's cause. Reproduce November 20
  using the November 18 report as retained history.
- [x] **R3 — One release candidate and one guarded handoff.** Build once; run the
  relevant incident reproductions and integration checks against that exact
  installed artifact. Include adapter/compatibility tests explicitly: the incident
  suite list omitted `test_read_schema_contract`; the corrected candidate includes it.
  Run a bounded candidate check on the actual host with real read-only provider
  discovery/capture and snapshot verification before activating its scheduler.
  Preserve source account state, installed release, enrollment and retry counters
  during preflight. Retain each stage's result so one failure does not require
  rediscovering the entire machine. Stop on a failed gate; distinguish install,
  schedule resume and worker launch in the result. No automatic counter clearing
  or duplicate worker launch. A rehearsal must cover a busy controller, changed
  schema, capture failure and rollback.
- [ ] **R4 — Operational acceptance of the exact deployed candidate.** Observe
  the same scheduled worker at launch, after 30 minutes, after two hours and at
  close. The first 30 minutes must show advancing feed sequences and decisions
  across due evaluation slots, valid source clocks under the existing limits,
  working publication and no unexplained skipped slots or fatal component errors.
  Report attempted/completed/missed slots, feed gaps, blocked families and recovery
  counts explicitly. A valid no-setup decision counts; an unavailable feed does
  not. Zero fills is acceptable. The longer checks must cover the same evidence
  plus clean closure and verified accounting. Diagnose a failed early check then,
  rather than waiting for the end-of-day review. Installation, process uptime and
  timer activity cannot satisfy this gate.

Most of R1-R3 is independent of market hours: compatibility, empty responses,
installed lifecycle replays, failure reporting, reader behavior and provider
connection/capture checks. Real quote freshness, current-bar availability and a
connected trading day need market hours. A synthetic round trip with valid quotes
must verify position protection under collector/history/publisher failures without
creating a connected position just to force a fill. A full-duration offline soak
is a candidate gate for timing/recovery changes, not a substitute for R4. Reuse
existing tests and run broader suites once for the final candidate; repeat only
when a new change, failure or unresolved concern justifies it.

Use one current checklist and evidence record. Report the next unmet gate and
its owner (implementation here; host commands by the operator), not a growing
count of commits or tests. Keep provider CONNECT failures, account publication
under load, Scope readiness and Swing geometry explicitly open. A functioning
subset must name blocked families; full product acceptance requires their closure.
Do not add CPU or relax limits without measurements identifying the bottleneck.

Candidate `9a140b8d8628c27f9304cd6331bbcee07af7074e` completes the offline R1-R2
implementation and R3 release workflow. The corrected `2d538b7` subsequently
passed guarded host qualification and installation, closing R3 as recorded below.
R4 stays unchecked until connected operation is observed.
[Implementation proof](PAPER_RELEASE_20261120_PROOF.json) distinguishes these results from the earlier [process audit](PAPER_PROCESS_REVIEW_20261120.json).

The compatibility policy permits only new optional scalar properties directly
inside an output `data` envelope. Existing fields, constraints and all input and
permission contracts still compare exactly after description removal. The complete
raw schema remains attached to its original responses, which are validated against
that schema throughout feed delivery and Swing-cache replay. Tests cover held
quotes and cached history under the reported metadata extension. An unknown
breaking change still blocks admission conservatively; this is not general
per-family schema negotiation and does not make an unavailable family ready.

The next action is the read-only schedule check in PAPER_NEXT_SESSION.md, then
one diagnostic command at each R4 checkpoint. The completed guarded release
command retains every stage and leaves the installed release unchanged on a
qualification failure; no further deployment or resume is implied.

The first real qualification of `9a140b8` passed the November 23 catalog but found
two empty December 4 exact-strike responses. Both provider calls were successful.
It stopped before activation and restored the timer; host `c03b628` was preserved.
The local post-read error lacked a structured reason, revealing an additional R2
gap. Candidate `2d538b7f32afa7b6df09e7af0d3534e9e27f71e5` adds bounded listed-strike
discovery after an empty probe and carries local stage/reason evidence through the
host/controller wrappers. The system suite now includes session-capture and
downstream catalog consumers explicitly. The operator subsequently supplied
`RELEASE_INSTALLED` for `2d538b7`, stage `reader`, with no reported failure and
receipt directory `/root/trade-bot-release-zk5617xi`. The inspected workflow
requires all capture/publication/owner gates before installation, so this closes
R3. Individual capture counts and fallback usage are not supplied by the summary.
Timer/schedule state still needs a read-only check; `scheduler_resumed: false`
is an action record, not a pause-state report. R4 remains open.
[Qualification failure and repair evidence](PAPER_CATALOG_CAPTURE_20261120_PROOF.json).

### Existing implementation checklist

The following items remain the technical backlog. Work through **R1-R4** above
before resuming feature work or treating another scheduled day as accepted.
Existing implementation and regression tests are the starting point; an unchecked
item means its complete acceptance condition is still open, not that all related
code is missing. Do not repeat completed work merely to check a broader item.

Check an item only when its stated result is demonstrated. Record the code commit,
test/report artifact and remaining limits beside the item in the same change.
Keep code-tested, host-deployed, operationally accepted and economically evaluated
distinct. A blocked item stays unchecked and names the exact missing input and
next action. Do not replace missing evidence with a date estimate.

November 18 host evidence: `daily-20261118` ran nearly six hours but completed
only two cycles. One publisher timeout latched entries off at 10:07:14 a.m.;
653 collection attempts failed. A2 now distinguishes response serialization,
writing and completed flush. A4 preserves the publication halt through feed
errors and removes dashboard-history rendering from accounting publication.
Published repair `c03b628` passes 623 installed-system tests (one environment
skip), plus three additional damaged-account rejection checks.
Provider connection failures and connected acceptance remain open.
[Repair evidence](PAPER_SESSION_REPAIR_20261118_PROOF.json).

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
  passes and one known cross-UID skip. `0d79a3a` reports the delivery commit,
  parent-observed native spawn wait and deadline remaining at spawn. Entry quote
  age at dispatch fell from 8.91 seconds on the loaded baseline to 7.32 and
  6.83 seconds in the final 90- and 335-second runs. Full-session timing and
  capacity profiling remain under A6. [Loaded run evidence](PAPER_LOADED_HANDOFF_20261114_PROOF.json).
  `5f5f96c` measures original approved entry source age, receive lag and local
  time from matched reservation evidence. At 120 MB normal one- and two-CPU
  short runs reached admission at 6.55 and 6.30 seconds. The repeated one-CPU
  deadline miss was subsequently recovered. Terminal child progress is retained
  even when the child finishes before the parent observes spawn.
  `42648c6` removes a scheduler import from the native venue clock check.
  Two short and two two-slot one-CPU runs completed the known lifecycle.
  Approved source ages ranged from 6.01 to 6.84 seconds across the four.
  [Comparable runs](PAPER_CAPACITY_20261114_PROOF.json).
  `4329383` measures scheduled worker and reaped-child CPU. Matched 335-second
  tests used 0.73 and 0.75 busy cores on average. Original source age was 6.75
  and 6.18 seconds at the respective opening reservations. The older full
  fixture lost decision coverage after a feed halt despite continued dashboard
  and collector activity. `23b0669` counts scheduled evaluations from both
  original symbol scans and settles a trusted model reply and charge in one
  fenced commit. Under the same 335-second load, one and two CPUs averaged
  0.718 and 0.732 busy cores, with original entry ages of 6.57 and 6.59
  seconds. [Coverage evidence](PAPER_CAPACITY_20261114_PROOF.json).
  `54d8b93` measures request persistence, model admission, settlement,
  protection wait and the final review independently of the model call.
  `5cf21d1` commits an eligible option review with the native reservation.
  With the same 120 MB workload both CPU allocations still exceed the
  five-second entry target at 6.79 and 6.31 seconds.
  `e87ae5b` measures packet validation, repeat/new receipt handling, quote
  fills, cycle claiming and the durable trace start. One further 120 MB run
  opened at 5.59 seconds. Persisting the timing start took 0.46 seconds at p95.
  `875af6b` reads the original charge history once for a paid opening's native
  admission. Before repair it read the same records five times in one writer.
  A one-CPU repeat with the original limits opened at 6.68 seconds.
  On the month-grown account's next session at `8199a43`, the opening packet
  was 4.65 seconds old at cycle start. The ENTER reply had 0.674 seconds of
  validity left. Final review rejected the expired plan before reservation.
  `66d8ea4` times the original paid receipt check, mixed and Scope selection,
  and executable option book read. On a 120 MB two-slot run, saving the
  Scope choice took 0.330 seconds and the opening age was 6.72 seconds.
  Paid option reviews now save the clock used to assess the original plan.
  The session report shows the time remaining at the model reply and review.
  Seven new regression cases cover these clocks, including rejection at the
  exact deadline. All 211 related installed tests passed with networking disabled.
  The five-second entry-age target still needs a measured repair.
  `887b541` reads original charge history once for the option shortlist.
  Under the 120 MB one-CPU fixture, quote ages at reservation were 5.93
  seconds on the baseline, 6.68 in the selection-only trial, and 5.31 in
  the combined two-slot run. Each measured one opening and verified flat.
  `e2ced11` moves the verified feed-recovery read off the owner loop.
  On the same 123 MB account the longest delay to a ten-millisecond wakeup
  fell from 137 ms to 5.3 ms across eight polls per build. Four one-CPU
  opening trials measured 5.95 and 6.70 seconds on the baseline and
  5.53 and 6.78 on the repair. Each ended flat. The five-second opening
  target remains open. [Exact trials](PAPER_CAPACITY_20261114_PROOF.json).
  On `8447e50` the first approved quote was 6.28 seconds old, including
  5.68 seconds when a restore digest was running. The owner thread spent
  4.70 CPU seconds in fully contained digest calls. Ten of its calls came
  from recording tick and cycle timing. This result uses diagnostic
  padding and one approved opening.
  `9aeb3ea` compares the exact rescanned SQLite schema and rows with the
  preceding scan before reusing its SHA-256 prefix. Both retained account
  digests matched. Median warm verification fell from 254 to 95 ms on
  the 123 MB padded journal and from 297 to 192 ms on the 83 MB journal
  grown over 18 sampled sessions. The repair matched the original verifier
  in 1,152 comparisons. The two baseline 90-second runs admitted at 7.56
  and 7.97 seconds. The repaired short repeat admitted at 5.60 seconds,
  and the two-slot repeat admitted at 4.86 seconds. Another short run
  admitted at 4.89 seconds before the publisher failed its private copy.
  The one-CPU run with both repairs recorded one failed native acknowledgement
  with 1.76 seconds left at spawn start. It recovered the order and missed
  the second slot. The matched two-CPU run admitted at 5.91 seconds,
  evaluated both slots and finished flat. Average busy cores were 0.72
  and 0.83 over the respective 335-second windows. At 90 seconds two CPUs
  admitted at 4.76 seconds and finished flat. One CPU admitted at 4.75
  seconds and then hit the report and publisher copy errors described in A4.
  `88c9ba0` shows failed and interrupted local calls in
  the text report alongside the matched attempt and the actual fills.
  On the retained padded database, the timing table took 86% of a warm
  journal scan. On the unpadded 18-session account, Scope and mixed input
  tables were the largest intervals at 28% and 24%.
  On `2646944`, the 90- and 335-second one-CPU runs admitted at 4.995
  and 5.091 seconds. Each completed one round trip and verified flat.
  The two-slot run evaluated both opportunities and served every paired
  dashboard and report check. The five-second entry target remains open.
  [November 16 trials](PAPER_TIMING_20261116_PROOF.json).
  `6cb503d` stores the ordinary option selection with its paid reply. On
  copies of the same month-grown account, time from reply to final review
  fell from 0.778 to 0.455 seconds in the first comparison. `8b87749`
  reproduced all 66 original charges and reduced the median repeat history
  read from 56.8 to 7.0 ms. An expiry proven to precede native handoff
  now releases the reservation. A missing acknowledgement after handoff
  still records an uncertain attempt. The local acceptance worker on
  `365791d` uses its own transport thread and promptly delivers its exit
  status. The failed final replay reached review with 2.520 seconds left.
  The interval from dispatch entry to native launch used 1.216 seconds
  and left 0.089 seconds for acceptance. In the successful one-CPU repeat
  it used 0.884 seconds and left 0.945 seconds. In an earlier profiled
  dispatch that rejected its order, two journal integrity scans took
  0.526 of 0.535 seconds. A separate 90-second replay on the final build
  timed those scans around an eligible order. They used 0.533 of 0.799
  seconds in the opening check and 0.337 of 0.403 seconds in the exit
  check. That trade filled both ways and verified flat.
  [Recorded timing phases](PAPER_ENTRY_ACK_20261116_PROOF.json).
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
  The November 13 host rollout of `ab9b090` is confirmed. The following weekend,
  a diagnostic capture for November 16 observed a new schema and failed at
  VALIDATE_PLAN before any market reads. `aae1dff` admits the exact six reviewed
  description edits. Twelve baseline cases reproduced the rejection and 526 installed
  tests passed. The host then deployed `39d8e48` and completed eight real provider reads.
  Monday's preparation succeeded, followed by a failed dashboard publication.
  [Deployment receipt](PAPER_HOST_DEPLOYMENT_20261114.json).
  [November 14 evidence](PAPER_SCHEMA_REVISION_20261114_PROOF.json).
  On November 17 another provider description edit stopped all three context
  captures before market reads. `220da15` replaces the metadata-version allowlist
  with a fixed reviewed wire-contract fingerprint that excludes descriptions.
  It verifies original metadata hashes and accepts unseen description edits
  while rejecting changed tool permissions, argument rules and output rules.
  The old implementation has 30 reproduced failures. The repair passes 402
  focused checks and 620 installed system checks, with one cross-UID skip.
  Eight deployment rehearsals also passed after correcting Bash error handling
  in the operator block. Separate intermittent `daily-info` errors now report their
  module and exit code, with bounded daily-plan exception details. At 11:44 p.m.
  New York time, the operator captured Wednesday's catalog on the repair with
  eight provider calls and four candidates. Both `daily-info` checks passed;
  the scheduler and reader were updated to `220da15`, with the timer active
  and unpaused. The earlier intermittent error cause and a complete connected
  session remain unverified. Wednesday's preparation and launch review are
  scheduled for 9:00 and 10:00 a.m. New York time.
  [Incident and proof](PAPER_SCHEMA_CONTRACT_20261117_PROOF.json).
- [ ] **A4 — Independent protection:** prove that model waits, history work and
  display/report failures cannot improperly stop management of an owned position.
  Stock and option quote-fill tests now hold history, paid management advice
  and the failing publisher while a report snapshot is open. In the 120 MB
  run, native acknowledgements took 2.92 and 3.64 seconds from delivery of
  the stop book. Both ended flat. The option case took 5.14 seconds from
  setup through tick completion and missed its five-second bound.
  `f99a0ff` verifies the active order in the protective reservation transaction.
  A loaded repeat took 3.95 seconds from stop to option acknowledgement and
  5.53 seconds through completion. Both assets closed on the later book.
  `98f0b0d` separates contention setup and post-acknowledgement work. In
  `5761f48` a verified existing publication halt needs no additional native
  commit at the start of the protection tick. Its loaded stock and option
  cases finished in 3.78 and 4.21 seconds with verified flat accounting.
  A separate 73 MB option case sharing a CPU with another system suite
  acknowledged the breach in 4.51 seconds, completed in 5.99 seconds from
  the breach and filled on a later packet. The latency tail remains open.
  A new shared-CPU baseline reproduced the slow option exit at 5.56 seconds
  from the stop quote. On `887b541`, verifying a retained fill uses the
  original fingerprint function without initializing the trading engine in
  the exit worker. Stop-to-completion took 4.67 seconds for the option and
  4.59 for the stock. Both filled from a later quote before history or model
  advice returned. The installed system suite passed 562 cases with one
  unmapped-UID skip. [Measurements](PAPER_CAPACITY_20261114_PROOF.json).
  Five subsequent shared-CPU pairs all filled and verified flat. All ten
  native protective acknowledgements took 3.59 seconds or less from the
  stop quote. Nine of ten ticks finished within five seconds of that quote.
  Four of ten met the fixture's full five-second bound, including setup.
  In the last pair `7d63c74` observed the flat venue 2.40 seconds after
  the stock's next quote and 2.22 seconds after the option's next quote.
  In two matched stock/option pairs sharing one CPU with another test suite,
  `9aeb3ea` acknowledged all four stops in 3.38–3.65 seconds and completed
  the stop ticks in 4.62–4.98 seconds. Including contention setup, all four
  exceeded five seconds. Each filled from the next quote with advice and
  history still blocked. `0c46df3` releases its pinned read lock before
  a final incremental dashboard or report copy. Tests cover a quieting
  writer, repeated restarts, size growth and the original deadline.
  With both repairs, the stock and option stops were acknowledged in 3.26
  and 3.31 seconds. Their full cases took 4.87 and 5.26 seconds.
  In another short run a report timeout triggered fixture shutdown after
  the entry filled. The publisher also abandoned its released copy at
  the first writer restart. `2646944` lets that copy continue when it
  reaches new pages between restarts. Both real SQLite readers completed
  through two intervening commits, and all 15 deadline and lock cases
  passed. Persistent rewinds still release the reader early. In the final
  shared-CPU pair the stock and option acknowledged the stops in 3.18 and
  3.16 seconds. Both filled on the next quote before advice or history
  returned. Including setup, the cases took 4.94 and 4.91 seconds.
  [Protection measurements](PAPER_TIMING_20261116_PROOF.json).
  On `365791d` with 128 competing checks, the stock stop reached native
  acknowledgement in 3.35 seconds and the option stop in 2.86 seconds.
  The stock and option ticks finished in 4.46 and 4.23 seconds including
  contention setup. Both positions filled on the next quote while advice
  and history were still blocked. The subsequent flat-account observation
  took 1.80 and 1.89 seconds from that quote.
  [Loaded protection trials](PAPER_ENTRY_ACK_20261116_PROOF.json).
  On November 16 the host stopped before launch at dashboard publication.
  `fd7ff01` adds explicit stopped-host display recovery. The deployed
  release's three-step failure was reproduced offline. Both the prior
  accounting checkpoint and the failed display evidence survived recovery.
  A two-position fixture kept both positions and the original native
  account. The operator recovered the connected display at 10:30 p.m.
  New York time on November 16 and installed `fd7ff01` for the scheduler
  and reader. The timer is active. The next connected evidence is the
  next preparation, launch review and session outcome. November 17 stopped in
  capture before a session receipt or worker was created.
  [Host observations and tests](PAPER_SNAPSHOT_RECOVERY_20261116.json).
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
  In `0d79a3a` the same overlap on a fenced 72,814,592-byte journal produced one
  protective exit in 3.37 seconds with verified flat accounting. Injected journal
  failures also cover partial Scope/mixed acceptance and partial delivery/slot
  claims. [Loaded protection evidence](PAPER_LOADED_HANDOFF_20261114_PROOF.json).
  Sustained full-duration resource-profile proof remains under A6. Unverified
  startup exposure retains its authority/accounting rejection boundary.
  At 119,623,680 bytes the combined blockage case submitted the stock exit
  in 4.53 seconds on one CPU. The final account was verified flat. A native
  snapshot crossed by a paid model charge now requests fresh reconciliation.
  The regression preserves the settled charge and keeps the owner running.
  On `42648c6` the same contention test submitted the exit in 4.10 seconds.
  [Protection and accounting evidence](PAPER_CAPACITY_20261114_PROOF.json).
  `0349f38` and `4329383` recheck the running clock after local receipt,
  snapshot and reservation waits. A stale quote cannot fill an order and a
  new executable quote can close an earlier unattempted rejection. An actual
  held-position exit completed in 3.61 seconds under the 120 MB contention
  fixture. Two simultaneous stops recovered independently on fresh books.
- [ ] **A5 — Failure/restart matrix:** exercise every condition in A's matrix;
  preserve accounting, unknown outcomes and bounded recovery without duplicates.
- [ ] **A6 — Duration and capacity:** pass accelerated calendar/multi-day cases
  and a full configured-duration wall-clock soak under the host resource profile,
  including journal growth; identify any residual host-only restriction tests.
  The [November 12 preflight](PAPER_DURATION_CAPACITY.md) passed the small-journal
  lifecycle and exposed a 73 MB dispatch timeout. `0d79a3a` passes that short
  loaded preflight and a two-slot run with the same original limits and restore
  fence. The second slot recorded `ENTRY_MODEL_RISK_PAUSE`. The full
  21,480-second wall-clock test started on that build. The accelerated calendar
  completed 22 trading sessions, including the early close, on one continuing
  owner with eight sampled packets per session. The denser replay and nominal
  duration measurement are recorded in the current capacity evidence.
  The first normal-speed session after 1,738 retained packets missed one of
  two slots. A read-only reproduction found repeated forced revalidation on
  the 65th paid receipt. `8199a43` verified that display five times within
  the original two-second observer bound.
  Its repeat on a 22-session account evaluated both slots and published through
  shutdown, with 31 new packets and verified flat accounting. It failed the
  known-trigger lifecycle because the first slot's plan expired before reservation.
  The full-duration `0d79a3a` baseline finished with 25 of 72 evaluated
  slots and verified flat accounting. It allowed zero feed recoveries.
  With the daily allowance of two, a 335-second comparison on `77a0118`
  evaluated both slots and completed a round trip. The opening quote was
  7.02 seconds old. A full day on that implementation remains unverified.
  The zero-recovery 135-minute repeat on `9710cce` evaluated 27 of 27 slots
  and verified flat. Its 263 paired dashboard/report reads and 2,983 native
  snapshot reads succeeded through shutdown.
  The later 358-minute attempt stopped after 44 minutes 51 seconds with
  nine completed cycles. Its last report recorded one round trip. A separate
  replay stopped after 18 sessions. Neither checkpoint proves completion.
  The `0c46df3` application subsequently completed all 22 exchange sessions
  with eight sampled packets per session on one owner and verified the
  original journal authority after each session.
  The denser replay used an intermediate restore build. It delivered 1,738
  packets across 22 sessions. Its next 335-second session published and
  evaluated both slots. The first plan had 0.403 seconds left at reply and
  expired 0.723 seconds before its final review. The expected round trip
  was missed. In that cycle, persisting the settled model result took 0.610
  seconds and Scope selection took 0.457 seconds. The total time from reply
  to review was 1.126 seconds. The final application verified the same
  authority and flat accounting at packet 1,769 using read-only access.
  [Session and timing evidence](PAPER_TIMING_20261116_PROOF.json).
  On separate copies of that stopped account, the next synthetic session
  on `365791d` evaluated one of two slots with zero fills on the first
  one-CPU run. The one-CPU repeat and two-CPU run each evaluated both
  slots and completed one round trip. Opening quote ages in trial order
  were 7.924, 7.656 and 7.736 seconds. The separate 119.6 MB padded
  one-CPU run evaluated both slots, completed a round trip and served all
  11 paired dashboard and report reads. Its opening age was 5.308 seconds.
  Full 358-minute coverage on this build remains unverified.
  [Account replays and capacity comparison](PAPER_ENTRY_ACK_20261116_PROOF.json).
  The short tests use labeled padding and sampled aggregate RSS. Host cgroup
  enforcement and connected-session effectiveness still require separate evidence.
  [Short loaded runs](PAPER_LOADED_HANDOFF_20261114_PROOF.json). [Current capacity evidence](PAPER_CAPACITY_20261114_PROOF.json).

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
