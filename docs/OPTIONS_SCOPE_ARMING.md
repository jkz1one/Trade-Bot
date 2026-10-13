# Scope sampled arming hold

`ScopeWatchPolicy.arming` explicitly enrolls a new research cohort in a durable
hold check. It requires the matching frozen quality policy. Absent fields remain
omitted from old policy serialization; an existing cohort cannot enable this on
reopen. Independent A/B/C/D accounts, all entry and management costs and native
Degen/Swing execution remain unchanged.

`ScopeArmingPolicy` requires `confirmation_hold_seconds` from 60 to 600 and
`max_sample_gap_seconds` from 1 to 10. The pinned
[SignalFlow policy](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard_policy.py)
sets a 60-second default and permits 0–600. This adaptation deliberately requires
at least that baseline. Bounded sampling and durable evidence are conservative
research additions, not claims of identical source runtime behavior.

## Observations and continuity

`book.observe_arming(key, play_key, expected_revision=..., now=..., frame=...,
context=...)` records one supplied observation under the existing owner lease,
transaction, revision and restore fence. The watch must still be active and the
owner fresh, reconciled, supervised, funded and free of global entry/loss blocks.
No provider polling, model invocation or order creation occurs.

Each passing sample reruns complete context and quality review. It preserves the
original instrument, session, selected pattern/parent/right, exact geometry,
matched anchor and prior-session evidence. All previously reviewed bars must
remain unchanged. New completed bars pass the same chronological invalidation
and consumed-second-objective checks used by `advance()`. A crossing terminates
the unfilled watch and releases its active lock atomically. A changed setup cannot
silently move the original target or stop to maintain a hold.

Every current source clock must strictly advance after the previous accepted
sample: all nine evidence groups, three histories, metadata, option quote and five
current typed context streams. Receipt-only refreshes do not count. Historical
prior-session evidence is locked instead of requiring it to acquire a new timestamp.
Unchanged completed bar values are allowed with fresh observations of that history.
This does not fabricate unfinished bars or authenticate a provider's timestamps.

The first passing sample starts `HOLDING`; the initial call contributes no elapsed
time. Subsequent samples continue the interval only through the preceding
`valid_until`. That endpoint is bounded by the sampling gap, source age limits,
flow/news/event validity and entry cutoff. A gap starts a new hold with count one.
At the exact configured duration a passing sequence records `ARMED`. Sampling must
continue to extend that dated result. Explicit `advance()` resets the hold because
it does not supply current quality context.

Missing, stale or failing evidence and owner-readiness blocks commit a `RESET`,
with no retained start time or arming permission. Full supplied inputs, available
quality scan, reasons, source-clock watermarks and timing remain auditable through
records, action receipts and events. A later recovery starts a new interval.
Malformed inputs, wrong revisions, conflicting keys, closed owners or native
execution history reject the request without mutation. They never refresh the
previous sample. Identical action retries return their original historical receipt.

## Meaning and limits

The nested arming state is research evidence only. The top-level watch remains
`WATCHING` until price termination or explicit expiry. `authority` and
`live_enabled` remain false. `snapshot()` returns stored, dated evidence and does
not silently refresh, expire or authorize it. Consumers must not treat a historical
`ARMED` label as a current entry entitlement.

Sampling establishes passing observations at bounded intervals, not an unbroken
intrabar price path. Completed-bar checks cannot prove that no crossing happened
inside an unfinished bar. Complete obstruction coverage, intrabar/live acceptance,
contract-profile admission, native position/full-cost loss attribution, cooldowns,
Scope execution/runtime/replay and observer integration remain separate work.
The existing native-activity guard remains in force, so this watch cannot claim a
traded position was unfilled. No cost or loss is inferred from watch classifications.

See [watch lifecycle](OPTIONS_SCOPE_WATCHES.md), [quality review](OPTIONS_SCOPE_QUALITY.md)
and [current proof/status](SLICE2_STATUS.md). Main stays untouched, PR #1 draft,
LIVE disabled and the deployed experiment frozen.
