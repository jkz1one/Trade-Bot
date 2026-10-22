# Shared stock/options durable fixture

This is a create-only, explicitly enrolled local PAPER fixture transport. It is
not a native mixed execution owner, a broker adapter, or permission to run a mixed
strategy. It builds on [common cash history and admission](MIXED_CASH_HISTORY.md).

## One venue and one balance

`DurableOptionVenue(..., stock_limits=...)` creates the separate
`durable-mixed-fixture-v1` population. Both option limits and actual long-share
limits are frozen. Stock primitives live in `app/mixed/stock_models.py` and remain
re-exported from `app/mixed/models.py`; existing history contracts retain their
serialization. Existing option-only fixtures retain their original schema and
omit all new optional stock fields.

There is one private SQLite state, original capital, cash balance, settled balance,
submit count and event sequence. The same `BEGIN IMMEDIATE` transaction enforces
one unresolved order and one holding across both asset types. Two competing child
processes cannot each acquire a different instrument's order lock. Stock entries
require their approved debit plus conservative close fees to fit settled funds;
option entries continue to use their original full-premium-loss envelope. Neither
path opens a second holding or turns an option exercise into a stock strategy.

Actual share fills retain FIFO lots and the complete accepted stock intent:
original instrument, source hash/clocks, family, thesis, geometry, approval hash,
account revision, approval expiry and DAY/strategy deadlines. A fill cannot replace
any accepted term. A close binds the owned entry and its original terms. Partial
entry cancellation retains its actual shares; a rejected order cannot contain fills.
Terminal records remain in history and cannot be replayed as fresh attempts.

Stock fills require a later fresh realtime executable quote, exact share increment,
observed size, adverse tick/slippage price and exact per-share/first-fill order fee.
Changing a quote's receipt time or decimal formatting cannot create more liquidity
at one source instant. Partial closes use the same cash balance, and sale credits
remain unsettled until an explicit funds receipt. Stock and option fills share
unique fill identities and one consecutive chronological event sequence. A stock →
option → stock fixture history reconstructs from one original capital using the
existing common accounting boundary, including fees and settlement.

## Fixed child and enrollment boundaries

The existing bounded `python -I -m app.options.worker` accepts a separately typed
`stock_accept` operation. Requests retain the full stock intent and exact frozen
stock limits. The child verifies venue/account/population and stock-policy binding.
The existing timeout, bounded protocol, parent ownership and cleanup path applies;
no arbitrary adapter, credential, provider or model call is added.

Lost/invalid/oversized acknowledgments, crashes and stalls do not erase an accepted
stock order. A repeated client identity is rejected. Fixture terminal operations
are explicit scripted outcomes, not authenticated cancellation or retry authority.
A native journal still has to distinguish PREPARED, SUBMITTING, UNKNOWN, native
approval and actual fills before this transport can power a mixed trader.

Legacy `OptionExecution` rejects mixed venue enrollment even when flat, and rejects
mixed snapshots during reconciliation. A mixed schema cannot be grafted onto an
old fixture merely by adding stock limits. Mixed source clocks and stored event
sequence/identities are validated on reads and writes. Unsupported stock inputs
cannot silently disappear into an options-only runner.

The fixture does not authenticate approvals, strategy eligibility, native revision
ownership, native restore fencing or complete global/family loss controls. Its
frozen execution limits are not a replacement for those owner checks. Costs remain
with the common cash-history/native economics boundary: no absent model or operating
charge is manufactured as zero by this transport.

## Remaining integration

The venue and fixed worker portion of item 1 in the [remaining plumbing
list](MIXED_CASH_HISTORY.md#remaining-plumbing-in-total) is implemented. Still required:

1. Bind stock preparation, common journal/restore fence, attempted/unknown state,
   complete reconciliation, independent stop/target/time protection, partial-close
   supersession, restart and signed recovery to the native owner.
2. Connect original stock candidates to shared family selection, complete mixed
   entry/management model contracts, fresh post-cost native admission and one
   global/family loss-control history.
3. Connect explicit mixed continuous runtime inputs and common market tapes to
   four independent native A/B/C/D replay/export accounts with all costs.

Final UI/visual and authentic provider/model/host/PAPER acceptance follow those
steps. LIVE remains disabled and the deployed experiment remains frozen.

## Next owner boundary

Continue in `app/options/engine.py` and `app/options/loss_control.py`, using the
common accounting/admission helpers and this fixture. Do not simply remove the
mixed enrollment rejection: `_account`, `_epoch`, submission guards, `_reconcile`,
position supervision, recovery and loss consumption currently enumerate native
option orders. They must bind stock attempts and stock holdings to the same durable
owner, original capital, revision, restore fence and economic envelope. A stock
holding must appear in the existing `EquityHolding` account discriminator while
option/Scope/Swing positions retain their full original native terms.

Stock and option fills must reconcile in one global event sequence from the original
capital. Stock observations now include the exact accepted intent, but the native
journal must independently prove its approval, attempt time and immutable prefix.
Paid entry/management proposals remain separate from preparation, attempts and fills.
Mandatory stock exits must survive partial fills, unknown attempts, restart and
entry/model halts. Unsupported mixed coordinator/runtime/export enrollment must
continue to reject until those complete contracts are connected.

## Verification

`test_mixed_venue.py` exercises installed fixed children, cross-instrument contention,
partial fills, cash continuity, explicit settlement, original-term tampering,
source size, fractional fees, protocol failures, restart and rejected legacy
consumption. Existing cash/admission and native option/Scope/Swing suites run on
the same final noneditable wheel. See the newest [status entry](SLICE2_STATUS.md)
and [test procedure](OPTIONS_TESTING.md) for exact completed proof. Fixture
transport proof is not native mixed-owner or native four-arm replay acceptance.
