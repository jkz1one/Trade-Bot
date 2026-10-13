# Scope owned account admission review

`ScopeWatchBook.review_admission(...)` now stores an account-aware sizing review
for a new explicitly enrolled research watch. It refreshes the arming hold and
uses the existing `admit_option` governor. It creates no order, reservation,
execution decision or model request; `authority` and `live_enabled` remain false.
Native Scope dispatch and filled-position lifecycle integration remain open.

## Frozen enrollment and evidence

`ScopeWatchPolicy.admission` requires both arming and contract-profile policies.
`ScopeAdmissionPolicy.max_entry_debit` is an explicit positive cap no greater than
$500, the pinned Scope research baseline. The owner's stricter limits still win.
Older cohorts omit the optional field and cannot add it on reopen.

Call `review_admission(key, play_key, expected_revision=..., now=..., frame=...,
context=..., underlying=...)` with current supplied evidence. It advances the
sampled hold itself, so callers do not first submit the same sample to
`observe_arming()`. Reusing source timestamps cannot create fresh arming evidence.
An unfinished hold is retained as `HOLDING` with a blocked review and no sizing.

The method reads reconciled account state from the same owner and journal inside
the fenced transaction. Callers cannot supply balances, remaining loss allowance,
quantity, a replacement contract/stop or an alternative session. Existing native
activity still blocks this research watch version; no traded account is silently
classified as unfilled.

After fresh quality/contract/arming checks pass, the current underlying quote must
also be before the locked first objective. A CALL ask at/above it or PUT bid
at/below it resets the hold. The common governor checks source, freshness,
synchronization and invalidation against current executable underlying evidence.
Missing, wrong or stale evidence cannot use the old completed close as a substitute.

## Common sizing and calendar restrictions

The proposal uses the original exact contract and invalidation, the explicit
Scope debit ceiling and a deterministic setup description. The common governor
applies every existing account and quote gate, including:

- Full-premium risk, settled/unreserved cash, daily and total loss allowance,
  existing positions/orders, unsupported exposure, supervision and entry halts.
- Available ask size, maximum contracts, account exposure and debit ceilings.
- Slippage rounded against the trader to the contract's correct tick tier.
- Entry fees and reserved exit fees. The owner's effective limits reserve a
  separate exit-order fee for every contract, matching partial-exit protection.

There is no parallel Scope sizing formula. Original and effective limits, account
snapshot, proposal, session and full governor result are retained. Existing cost
accounting remains authoritative: all recorded entry/management costs reduce
available budgets and unknown costs cannot become zero. This slice does not
relax the watch's native-activity restriction to authorize paid model/trade history.

The owner still uses its existing regular-session calendar. Scope's explicit
reviewed index session is retained separately. The sizing window is their
intersection: the later entry start, earlier entry cutoff and earlier close/
Scope protection time. An absent or empty owner window blocks review. The owner's
calendar never substitutes for missing Scope evidence or extends Scope's hours.
This conservative offline intersection is not authentic SPXW calendar acceptance.

A successful governor result's deadline is further shortened to the arming
sample's validity. `eligible=true` means the offline result passed at the recorded
time, not that a later dispatcher may trust it. All evidence must be freshly
reviewed again when native dispatch is eventually implemented.

## Persistence and boundaries

Fresh-evidence failures persist a reset and a blocked review. Governor rejections
also reset the hold. Hold progress, price termination, sizing evidence, action
receipt and audit event commit together. A write failure rolls back all of them.
Identical action retries return their original historical receipt; current stored
state comes from `snapshot()`. Reads never refresh or approve old evidence.

A rejected or successful review does not consume another called play or change
cash, cost records, fills or account reservations. Independent accounts remain
independent. Native order/position linkage, full-cost loss/cooldown/reset controls,
complete obstruction coverage, Scope runtime/replay/observer and authentic
provider/model/calendar/host acceptance remain open. Convexity remains blocked
without complete path evidence.

See [contract profiles](OPTIONS_SCOPE_CONTRACTS.md), [arming](OPTIONS_SCOPE_ARMING.md),
[watch lifecycle](OPTIONS_SCOPE_WATCHES.md) and [status](SLICE2_STATUS.md).
Main untouched, PR #1 draft, LIVE disabled and deployed experiment frozen.

## Native execution boundary

The common engine now enforces this research-only boundary at both `prepare()`
and dispatch. If the Scope watch-policy table exists, `OPEN_LONG` is rejected with
`SCOPE_NATIVE_EXECUTION_NOT_ENROLLED`. An eligible stored sizing result, an admission
ceiling, a different source key, or absence of a currently active watch cannot
bypass it. An incomplete/empty enrollment table also fails closed. The guard does
not parse a caller-supplied policy or offer a configuration switch to enable orders.

Preparation retains the normal rejected native decision/audit receipt and creates
no order or reservation. As with any native decision, that history then prevents
further research-watch mutations under the existing native-activity restriction.
Use the watch APIs for research; a rejected native entry is not a watch action.
Historical preparation retries retain their receipts, but dispatch rechecks the
boundary before any attempt/worker. A blocked prepared buy becomes `REJECTED`,
releases its active order lock and records the dispatch reason without an attempt.

HOLD and owned CLOSE actions remain available through their existing rules,
including protective exits in a legacy/inconsistent journal. Already-attempted
orders retain the engine's existing observation/reconciliation workflow. This
change does not cancel broker orders or infer missing fills. Accounts without a
Scope enrollment table retain existing Degen/Swing behavior. Native Scope linkage
and its filled-position/full-cost loss controls must be implemented before this
boundary can be replaced by a governed entry path.
