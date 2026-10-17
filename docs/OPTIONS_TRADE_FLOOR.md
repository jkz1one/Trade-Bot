# Native whole-trade floors

`OptionObserver(journal, population_id).trade_floor(entry_client_id)` reads a
bounded native snapshot and returns cost-aware whole-trade floor **previews**.
It supplies the arithmetic used by the separately enrolled automatic owner policy.
Reads neither enroll a policy nor evaluate quotes, latch an exit,
submit an order, refresh evidence or attach an execution owner.

The fixed `native-target-floor-preview-v1` reference adapts the 0%, 10% and 25%
whole-trade floors in pinned SignalFlow
[`play_management.py`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_management.py).
That source's original calculation uses realized sale P&L without fees or model
charges. This preview uses native actual premiums and costs. Reference stages do
not create Scope objectives or authorize a new management policy.

## Exact cash requirement

For each reference fraction `r`, the required remaining gross sale proceeds are:

```text
max(0, original entry premium × (1 + r)
       + actual execution fees + attributable entry/management charges
       + remaining exit-fee reserve − actual sale proceeds)
```

Original premium comes from all fills of the exact fully completed native entry.
Partial sales never rebase it onto remaining FIFO lots. Only verified linked fills
contribute sale proceeds. A target touch, prepared order or model proposal contributes
no proceeds. Every actual entry and exit fee stays included, including extra fees
from separate scale orders. Attributable MAINTAIN/TIGHTEN/rejected advice remains
charged even if it creates no order. Unknown or unallocated model costs suppress
the preview, retaining their evidence rather than treating them as zero.

The future exit reserve is remaining contracts multiplied by the frozen per-contract
plus per-order exit fee. This assumes at most one charged filled order per remaining
whole contract, avoiding an optimistic single-order fee assumption for a thin runner.
Actual fees already paid are separate from this reserve. Future model calls can
raise the requirement; no unrecorded future charge is claimed to be included.

`minimum_exit_fill_price` divides the required proceeds by actual remaining
quantity and contract multiplier, then rounds **up** to the contract's price ticks,
including the tier change at $3. It is a hypothetical actual fill-price threshold,
not a bid trigger or proposed limit. Native slippage may make a fill lower than its
observed bid; this API does not convert the threshold into a quote or execution
decision. If actual sale proceeds already cover the requirement and reserve, both
required proceeds and minimum fill price are zero, with `covered_by_recorded_sales`
true. The remaining position is still owned and has no completed trade outcome.

Data/host costs remain in the full-cost session report and are explicitly excluded
here. These thresholds therefore do not establish all-in breakeven, profitability
or a guaranteed exit.

## Evidence, uncertainty and authority

The preview reuses [native position outcomes](OPTIONS_POSITION_OUTCOME.md), including
exact proposal/approval/fill links, replayed settlement/accounting, cash, holdings,
known and unknown model charges. It carries the complete outcome evidence, its
hash, frozen configuration hash, audit revision, last event time and a separate
account-snapshot time. A dated stored result is not a fresh valuation.

The requested entry must still be owned, fully filled and have no unresolved linked
order. A working partial scale suppresses the floor until terminal reconciliation;
terminal partial entries cannot resize the original reference. Closed or replaced
entries have no remaining floor. Conflicting evidence raises an error; legitimate
incompleteness returns `INCOMPLETE`, reasons and empty `reference_floors`.

Valid open positions receive three reference scenarios. `reached_target_floor`
selects one only when the exact entry-bound native schedule has saved target
progress; before a touch or without that schedule it remains null. The stored
schedule must match the original native intent. Selection is a reference preview,
not activation. Reads do not infer fresh targets from prices or change progress.

`READY` means that the current stored arithmetic is available. Every result retains
`execution_authority=false`, `execution_ready=false`, `live_enabled=false` and
`data_host_costs_included=false`. The default observer report exposes saved `position.trade_floor` state only;
this explicit read API does not add accounting replay to every page request.
Detached journal copies need no authority database, model key or venue connection.

## Acceptance boundary

Native fixture tests cover CALL/PUT target stages, touches without sales, original
weighted basis, scale/runner fees, tick tiers, complete/partial/unresolved entries
and exits, entry plus non-order management charges after a scale, unknown and
unallocated costs, altered schedules, independent ledgers and read-only copies.
The calculation is independent of the caller's decimal precision.

