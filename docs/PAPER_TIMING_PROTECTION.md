# Runtime timing and publication-failure isolation

This continues delivery-plan A2 and A4 after the recovered A1 implementation
`29ef510`. All examples and retained runs here are isolated synthetic PAPER
fixtures. The operator subsequently deployed `39d8e48`. The November 14 timing
work ran in disposable PAPER environments.
[Host receipt](PAPER_HOST_DEPLOYMENT_20261114.json).

## Timing contract

Runtime ticks and strategy cycles retain separate monotonic traces, bound to the
native generation and, when available, the exact packet sequence/hash and cycle
slot. A cycle has its own asynchronous context; a waiting entry model does not
absorb timings from concurrently running position protection. Packet sequences
are collector attempt sequences. The session reporter checks the retained native
packet hash and joins recent traces to the collector's delivered attempt/hash.

The trace measures protection, native snapshot/accept calls, common option and
stock scans, Scope admission scanning and quality review, the shared entry-model
wait, paid stock/Scope refresh waits, option/stock admission and dispatch, and
option/stock/portfolio management-model waits. The management spans cover the
model await only; receipt validation, cost settlement and native execution remain
separate. Refresh spans include the actual selected callback, including the
collector-backed Scope refresh when enrolled. Native parent/child progress
is retained for success, timeout and cancellation. Overall native-call durations
include cleanup; the child diagnostic freezes the parent's observation before
cleanup. Child intervals use adjacent observed markers only. An unobserved stalled
tail is not invented. Nested phase durations overlap and must not be summed.

Option and stock admission/dispatch diagnostics preserve original quote age, source-to-receive
lag and receive-to-evaluation age separately. Negative/future clock differences
remain visible; diagnostics never make a quote admissible. Packet age is measured
at the tick/cycle evaluation time, not a claimed network latency or fill time.

`execution_runtime_timings` is an additive diagnostic table. It does not emit
accounting events or change market packets or execution policy. Enrolled restore
fences still hash every execution table, including diagnostics; that integrity
work and its cost are unchanged.
A start record precedes the work, and completion/failure/cancellation updates it.
An unfinished start remains incomplete evidence. Diagnostic SQLite/I/O failure
does not authorize an entry or stop otherwise valid protection. Native slot/model
commitments supply independent denominators even when
no timing record was saved. Reports separate unmatched commitments, unmatched
trace keys, duplicate trace keys, skipped/waiting slots and unsettled model costs.
Interrupted slots are counted conservatively; this does not assert that every
interrupted slot reached a model. Work before any native commitment remains
unobservable. Actual child-process exits test both absent and unfinished traces.

Each trace retains at most 64 spans and 64 native diagnostics; excess span counts
and excess native-diagnostic counts are explicit. Reports inspect at most the
latest 20,000 records and 64 MiB of payload in the selected window, retaining
total, measured, unfinished/invalid and omitted counts. Unmatched commitments
can include uninspected or window-boundary traces; they are not all labeled crashes.
Phase p50/p95/p99/max values describe those measured records, including failed calls.
Recent correlation details are limited to 25 traces. Display snapshots copy only
the latest 100 diagnostic rows; the native ledger is not pruned.

Collector traces include HISTORY_PLAN, HISTORY_VALIDATE and HISTORY_BINDING.
Runtime traces also report scheduler wakeup delay beyond the configured inter-tick
wait; total tick duration is retained separately. These are observations, not
changed process deadlines or faster freshness clocks.

Paid-entry traces also time the mixed-family choice, the original Scope
receipt check, the selection record and the read of the executable option
book. The Scope selection span includes persistence of the choice. When the
model chooses Scope, its market refresh has its own span before that record.
An ordinary model HOLD ends before these phases.

A2 still requires the full-session timing/capacity profile under A6. Synthetic
timings are workspace observations, not Robinhood
latency measurements or proof of Tuesday's exact native timeout cause.

## Publication failure with held positions

An in-run publisher exception now records a sanitized native incident and latches
`CONNECTED_PUBLICATION_FAILED` as an entry fault. It fences automatic feed
recovery and prevents a later model result or healthy quote from resuming entries.
The publisher is not retried, and any partial display copy remains available for
inspection. The single original runtime owner and collector continue until the
original stop condition or another fatal component failure.

The display fault is separate from invalid market evidence. Original valid quotes
still pass through native simulated fills, reconciliation and protective exits.
Missing or invalid data retains its existing rejection behavior. No successful
exit, flat state or fresh quote is inferred from publication failure. Failure to
persist the native entry fence remains fatal; protection cannot continue without
durable execution authority.

The session report reads the incident from the native journal independently of
the failed display. The existing operating-status publisher can show the failure
while account publication is unavailable. At shutdown the worker reports failure,
even if protection completed, preserving the controller's review requirement.
No message is sent to an external alert destination.

The new coordinated fixture fails the publisher with SPY and QQQ already held.
It checks the entry fence, continued SPY protective exit, a stopped restart with
QQQ still held, and QQQ's eventual exit without another entry-model request.
It retains failure reporting and verified final accounting. Separate tests retain
native timeout/cancellation cleanup and concurrent timing-context isolation.

## Startup display failures

