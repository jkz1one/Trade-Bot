# Two-play accounting and candidate admission

Status: implemented offline accounting/admission contracts; native two-play execution
is incomplete. Starting local and remote HEAD was b901ded7a5b733075cfd643699d50543f3f3daae,
with tree 0456a1b03d2b61661e3f44a09ccc00c082f941f3 and unchanged main
b5359aaf396e692d2142d7e02908f1544e045ee6. PR #1 was open/draft. No applicable
AGENTS.md was found. Work used a separate clean worktree.

## Implemented

`portfolio_accounting.py` defines explicit mixed-cash-history-v2 policy, history,
ledger and projection contracts. Holdings are keyed by original entry client ID;
scalar position fields must remain empty in this version. One globally ordered
history owns cash, settled funds, fees, realized P&L and costs. The existing stock
and option reducers receive the current shared account balances plus an explicitly
selected holding; these transient calculation views are not separately funded
accounts or execution owners.

Two stock holdings, two option holdings, or a stock/option pair retain independent
entry terms and FIFO lots. Partial exits and exact-play option settlements preserve
the other holding. Account funds settlement remains account-wide. Original intent,
receipt identity, immutable prefix, source quote, quantity, fees and deadlines are
checked. Same-instrument/underlying exposure, missing/foreign closing identities,
reused receipts and resumed entries after exits are rejected. Option source size
cannot be replenished by changing only the receipt timestamp.

Held basis, remaining entry debit and exit fees are separate commitments. Partial
fills reserve only the remaining units at the approved limit plus applicable fees;
price improvement on already filled units becomes available. Confirmed cancellation
releases only the unfilled reservation. Uncertain entries/exits retain capacity.
Unknown costs retain their existing entry restrictions. Lower entry limits do not
remove held positions from the projection.

The existing `admit_stock` now supports explicit v2 history and exact-play closes.
`admit_portfolio_option` uses the existing option quote/calendar/contract governor
with the remaining shared funds, loss and index-exposure budgets. This is quantity
sizing and evidence review, not reservation or dispatch authority. Receipts have
separate v2 versions and bind the full history; closes include the play ID. Legacy
admission models reject them, preventing accidental reuse by an unconverted owner.

Existing **single-play native mixed reconciliation** now calls the common verified
cash-history reducer after native source/order/attempt/fill validation. Its stored
position/protection behavior and single-order lock remain unchanged. This removes
the duplicate native cash replay implementation and tests the common reducer on
actual existing native fixture execution.

## Compatibility and remaining integration

No existing database is migrated or enrolled in v2. Legacy cash serialization omits
the new optional settlement play binding. Frozen v1 histories retain scalar semantics
and cannot silently become v2; immutable-prefix verification rejects a version or
policy change. Missing original strategy lineage is never guessed for v2 options.
This change supplies no database migration command or rollback procedure. A future
migration must verify backups and preserve original receipts, IDs, balances and
theses; rollback of migrated storage will require the matching backup.

Still required: authoritative transaction-bound native capacity/funds reservation;
per-play order locks and multi-position venue snapshots; native preparation,
dispatch, independent protection/management and restart recovery; selection and
model-schema binding; signed admin control; continuous normalized market feed;
dashboard selector and browser review. The native engine still permits one play.
No claim of concurrency, two-play native execution or two-play recovery is made.

Reviewed contract metadata, entitlement and equity executable sizes remain unresolved.
Successful weekend samples do not establish fresh market data. No provider/broker
or paid model call, credentials access, hosted CI, dependency change, host service
change, PAPER activation or LIVE routing occurred. The supplied d2092f1 deployment
is recorded in [panel-balance status](MIXED_PANEL_BALANCE.md); browser acceptance
remains pending. No deployment commands are supplied for unfinished two-play support.

Installed-wheel validation records 401 deduplicated passing cases and 262 matching
application files in [TWO_PLAY_ACCOUNTING_PROOF.json](TWO_PLAY_ACCOUNTING_PROOF.json). Only
completed cases against the final wheel count; earlier diagnostic runs are separate.
