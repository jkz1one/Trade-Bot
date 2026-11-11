# Runtime timing and publication-failure isolation

This continues delivery-plan A2 and A4 after the recovered A1 implementation
`29ef510`. All examples and retained runs here are isolated synthetic PAPER
fixtures. The confirmed host remains d2046f6; no deployment, schedule change,
account recovery or market capture is requested.

## Timing contract

Runtime ticks and strategy cycles retain separate monotonic traces, bound to the
native generation and, when available, the exact packet sequence/hash and cycle
slot. A cycle has its own asynchronous context; a waiting entry model does not
absorb timings from concurrently running position protection. Packet sequences
are collector attempt sequences. The session reporter checks the retained native
packet hash and joins recent traces to the collector's delivered attempt/hash.

The trace measures protection, native snapshot/accept calls, the common option
scan, entry-model wait, option admission and dispatch. Native parent/child progress
is retained for success, timeout and cancellation. Overall native-call durations
include cleanup; the child diagnostic freezes the parent's observation before
cleanup. Child intervals use adjacent observed markers only. An unobserved stalled
tail is not invented. Nested phase durations overlap and must not be summed.

Admission and dispatch diagnostics preserve original quote age, source-to-receive
lag and receive-to-evaluation age separately. Negative/future clock differences
remain visible; diagnostics never make a quote admissible. Packet age is measured
at the tick/cycle evaluation time, not a claimed network latency or fill time.

`execution_runtime_timings` is an additive diagnostic table. It does not emit
accounting events, change market packets or participate in execution authority.
A start record precedes the work, and completion/failure/cancellation updates it.
An unfinished start remains incomplete evidence. Diagnostic SQLite/I/O failure
does not authorize an entry or stop otherwise valid protection. A failure before
the start record is written cannot be counted from that table alone.

Each trace retains at most 64 spans and 64 native diagnostics; excess span counts
are explicit. Reports inspect at most the latest 2,000 records in the selected
window, retaining total, measured, unfinished/invalid and omitted counts. Phase
p50/p95/p99/max values describe those measured records, including failed calls.
Recent correlation details are limited to 25 traces. Display snapshots copy only
the latest 100 diagnostic rows; the native ledger is not pruned.

This does not complete A2. Dedicated stock/Scope/management-model phase coverage,
complete killed-before-record denominators and the full-session timing/capacity
profile remain open. Synthetic timings are workspace observations, not Robinhood
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

A4 remains open for the full failure matrix, including dashboard startup failures,
combined prolonged history/model/report stress and resource-constrained sustained
operation. Existing publisher enrollment checks still fail before worker startup;
this slice isolates failures during an already running session.

## Release boundaries

The recovered A1 proof remains immutable in PAPER_SYSTEM_CHECK_PROOF.json.
The continuation's installed identity, failures/corrections and final results are
recorded in [PAPER_TIMING_PROTECTION_PROOF.json](PAPER_TIMING_PROTECTION_PROOF.json).
The same paper-system-check command now also exercises runtime timing and the
held-position publication-failure case.

The new diagnostic table is accepted by this release and bounded in display
copies. Older releases with a strict table allowlist cannot reopen that upgraded
native journal unchanged. D2 must review rollback compatibility before any host
upgrade; deleting diagnostic/account history is not an automatic rollback step.

Connected account identity, enrollment, balances, positions, original journals,
halts, eight catalog slots, $1,000 initial capital, two plays, $1/day and $5 total
AI limits are unchanged by this development work. LIVE remains disabled. Full
host-duration soak, cross-UID/Docker/systemd and browser acceptance, original
Swing/Scope inputs and a connected entry-to-exit lifecycle remain separate gates.
