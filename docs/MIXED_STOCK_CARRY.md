# Original stock carry on the native mixed owner

An explicit `MixedOwnerPolicy.stock_carry` enrollment now permits original bounded
Swing long-share horizons on the [same native owner](MIXED_NATIVE_OWNER.md). It
adds no account, option contract, short stock, provider call or LIVE authority.
[Source-derived stock candidates and shared selection](MIXED_STOCK_SELECTION.md)
now bind these terms to original completed evidence and one native choice.

`mixed-stock-carry-v1` freezes maximum trading sessions, maximum calendar days,
final exit minutes before the actual close, catalyst source and catalyst freshness.
The original `StockCarryTerms` retain the source hash, policy hash, every actual
XNYS session boundary, exact final exit and full original catalyst evidence. The
calendar path is recomputed at native preparation, dispatch and stored approval
verification. Holidays, weekends and early closes are calendar facts; omitted or
rewritten sessions, extended exits and foreign policies cannot grant admission.
There is no option expiration field or synthetic option identity for shares.

The original proposal must be Swing, retain the same source hash and exit, and
arrive in its original first session. Catalyst evidence must be complete, realtime,
CLEAR, bound to the original stock symbol/source, fresh at preparation **and actual
dispatch**, and cover the final exit. Fresh quotes cannot replace expired original
catalyst evidence or extend the original source/approval deadline. Deriving terms
is order-free; only the native owner can approve and attempt a funded entry.

Entry orders remain DAY orders expiring at the original entry session close.
A carrying position retains its original stop, target, thesis, exit and calendar
terms through partial closes, reconciliation and restart. Native close approvals,
fixture acceptance and common fill reconstruction require those exact originals.
No intermediate session cutoff shortens the enrolled horizon. Stop/target/time
protection still latches independently of entry halts, model contracts and costs.
At the final deadline a missing quote retains the mandatory exit latch. A closed
market blocks execution and records `STOCK_CARRY_MARKET_CLOSED`; it cannot assert
an executable quote or invent a fill. Resuming fresh regular-session supervision
does not silently erase an entry halt or prior mandatory exit.

The existing explicit daily calendar allocations charge data, host and operating
costs across the whole holding interval, including weekends and nontrading days.
They remain part of the common loss envelope and attributed full-cost outcome;
unknown values remain unknown. These are declared offline fixture allocations,
not a claim that authentic provider or host costs have been accepted. Execution
fees and settled proceeds retain the existing common accounting rules.

Existing policies, proposals and intents omit absent carry fields, preserving
frozen serialization. A stock owner without explicit carry enrollment rejects
carry terms. Even an enrolled owner rejects a later exit without original terms;
no inference turns an ordinary session-close proposal into carry. Paid model,
continuous mixed runtime and mixed A/B/C/D export guards remain in place until
those full contracts are implemented.

`test_mixed_stock_carry.py` verifies native fixed-child entry/exit, original
calendar/catalyst/deadline rejection, weekend restart, full daily costs, original
protection and partial closes. See the latest [status](SLICE2_STATUS.md) for the
completed isolated-wheel proof. Original stock source selection is now connected; continue with complete paid
contracts, runtime and independent replay/export.
