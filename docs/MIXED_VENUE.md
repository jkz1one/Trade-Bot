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
The separately enrolled native owner distinguishes PREPARED, SUBMITTING, UNKNOWN,
native approval and actual fills. The transport alone cannot prove those states.

Unenrolled `OptionExecution` rejects mixed venue enrollment even when flat, and rejects
mixed snapshots during reconciliation. A mixed schema cannot be grafted onto an
old fixture merely by adding stock limits. Mixed source clocks and stored event
sequence/identities are validated on reads and writes. Unsupported stock inputs
cannot silently disappear into an options-only runner.

The fixture does not authenticate approvals, strategy eligibility, native revision
ownership, native restore fencing or complete global/family loss controls. Its
frozen execution limits are not a replacement for those owner checks. Costs remain
with the common cash-history/native economics boundary: no absent model or operating
charge is manufactured as zero by this transport.

## Native owner integration

The [explicit native mixed owner](MIXED_NATIVE_OWNER.md) now binds stock preparation,
common journal/restore, attempted/unknown state, complete reconciliation, independent
stop/target/time protection, partial-close supersession, restart, signed recovery and
full-cost global/family loss outcomes. The transport itself still grants none of
that authority; only exact native enrollment can use both paths.

Original stock candidates/shared selection, paid mixed entry/management,
continuous runtime and [independent native A/B/C/D replay/export](MIXED_REPLAY.md)
now have separate complete contracts. The [plumbing status](MIXED_CASH_HISTORY.md#remaining-plumbing-in-total)
is current. Final UI/visual and authentic PAPER acceptance remain separate.
LIVE remains disabled and the deployed experiment remains frozen.

## Verification

`test_mixed_venue.py` exercises installed fixed children, cross-instrument contention,
partial fills, cash continuity, explicit settlement, original-term tampering,
source size, fractional fees, protocol failures, restart and rejected legacy
consumption. Existing cash/admission and native option/Scope/Swing suites run on
the same final noneditable wheel. See the newest [status entry](SLICE2_STATUS.md)
and [test procedure](OPTIONS_TESTING.md) for exact completed proof. Fixture
transport proof is not native mixed-owner or native four-arm replay acceptance.
