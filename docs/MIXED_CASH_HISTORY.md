# Shared stock/options cash history and admission

Delivered accounting and order-free admission boundary, October 22, 2026
America/New_York. This is the first mixed-owner implementation slice. It does **not**
yet enroll a mixed native execution owner, submit stock orders, run mixed strategies
or provide native mixed A/B/C/D replay. Existing stock and option populations remain
unchanged. Do not attach their independently funded engines to one brokerage account.

## One original balance

`app/mixed/models.py` defines `mixed-cash-history-v1`: one account, population, venue,
provider, original capital and global daily/total loss envelope. Stock limits are
explicit and frozen alongside existing option limits. Actual US-listed equity/ETF
identities, share increments and share quote sizes never become synthetic options.
Scope remains an options family. Stock proposals are long-only Degen/Swing inputs.

`app/mixed/accounting.py::reconstruct` replays the complete supplied fill/settlement
sequence from original capital. The option branch uses the existing native exact
accounting operations on the current common balance; it does not fund a child
account. Stock and option holdings are mutually exclusive. Shares retain their
complete original intent, thesis, family/source hashes, account revision, approval
hash/deadlines, fixed stop/target/exit time and FIFO lots. Option intents/positions
retain their existing Scope, fill-reference, target, premium, time and carry terms.

Every fill must bind a consistent original intent, order and attempted instant.
Global receipt sequence and clocks cannot regress, duplicate or contain gaps.
Partial fills cannot exceed the original quantity/debit, and an entry cannot resume
after an exit begins. Stock sells require the exact owned entry and original terms.
Cash, settled cash, realized P&L, execution fees and daily net P&L share one ledger.
Stock sale credits remain unsettled until an explicit valid funds receipt. Option
expiry/cash receipts retain native checks; they cannot transform a stock holding.
Unexpected physical exercise is not a stock-entry path.

Stock fills require later real-time, complete, fresh, matching executable quotes;
observed share size; adverse slippage/tick rounding; and all first-fill order and
per-share fees. Changing a receipt time or equivalent decimal formatting cannot
mint more source liquidity. Missing size is unavailable evidence. Exact fractional
shares require the frozen increment, down to 1e-8; options remain whole contracts.
All arithmetic uses a private high-precision Decimal context. Bounded native money
serialization is retained, with no implicit rounding to force a fill.

The configured stock increment also determines conservative exit-order fee
reservation: one order fee per minimum-sized close plus per-share fees. A fine
fractional increment with positive order fees can make entry unaffordable. This is
an explicit consequence of the frozen fee/quantity policy, not permission to omit
possible fees or change increments after entry.

## Uncertainty, costs and retained prefixes

At most one unresolved order reservation spans both instrument types. Preparation,
submission, ambiguous attempts and working/partial orders remain blockers. Expired
approval alone never releases a reservation. Remaining entry debit is calculated
from actual paid fills, with held exit fees retained. A pending sale cannot reserve
more than the owned remainder. An unfunded exit reserve is explicit and blocks entry.

Every supplied entry/management model charge is included, including paid rejected
entries. DATA, HOST and OPERATING allocations must be explicit for every New York
calendar date in the bounded history interval, including overnight dates. Zero is
an explicit amount; absent allocations and unresolved usage remain unknown. Broker
cash is distinct from economic P&L. Known charges reduce the common loss budget;
unknown charges suppress net results and available loss budgets and block entry.
This accounting boundary cannot discover a model call omitted by its future native
owner. Native attempt/usage completeness remains an integration requirement.

An unknown original cost remains immutable. A separate attributed resolution can
supply its known amount and evidence later. `verify_extension` requires unchanged
account/provider/policy/original capital, immutable prior fills/receipts, original
costs and resolutions, monotonic capture times and no backdated appended records.
An unresolved reservation needs an exact explicit terminal record before release.
This verifies supplied evidence consistency, not broker authenticity or cancellation
success. Terminal receipts must come from the future native owner, never a model.

## One admission envelope

`app/mixed/governor.py::option_account` projects the same cash, settled balance,
reservations, costs and loss headroom into existing `OptionAccount`. A share holding
becomes its existing `EquityHolding`, so the native option governor blocks a second
position. It does not receive a newly funded account.

`admit_stock` is deterministic and order-free. It binds the original proposal and
complete account-history hashes, requires exact instruments and fresh executable
quotes/session/account evidence, and sizes long shares within settled cash, all
fees, exposure, entry debit and common remaining full-loss limits. A stop does not
guarantee proceeds or permit extra credit. Source expiry, original exit time, account
and quote freshness, session cutoff and frozen approval lifetime cap the approval.
Fresh inputs cannot extend original source validity or move original geometry.

Both paths default to unreconciled. Setting `reconciled=True` is an explicit caller
assertion with the same trust boundary as the existing pure option governor; it
is not authenticated native ownership. No public helper creates a dispatchable
stock intent from a model response. Proposal, accounting projection, admission,
attempt and actual fill remain separate contracts. Independent owned stock-close
admission remains available under entry halts, exhausted/unknown economic budgets,
entry cutoffs or a price below new-entry eligibility, subject to fresh executable
proof, exact ownership and fee-paying liquidity. This is not yet a running stock
protection supervisor.

## Remaining plumbing in total

The [native mixed owner](MIXED_NATIVE_OWNER.md) now connects the common ledger and
[shared fixture](MIXED_VENUE.md) to one journal, restore fence, cross-instrument order
lock, preparation/attempts, complete reconciliation, independent stock protection,
partial exits, restart, signed recovery and full-cost global/family loss history.
Remaining:

1. Derive native stock candidates from original Degen/Swing sources and join the
   existing option/Scope selector. Retain exact family/instrument lineage, fixed
   original geometry and source clocks. Bind the [explicit stock carry](MIXED_STOCK_CARRY.md)
   terms to those sources; native calendar/catalyst/protection and daily-cost
   contracts are now implemented. No fake option contracts or bearish shorts.
2. Bind complete mixed entry/management model contracts, fresh post-cost native
   admission and paid attribution into the common global/family loss history.
   Preserve original deadlines and every
   usage charge, rejected decision, partial close and mandatory exit.
3. Connect explicit mixed runtime inputs, source collection, continuous sessions,
   held protection, settlement and recovery. Unsupported inputs must reject at the
   enrollment boundary; old frozen populations remain unchanged.
4. Connect common mixed market tapes to four independent native A/B/C/D accounts and
   portable full-cost replay/export, including all entry/management charges,
   execution fees, operating/overnight allocations and unknown costs. Pure account
   isolation tests here are not native four-arm mixed replay acceptance.

Then final UI/visual and authentic provider/model/host/economic/PAPER acceptance.
LIVE remains disabled and the deployed experiment frozen. The original cash-history slice changed no existing option/stock implementation.
The subsequent fixture slice explicitly enrolls mixed transport; dependencies,
broker transport and deployment remain unchanged.

## Verification

`test_mixed_accounting.py` and `test_mixed_admission.py` cover cross-instrument cash,
partial fills, settlement, unresolved reservations, original terms, fee/size/time
validation, unknown/known costs, retained prefixes and shared admission. Tests also
project actual native option, Scope and Swing carry entries, preserving their exact
positions and original terms. Four separately bound histories prove cash/cost
isolation without claiming a mixed replay scheduler. Follow the installed-wheel
procedure in [OPTIONS_TESTING.md](OPTIONS_TESTING.md); final measured evidence is in
[SLICE2_STATUS.md](SLICE2_STATUS.md).
