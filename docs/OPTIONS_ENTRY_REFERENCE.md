# Fill-bound target stop reference

New PAPER owners can explicitly freeze
`target_entry_reference="fill-weighted-underlying-v1"`, together with v2 target
milestones, whole-contract partial closes and frozen target stops. The first
milestone can then specify `tighten_to_entry="fill-weighted-underlying-v1"`
instead of a fixed `tighten_underlying_to` price. Both fields cannot coexist.
Old cohorts cannot add this enrollment on reopen; preparation, dispatch and
reconciliation enforce it, and portable accounting checks the owner policy.

## Rule and source boundary

The pinned SignalFlow `play_management.target_stop_price()` at
`f9eaf2c1b5d13dca287ee7138126883065b00395` moves the stop to its underlying entry
reference at T1, to T1 at T2 and to T2 at T3, independently of scale allocations.
It does not define a partial-fill reference for our native receipt model.

Our explicit execution adaptation uses the quantity-weighted mean of the actual
entry fills' observed CALL asks or PUT bids. It requires every originally approved
contract to fill and every fill to retain a valid underlying observation. No setup,
approval, later management quote or midpoint substitutes for missing evidence.
Each observed price must lie strictly between the original stop and first target;
an average cannot hide an individual fill observed outside that geometry.

Weighting uses exact rational arithmetic. The final reference rounds toward tighter
protection at twelve decimal places: upward for CALL, downward for PUT. Ambient
Decimal settings cannot change the result. Unrepresentable output remains blocked.
This is an observed underlying reference bound to option fills, **not an underlying
transaction price or an option/net-profit breakeven guarantee**. Fees and every
entry/management charge remain separately accounted for.

Only the first v2 milestone can name this dynamic reference. A subsequent fixed
stop must be at least as tight as the first objective and remain strictly behind
its own objective. Later fixed stops must tighten further. This permits the sourced
T2-to-T1 rule while preventing a later fixed price from loosening an initially
unknown entry-bound stop. All original target prices and quantities stay frozen.

```python
TargetExitSchedule(
    version="frozen-target-milestones-v2",
    entry_quantity=1,
    steps=(
        TargetExitStep(underlying_price="602", quantity=0,
                       tighten_to_entry="fill-weighted-underlying-v1"),
        TargetExitStep(underlying_price="604", quantity=1,
                       tighten_underlying_to="602"),
    ),
)
```

These prices illustrate the contract; the engine does not generate strategy targets.

## Native ownership and protection

The original buy's `entry_underlying_reference` retains approved quantity and one
sample per verified entry fill: fill ID, complete receipt hash, quantity and the
observed directional reference, or explicit missing data. Reconciliation rebuilds
it from complete native fill history and checks the venue and prior owned prefix.
Partial sales preserve the original samples and original quantity. They cannot
change the reference to the remaining lots or a favorable later price.

A fresh target observation can latch while entry fills are incomplete or the option
quote is unusable. Once all required evidence exists and ordinary supervision is
usable, protection applies the tighter stop and checks the current quote for a
rebound immediately. A prior tighter stop is never relaxed. Target touches alone
create neither fills nor sale proceeds.

Missing evidence, out-of-geometry observations, numeric failures and terminal
partial entries leave the reference blocked. They block target-driven sales and
ordinary partial-close requests, without creating a global halt merely because
entry fills are still completing. Original invalidation, premium catastrophe,
time/expiry protection, independent tighter stops and full owned closes retain
their existing authority. A later fixed target stop can still tighten protection.
Already attempted orders keep their reservations; missing reference evidence is
not permission to cancel or resubmit an order.

The stored supervision result reports coverage, readiness, reasons and the reference
hash. The observer verifies saved samples against the original fill table and
observation before displaying the historical reference; it does not refresh data
or grant authority. Native export and portable accounting retain the original basis
through open runners. Altered exported samples fail ownership replay. Open positions
remain economically inconclusive, with no invented valuation or free model calls.

## Scope management v2

New research books may freeze `ScopeManagementPolicy(version="scope-management-plan-v2", ...)`.
For quantities one through three, the factory retains both locked Scope objectives:

| Contracts | T1 sale | T1 protection | T2 sale | T2 protection | Runner |
| --- | ---: | --- | ---: | --- | ---: |
| 1 | 0 | Fill-bound entry reference | 1 | Locked T1 | 0 |
| 2 | 1 | Fill-bound entry reference | 0 | Locked T1 | 1 |
| 3 | 1 | Fill-bound entry reference | 1 | Locked T1 | 1 |

No entry price is populated in the preview. The marker is resolved only by the
separately enrolled native engine using actual receipts. The existing v1 preview
retains its original positive-sale steps and encoding. Existing research books
cannot change management versions on reopen. Stored observer output and portable
Scope replay reproduce the exact versioned plan and original admission costs.

Four contracts still require an unspecified T3 and remain blocked with their exact
source allocation. Scope research reviews retain `native_execution_ready=false`;
the native entry guard remains enforced. Watch/order linkage, family loss/reset,
complete path requirements and Scope runtime/replay enrollment are still required.
This slice closes the shared entry-reference stop and Scope milestone-plan dependency,
not the entire Scope trading integration.

Installed fixture tests cover both directions, weighting/rounding, stop-only
milestones, scales/runners, rebound/restart, incomplete entry evidence, enrollment,
atomic rollback, independent accounts, stored verification and portable replay.
All entry/management costs and unknown-cost treatment remain intact. Authentic
provider, host, final UI/data and prospective economics remain separate gates.
Main untouched, PR #1 draft, LIVE disabled and deployed experiment frozen.

See [fill observations](OPTIONS_FILL_UNDERLYING.md), [targets](OPTIONS_TARGET_EXITS.md),
[Scope plans](OPTIONS_SCOPE_MANAGEMENT.md) and [status](SLICE2_STATUS.md).
