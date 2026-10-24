# Native whole-contract partial closes

A new frozen PAPER population may set
`OptionExecutionPolicy.partial_closes="whole-contract-v1"`. Its trusted local
orchestrator can then call `prepare()` with a CLOSE proposal carrying an explicit
positive integer `close_quantity`. This supplies the native order primitive needed
for Scope's eventual first-target scale and runner workflow. Separately enrolled
[frozen target schedules](OPTIONS_TARGET_EXITS.md) now orchestrate automatic sales
from explicit entry allocations and verified fills. Scope profile/allocation selection
and watch execution remain open.

## Quantity and ownership

The common governor approves at most the requested quantity, current exact owned
contracts and observed bid size. A request above ownership rejects instead of
silently shrinking. Fractions, booleans, strings, zero and negative counts reject.
HOLD and OPEN_LONG cannot carry a close quantity. One contract cannot split into
fractional exits. Omitting the field retains the previous full-owned-close request,
still subject to executable bid size.

The original requested ceiling is frozen in `OptionIntent.requested_close_quantity`,
while the intent's `quantity` is the actual fixed approved order size. Both bind
the same exact entry through `closing_entry_client_id`. Dispatch checks the stored
proposal, requested ceiling and approved quantity before any attempt. A later
increase in liquidity cannot enlarge that prepared order. Changed action reuse
rejects; an exact retry returns the historical preparation receipt. Retrying a
completed/attempted client does not submit a replacement.

Only `DETERMINISTIC` origin may use this explicit quantity API. It is software
orchestration authority, not a new model sizing field or broker tool. Existing
model EXIT_ALL and protective full exits keep their original behavior.

## Protection takes precedence

A request that would deliberately retain contracts must supply fresh executable
option and underlying protection evidence at both preparation and dispatch. The
shared protection evaluator rechecks original/tightened invalidation, premium
catastrophe, any stored entry target, and time/expiry requirements. A mandatory
full-exit reason is latched in the same transaction and rejects the partial request.
A rebound, restart or failed scale cannot erase the latch. Missing/stale protection
evidence blocks a planned scale; ordinary full-owned closes remain available.

When independent `protective_tick()` observes a required exit, it may reject and
release a locally prepared partial order **only if no attempt was recorded** and
it belongs to the same held entry. It records `OPTION_PARTIAL_CLOSE_SUPERSEDED`
without calling a venue cancel API, then prepares the ordinary protective close.
A rejected unattempted bounded close does not require a failed-venue-order review
before protection can proceed.

An OPEN, SUBMITTING, PARTIAL or UNKNOWN attempted order is never canceled, replayed
or assumed absent. It retains the existing single-order reservation. After verified
completion, protection addresses actual remaining ownership. Attempted rejected,
canceled or expired exits retain the existing explicit review requirement.

## Accounting and evidence

Every scale and runner order retains its own actual execution fees and observed
fills. FIFO basis, remaining quantity, settled cash and the exact original entry
reconstruct through the existing accounting replay. Sale credits remain unsettled
until an explicit funds-settlement receipt. Remaining contracts retain their stop,
entry target/horizon and independent protection.

Entry admission already reserves one closing order fee per contract; planned
scaling does not introduce a second fee calculator or discard those reserves.
The common governor's conservative fee allowance remains distinct from actual
per-order/per-contract fees recorded by fills. All entry and management model
charges remain linked to the original entry, including advice that produced no
order. Unknown costs stay unknown.

Order/decision attribution exposes `requested_close_quantity` separately from
approved and actually filled quantities. A partial exit does not complete a
position outcome or consume a completed loss. Only the verified final close or
settlement, with every attributable charge known, can complete the existing native
loss review. Independent owners and family histories remain separate.

Omitted optional fields preserve historical serialization. Existing populations
cannot enable this policy on reopen, and old orders/receipts are not backfilled.
The observer/export uses stored attribution without performing trading work.

## Acceptance boundary

Fixture proof covers native prepare/dispatch/fill/reconciliation, partial and
final closes, fee conservation, lineage and entry/management charges, loss
recognition, durable retry/restart, ownership ceilings, protection races and
transaction rollback. This is a shared execution primitive, not completed Scope
strategy integration or authentic broker/provider acceptance.

Scope still needs complete obstruction coverage, a frozen watch-to-order and
filled-position lifecycle, profile/quantity-specific target allocation, Scope
family loss/reset linkage, runtime and replay. Its existing generic entry guard
remains in force. No extra AI role, live adapter, host process or deployment is
introduced. See [native execution](OPTIONS_EXECUTION.md),
[position outcomes](OPTIONS_POSITION_OUTCOME.md),
[Scope admission](OPTIONS_SCOPE_OWNED_ADMISSION.md) and
[source of truth](SOURCE_OF_TRUTH.md).
