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