Automatic enforcement is fixture verified as described below and is not silently
added to existing cohorts or the premium-trail policy. Scope watch/entry
linkage, its missing third objective, full path proof and complete management/runtime
acceptance remain open, as do provider/host evidence and the dedicated UI pass.
Main stays untouched, PR #1 draft, LIVE disabled and deployment frozen.


## Frozen automatic protection

New PAPER owners may freeze all three policy fields:

```json
{
  "partial_closes": "whole-contract-v1",
  "target_exits": "frozen-targets-v1",
  "trade_floor": "native-target-floor-v1"
}
```

The original buy, preparation inputs and approval retain enrollment. Dispatch
rejects changed terms or a mismatch with the owner's frozen policy. Accounting
creates `TradeFloorState` from that buy; reconciliation checks enrollment and keeps
the same entry's saved state through partial sales and restart. Omitted fields keep
legacy serialization unchanged. Existing owners cannot adopt this policy on reopen.

Enrollment alone does not invent a target schedule. It remains inactive until an
exact completed entry has an original frozen schedule and a freshly observed native
target has latched. Full-entry AI positions without that schedule keep their existing
protection; this does not add Scope geometry or AI target allocations.

The owner computes the reached 0/10/25% reference scenario in its audited write
transaction. It saves the greater of the previous accepted fill-price floor and the
new cost-aware candidate, the accepted reference stage and the latest successful
native evidence hash. Profitable actual sales can lower the preview to zero but
cannot loosen a previously accepted positive floor. The hash identifies the latest
successful calculation; the audit history retains earlier accepted floors. A first
zero floor means verified sales cover that scenario and needs no price trigger.

Only a fresh, complete, correctly bound REALTIME bid with positive size may trigger.
The engine applies the same conservative slippage and downward contract-tick
rounding used by native sale admission; at or below a positive saved minimum fill
price it latches `WHOLE_TRADE_FLOOR` and the first exit time. Ask, midpoint and last
prices are never substituted. A stale bid cannot trigger; an unavailable underlying
still blocks dispatch under existing supervision even if a valid bid latches the
exit. Targets may latch while the option is unpriced, as with frozen target stops.
Other existing mandatory exit reasons retain priority. No floor guarantees a fill
or a realized return; a price gap can put execution below the threshold.

Protection refresh runs before automatic scales, explicit partial-close preparation
and dispatch, and settled management-plan execution review. New paid advice can
raise required proceeds. Changed protection makes an older model packet fail its
existing position-state gate; model advice cannot overwrite the new floor or exit.
Audit failure rolls back stage, floor and latch together.

Incomplete costs, unallocated account calls or incomplete original entries retain
explicit `reasons`, withhold new floor arithmetic and block scales after a target.
They do not erase an accepted floor or disable independent mandatory protection.
Unresolved orders also withhold recomputation, preserving the existing reservation
and floor. A never-attempted prepared scale can be superseded by a mandatory full
exit; an attempted/partial/unknown order cannot be retried or silently canceled.
Actual terminal reconciliation is required before recomputing its sale proceeds.

Stored observation exposes the saved floor, stage, evidence hash and reasons with
its before-data/host-cost label; it never refreshes these fields. Close attribution
inherits original enrollment through the exact entry. Native export retains full
state while economic comparison excludes dynamic annotations and still checks the
original policy, schedule, lots, cash and fees. Open positions remain inconclusive.
Independent A/B/C/D replay retains all entry and management charges; no account
shares a floor, cash balance or model budget with another.

`tests/test_option_trade_floor_execution.py` covers target activation, executable
boundaries, scale/runner accounting, restart, stale or malformed bids, pending and
partially filled reservations, dispatch races, incomplete evidence, audit rollback,
read-only observation, enrollment tampering and open-boundary export. Its cost
refresh boundary injections complement the native paid-entry/non-order-management
receipt tests in `tests/test_option_trade_floor.py`. Native paid-selection cases
also verify that a recorded entry charge raises the enforced floor, unallocated
charges block activation, and later unknown cost cannot erase accepted protection.
These fixtures do not claim authentic model or provider acceptance. The four-arm replay case verifies frozen enrollment
without inventing schedules for full-entry AI positions.
