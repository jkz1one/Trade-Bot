# One native stock/options PAPER owner

The explicit `mixed-native-owner-v1` policy now binds actual long shares and native
options to the **same `OptionExecution` owner**, journal, original capital, revision,
restore fence and bounded fixture child. This is offline native execution plumbing.
A separate [stock selection enrollment](MIXED_STOCK_SELECTION.md) now binds
original source candidates and one shared stock/options/Scope choice. Paid mixed
models, continuous runtime and A/B/C/D replay remain unenrolled.
Those remaining contracts must be connected before authentic PAPER acceptance.

## Create-only enrollment and common evidence

`OptionExecutionPolicy.mixed_owner` freezes exact share limits and explicit nullable
daily data, host and operating allocations. The owner requires the separately
[enrolled mixed venue](MIXED_VENUE.md), one provider and global plus Degen/Swing loss
policies. Native Scope enrollment also retains its required Scope family policy.
Mixed paid calls remain disabled. Existing option-only policies omit the new field;
old journals, venue schemas and serialized contracts are unchanged.

The original journal retains its cash/settled ledger and native option position.
Separate stock order/fill/decision and held-protection tables belong to that same
journal and restore authority. SQLite triggers enforce one active order across both
asset tables. Stock PREPARED, SUBMITTING, UNKNOWN, OPEN, partial and terminal states
are distinct. Acknowledgment does not create a fill. Interrupted submissions reopen
as UNKNOWN and halt entries; reconciliation must recover exact attempted evidence.
Repeated dispatch never repeats an uncertain or already attempted order.

Both instruments reconcile in one consecutive chronological event sequence from
original capital. Actual fills and explicit settlement receipts determine cash,
settled cash, lots, fees and realized results. Stock observations must match their
full native intent, attempt time and immutable prior fills. Unowned/missing orders,
rewritten terms, changed fees, conflicting identities and reopened retired entries
block reconciliation. An options-only snapshot cannot replace mixed evidence.
The existing account discriminator represents shares as `EquityHolding`, blocking
competing option entries without funding another account. Native Scope targets and
Swing carry terms remain attached to their original option entries.

## Native stock approval and independent exits

`prepare_stock` stores the original proposal, quote, complete common cash history,
session, admission, account snapshot and revision. It derives the stock intent only
after native admission. Verification recomputes the original admission and binds
its quantity, price, debit, close fees, source clocks, thesis, family, geometry and
original deadlines. Dispatch requires fresh admission within the **original**
approval window; refreshed inputs cannot extend it, increase the approved price or
silently resize the order. Stock carry requires a separate [explicit enrollment](MIXED_STOCK_CARRY.md) and
original calendar/catalyst terms. Without them, an exit beyond the owner's session
protection cutoff is rejected rather than shortened.

`assess_stock` and `protective_stock_tick` preserve original invalidation, target
and time protection independently of entry halts or unknown model costs. A triggered
exit remains latched across rebound, partial fills and restart. Missing executable
quotes block dispatch while retaining a time-exit latch. Tightening cannot widen
protection or cross the current bid. Closes bind the exact original owned entry,
retain its source terms/thesis and use actual share quantities and native fees.

Partial-close preparation and dispatch freshly reassess mandatory protection.
A newly mandatory full exit supersedes an unattempted partial close. An attempted
or uncertain close remains unresolved; an attempted terminal failure requires
review instead of automatic resubmission. Stock source keys cannot collide with
native option decisions. Option-only supervision cannot certify a held stock as
healthy without its stock quote.

The same lifetime owner lock and paired restore fence cover stock mutations.
Signed operator recovery retains authentication, exact revisions, fresh common
account/supervision and unresolved-order checks. Global/family lock resets require
flat ownership, expired cooldown and completed full-cost evidence. Resetting a lock
or resuming entries does not erase trades, costs, halts or original protection.

## Full costs and one loss history

The frozen `daily-calendar-fixture-v1` allocation explicitly declares data, host and
operating costs for each New York calendar day, including nontrading days, within
a bounded 366-day fixture horizon. Zero is
an explicit fixture assumption; `None` remains unknown. Daily records are charged
to a holding at the boundary, otherwise to the next actual filled entry. Idle
allocations still reduce account loss headroom. Operating allocations are expenses,
not invented cash transfers or extra funds-settled receipts.

Stock and option outcomes feed the existing global/family loss history once, in
close order, with all execution fees and attributed operating allocations. A gross
win can therefore be a net loss. Original stock entry and allocation records remain
in the consumed outcome digest. Unknown costs keep budgets/outcomes incomplete.
Paid mixed contracts are not enrolled; an unexpected retained usage row blocks new
entries and loss consumption without suppressing independent owned exits. It is
never treated as a free call. Direct native option outcome fields continue to label
execution/model costs separately; complete mixed portable export is not yet enabled.

## Remaining plumbing

Original stock source derivation, shared stock/options/Scope selection, immutable
source retirement and source-bound carry are now connected through the separate
[selection contract](MIXED_STOCK_SELECTION.md).

[Paid mixed entry/management](MIXED_AI.md) now bind full requests/results, every
usage charge, original deadlines, fresh native admission and full-cost attribution.

1. Connect explicit continuous mixed inputs, source collection, held protection,
   settlement and recovery across sessions.
2. Connect common mixed tapes to independent native A/B/C/D owners and portable
   full-cost replay/export. Keep their cash, reservations, attempts and loss states
   separate, including operating/overnight costs and unknown charges.

Option-only runtime, old replay adapters and option/Scope comparison exports
reject mixed enrollment until their complete contracts exist. The basic
owned journal report labels `MIXED_PAPER_FIXTURE` and includes stock state; it is not
final dashboard or observer acceptance. See the [complete remaining list](MIXED_CASH_HISTORY.md#remaining-plumbing-in-total).
Final UI/visual and authentic provider/model/host/PAPER acceptance remain after the
plumbing. LIVE stays disabled; the deployed experiment stays frozen.

## Verification and continuation

`test_mixed_native_owner.py` runs against a noneditable installed wheel and actual
bounded fixed children. It covers native stock/option cash continuity, original
approval tampering, uncertainty/restart, full-cost losses, independent protection,
partial supersession, restore fencing, signed recovery and original Scope/Swing
terms. The [testing procedure](OPTIONS_TESTING.md) and latest [status entry](SLICE2_STATUS.md)
record exact completed final-wheel cases, including legacy regressions.

Continue with explicit continuous mixed runtime and independent A/B/C/D replay/export.
Do not remove legacy input guards to make old adapters accept mixed evidence.
Preserve one native owner and its complete original admission evidence throughout.