A missing completed display or a retained partial publication no longer blocks
protection of verified native holdings. Read-only preflight requires the original
source alias, exact display binding and reader identity, private publisher lock,
and a complete native portfolio whose original receipts reproduce its cash and
held positions. It does not infer holdings from a failed display or pending order.
Missing enrollment, a flat account, changed identity, incomplete reconciliation
or inconsistent accounting still fail before opening a runtime.

The runtime repeats this verification under its original owner lease, durably
records a STARTUP publication incident and latches the entry fault before starting
the loops. It never constructs or retries the damaged publisher on that path.
Valid native data can still reconcile fills and trigger protective exits. The
worker ends with an explicit publisher failure even after a successful exit.
The display is not deleted, replaced or silently repaired.

The read-only `connected_runtime check` and host review expose `PROTECTION_ONLY`
with the exact snapshot binding. The host review hashes that startup mode and
rejects `--resume-flat` or automatic feed-recovery allowances for it. The ordinary
daily launcher still requires its reviewed flat startup; this is not an automatic
held-account recovery, deployment or schedule change.

Two coordinated restart fixtures retain QQQ after SPY exits, then remove the
completed display or leave a partial copy. Both require QQQ's protective exit,
two total entry-model calls, reconciled final accounting, independent failure
status and byte-for-byte preservation of the damaged display. The installed
baseline fails before that second runtime starts. Guard cases separately reject
changed bindings/readers, missing enrollment/lock, flat or unreconciled accounts
and cash discrepancies.

A concurrent stock-management fixture also combines a pending paid model result
with the publication fault. A separate protection tick dispatches the exit before
the model returns, the known model cost is still retained, and no second exit is
submitted. Timing assertions keep that dispatch outside the model's cycle trace.

## History and display/report contention

History planning, original snapshot validation, binding reconstruction and
normalization run outside the protection event loop. SQLite history readers use
separate read-only connections; the original collector connection remains the
sole writer. Derived bindings retain exact original payload/hash equality and
their original creation time. A capture guard excludes overlap before the durable
attempt exists. Repeated cancellation drains background work before releasing
its owner; validation failures still reject changed originals.

Publication and standalone session reports use the same standard-library
SQLite copier. Its normal path releases native read locks between 64-page
steps. If commits repeatedly restart the backup, one retry holds a consistent
read transaction for up to 0.5 seconds within the existing five-second total.
Both paths enforce the 512 MiB source-copy limit. The final dashboard projection
still enforces its 64 MiB limit and durable commit. Each report database has
its own consistent cutoff. Packet and hash checks correlate the two sources.

An ordinary failure removes the private source copy. The publisher retains
the previous completed display and the failed `.pending.db` for inspection.
A dashboard HTTP reader checks file identity around receipt and accounting
verification. It may retry one observed atomic replacement. Corrupt or
repeated replacements remain unavailable.

The 120 MB contention fixture records setup, fresh stop to native
acknowledgement, and acknowledgement to tick completion. Its five-second
assertion includes all three intervals. Run the loaded stock and option cases
with `TRADE_BOT_PROTECTION_DENSITY=extended` for the 112 MiB diagnostic seed.
The following eligible packet must fill the submitted exit during the blocked
management and history calls. See the [November results](PAPER_DURATION_CAPACITY.md).

Three baseline tests demonstrate event-loop blockage and native SQLite write-lock
contention before repair. The combined installed test overlaps real history binding,
pending management advice, paused then failed display projection and an open report
snapshot against the same original native owner. Its exit submits in 1.47 seconds
on one logical CPU, completes while advice/history remain pending, then retains
known model costs and verified flat accounting without a duplicate exit. Separate
tests retain original-source tamper rejection, cancellation/lease drainage, read-only
report consistency, deadline/capacity cleanup and the existing >64 MiB journal case.

A4 remains open for sustained full-duration resource-profile proof under A6 and
startup exposure outside the verified-held boundary. The short one-CPU tests and
per-process RSS observations do not establish host memory limits, projected-month
growth, full-session deadlines or actual host acceptance.

## Release boundaries

The recovered A1 proof remains immutable in PAPER_SYSTEM_CHECK_PROOF.json.
The continuation's installed identity, failures/corrections and final results are
recorded in [PAPER_TIMING_PROTECTION_PROOF.json](PAPER_TIMING_PROTECTION_PROOF.json).
The startup/phase continuation is recorded in
[PAPER_STARTUP_PROTECTION_PROOF.json](PAPER_STARTUP_PROTECTION_PROOF.json).
The contention continuation is recorded in
[PAPER_CONTENTION_PROOF.json](PAPER_CONTENTION_PROOF.json). The same system-check
command also exercises all five coordinated scenarios, history/binding/feed
regressions, stock/Scope/management timing, contention, host review and snapshot guards.

The new diagnostic table is accepted by this release and bounded in display
copies. Older releases with a strict table allowlist cannot reopen that upgraded
native journal unchanged. D2 must review rollback compatibility before any host
upgrade; deleting diagnostic/account history is not an automatic rollback step.

Connected account identity, enrollment, balances, positions, original journals,
halts, eight catalog slots, $1,000 initial capital, two plays, $1/day and $5 total
AI limits are unchanged by this development work. LIVE remains disabled. Full
host-duration soak, cross-UID/Docker/systemd and browser acceptance, original
Swing/Scope inputs and a connected entry-to-exit lifecycle remain separate gates.
