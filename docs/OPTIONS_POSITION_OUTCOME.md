# Stored native position outcomes

`OptionObserver(journal, population_id).position_outcome(entry_client_id)` reads
one exact native buy entry from a bounded, read-only SQLite snapshot. It derives
account identity and model pricing from frozen journal configuration. It never
attaches an execution owner, refreshes evidence, submits an order or changes limits.
Conflicting evidence raises an error; incomplete evidence returns `INCOMPLETE`.

The projection reuses native proposal/approval/observed-fill attribution. Protective
and model-managed exits must identify the original buy. Observed fills supply
quantities, premiums and actual execution fees; quantities cannot exceed the buy
or precede its fills. Closure requires terminal linked orders and a positive entry
quantity equal to the sum of sold and authoritatively settled contracts. Open,
partial and unfilled positions have no realized outcome.

Every stored entry or management call attributable to this position is retained,
including management calls that did not create an order. Configured token charges
are checked against stored usage and frozen prices. Unknown cost is never zero.
Calls without a proven position allocation remain visible as account charges and
suppress the position's net result. Account-level daily/total cost limits remain
authoritative; this projection does not allocate unrelated HOLD costs arbitrarily.

A complete result reports entry/exit premiums, execution fees, known model costs
and their net, with a LOSS/WIN/FLAT classification. This is expressly **not an
all-in economic result**: data and host costs are not allocated here. Full-cost
session comparisons remain the research/economic authority. Accounts are never
combined and callers cannot supply P&L or replacement prices.

New native CLOSE intents now store `closing_entry_client_id`, derived from the
owner's held position in the preparation transaction and repeated in the approval.
This covers ordinary, protective and model-managed closes. Dispatch checks both
copies against the still-held entry before recording an attempt. A changed or
missing half-link rejects dispatch with `OPTION_CLOSING_ENTRY_CHANGED`; it does
not retarget the close to a newer position in the same contract. Stored attribution
checks this link against the native buy, instrument, chronology and any existing
protective/model link. Attributed close-model charges retain the same entry ID.

Owner and isolated fixture worker must use the same installed release; an older
worker cannot decode a new close intent. This change does not deploy either.
The optional field is omitted when absent, preserving historical intent encoding.
Legacy protective/model links remain supported. Historical ordinary CLOSE orders
without an exact link are not backfilled. A same-contract unlinked exit prepared
after the selected entry still makes its result incomplete. Orphan/mismatched fills
and damaged proposal/approval/cost evidence are rejected. Reads preserve stored
history and grant no execution authority.

## Frozen strategy entry identity

New native buys prepared from a stored selected opportunity now carry
`entry_lineage`: the Degen/Swing family, exact setup, opportunity key, candidate ID
and hash of the complete admitted candidate. The engine derives it inside its
preparation transaction; callers cannot choose a family label. The identical record
is retained in intent and approval. Exact instrument and admitted-contract identity
must match. Missing/duplicate selected candidates or conflicting selection evidence
cannot produce a lineage-bound order. Direct engine orders without a stored
opportunity remain unlabeled rather than inheriting a family from a symbol or thesis.

Before the first dispatch attempt, both copies and the stored selected candidate
are rechecked. Changed selection, candidate evidence, instrument or approval rejects
the prepared order and releases its active lock without a venue call. This adds no
new submission or replacement path. Owner and isolated worker must use the same
installed release to understand the new optional intent field.

Stored order attribution and position outcomes validate the same binding. Ordinary,
protective and model-managed exits inherit family identity through their exact
buy-entry link. MAINTAIN/TIGHTEN advice without an order also inherits its owned
entry's label. Every entry/management charge and execution fee remains accounted
for by the existing outcome and independent-session export. Unknown/unallocated
costs continue to withhold net results. Labels do not allocate unrelated HOLD costs
or data/host charges to a position.

Absent optional fields preserve old intent/attribution serialization; historical
unlabeled orders are not backfilled from current opportunity records. A missing or
mismatched half-link fails closed. Scope cannot be declared through this contract;
its research-only native execution gate remains enforced. This is a prerequisite
for verified family loss attribution, not family-scoped loss/reset enforcement.

## Native settlement attribution

The outcome projection now replays the complete ordered native fill and receipt
stream from frozen original capital. Each cash-settlement or worthless-expiry
receipt is assigned to the exact position held immediately before the receipt.
Contract equality alone is insufficient: event sequences must be contiguous,
clocks ordered, receipts and fills covered by the stored complete owned snapshot,
and replayed cash, settled cash, realized P&L, fees, daily P&L and remaining lots
must agree with the journal. Foreign account/venue identity or unsupported
underlying exposure blocks the projection. A missing or conflicting stream raises
an error instead of manufacturing a settlement outcome.

The same native accounting rules enforce settlement time, full remaining quantity,
contract terms, authoritative value and exact cash proceeds. FUNDS_SETTLED changes
cash availability only and does not count as a close. PHYSICAL_EXERCISE does not
produce a supported cash outcome. Model charges stay separate from the cash ledger
and every attributed entry/management charge is still deducted by the outcome;
unknown usage still suppresses net results even after a verified settlement.

`settlements` retains the original receipts with derived entry IDs;
`settlement_quantity` and `settlement_cash` are distinct from sold quantity,
exit premium and fill IDs. Partial sales followed by settlement count each contract
once. A later settlement of a second entry in the same contract is not assigned to
the first. `closed_at` uses the last actual closing fill or settlement time.
`unlinked_settlement_receipt_ids` remains an empty compatibility field on valid
results; unprovable receipt history now fails validation. These are local fixture
accounting terms, with no additional settlement fee encoded. Authentic broker fee
coverage and data/host allocations remain separate acceptance requirements.

This is the native evidence primitive for subsequent Scope loss-state work.
It does not link watches to orders, consume loss streaks, start cooldowns, reset
risk limits or enroll Scope execution. The existing
[Scope entry guard](OPTIONS_SCOPE_OWNED_ADMISSION.md#native-execution-boundary)
remains in force. Complete path coverage, native Scope lifecycle/runtime/replay,
authentic provider/model/host evidence and prospective economics remain open.
