# Stored native position outcomes

`OptionObserver(journal, population_id).position_outcome(entry_client_id)` reads
one exact native buy entry from a bounded, read-only SQLite snapshot. It derives
account identity and model pricing from frozen journal configuration. It never
attaches an execution owner, refreshes evidence, submits an order or changes limits.
Conflicting evidence raises an error; incomplete evidence returns `INCOMPLETE`.

The projection reuses native proposal/approval/observed-fill attribution. Protective
and model-managed exits must identify the original buy. Observed fills supply
quantities, premiums and actual execution fees; quantities cannot exceed the buy
or precede its fills. Closure requires terminal linked orders and equal positive
entry/exit quantities. Open, partial and unfilled positions have no realized outcome.

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
after the selected entry still makes its result incomplete. Contract-level
settlement receipts also lack a unique entry ID and cannot prove position closure.
This conservatively includes later same-contract activity rather than guessing an
allocation. Orphan/mismatched fills and damaged proposal/approval/cost evidence
are rejected. Reads preserve stored history and grant no execution authority.

This is the native evidence primitive for subsequent Scope loss-state work.
It does not link watches to orders, consume loss streaks, start cooldowns, reset
risk limits or enroll Scope execution. The existing
[Scope entry guard](OPTIONS_SCOPE_OWNED_ADMISSION.md#native-execution-boundary)
remains in force. Complete path coverage, native Scope lifecycle/runtime/replay,
authentic provider/model/host evidence and prospective economics remain open.
