# Two-play implementation map

Status: incomplete. The [accounting/admission continuation](TWO_PLAY_ACCOUNTING.md)
adds v2 keyed projections and moves existing native mixed replay onto the common
reducer. It does not enable native two-play execution. The remaining lifecycle
work below is still required. d2092f1 host deployment is confirmed by supplied
operator output; browser visual acceptance remains pending.

Original audit from d2092f16cc99a3749be04fb2bd5a5d26fa0e30bc on
2026-10-25. This is not authorization or evidence for a connected PAPER launch.
Local and remote branch matched; main b5359aaf396e692d2142d7e02908f1544e045ee6
and open/draft PR #1 verified. No applicable AGENTS.md found. SOURCE_OF_TRUTH
1.124 and the latest panel-balance status are the starting contract. The user now
requires up to two plays before the first connected PAPER test.

## Accounting invariants

- One owner, cash ledger, revision, restore authority and bankroll. No strategy wallets.
- The original entry client ID identifies a play through partial fills and closes.
  Every subsequent order, receipt, management decision and protection latch must
  bind that identity. Never select the first position as an implicit target.
- Pending accepted entries consume capacity. Reserve the remaining approved debit
  plus required exit fees in the same transaction that claims capacity.
- Invested basis and unfilled debit are disjoint. Entry fills move funds from
  available cash/reservation into invested basis, not profit. Exit fills realize
  proceeds and basis with native multipliers/fees; sale proceeds remain unsettled
  until the existing explicit settlement evidence permits reuse.
- Full invested-loss envelopes plus pending debit and exit reserves share the
  daily/total loss and exposure budgets. Adding capacity never raises these limits.
- Confirmed cancellation releases only the unfilled remainder. Pending cancellation,
  partial exit and uncertain attempts cannot release a held play or its protection.
- All fills and costs remain idempotent by original identities. Unknown state blocks
  new risk but cannot skip other positions' supported mandatory protection.

## File-level integration map

| Boundary | Existing files | Required work |
| --- | --- | --- |
| Contracts and ledger | mixed/portfolio_accounting.py, models.py, stock_models.py; options/lifecycle.py, models.py | V2 keyed cash projections implemented; native durable enrollment and migration still required |
| Replay/accounting | mixed/accounting.py, portfolio_accounting.py, native_store.py; options/accounting.py | V2 ordered cash replay and reservations implemented; existing native single-play reconciliation uses the common reducer; multi-play native persistence remains required |
| Atomic preparation | mixed/native_execution.py, native_store.py; options/engine.py; execution/journal.py | Use existing journal write transaction; replace UNIQUE active_lock and cross-asset global locks with per-play exclusivity and atomic capacity/funds checks |
| Reconciliation/venue | mixed/venue.py, quote_fills.py; options/venue.py, engine.py, process.py, worker.py | Snapshot multiple holdings, independently match receipts, prevent cross-play fills and duplicate liquidity use |
| Shared selection | mixed/selection.py, entry.py; options/coordinator.py, entry_coordination.py, entry_reasoning.py | Reassess post-reservation portfolio; same selector, HOLD valid, no extra paid calls to fill slots |
| Management/protection | mixed/native_protection.py, position.py, runtime.py; options/position_reasoning.py, position_coordination.py, runtime.py, protection.py | Explicit play identity throughout; protect all held plays before optional entry; independent stale-price behavior |
| Recovery/operator | mixed/native_store.py; options/operator_inbox.py; execution/restore.py | Keyed protection/recovery, crash tests at prepare/dispatch/fill/exit transitions, account halt across plays |
| Feed | options/read_mapping.py, read_capture.py, read_gateway.py; mixed/runtime.py; options/runtime.py | Durable continuous delivery; held plus candidate union; dedup instrument reads; metadata/entitlement remain explicit blockers |
| Replay/model compatibility | mixed/replay.py, replay_enrollment.py, market_tape.py; options/entry_judgment.py, position_judgment.py | New versioned populations and explicit play bindings; never reinterpret historical schemas |
| Dashboard | mixed/observer.py; web/mixed_view.py; mixed_content.html, mixed_desk_script.html, mixed_live_script.html | Compact two-play selector, selected-play/tab/disclosure/scroll persistence; no stale details after selected play closes |

Paths above are relative to app/. Some responsibilities span companion modules;
this map does not claim those modules have already been converted.

## Initial overlap and controls policy

No distinct plays in the same underlying or exact instrument. SPY, QQQ, SPX and
SPXW share an explicit index-exposure cap no greater than the account cap; differing
symbols do not grant independent risk budgets. Two different underlyings may fit
that shared cap. Existing no-scale-in rules remain unchanged.

The order-free portfolio_capacity module validates capacity/funding constraints
and reports distinct reasons. It is NOT connected to native preparation and supplies
no execution authorization. Its revision must ultimately come from the owner and
be revalidated while holding the write transaction, with reservation persisted in
that transaction. It alone does not establish atomic admission or recovery.

An eventual authenticated admin lightbox may select 0/1/2 entry slots within the
supported maximum. Lowering the limit blocks additional entries without closing
held positions. UI edits need the existing signed/revision-bound operator authority,
a durable audit record and server-side validation. No new control endpoint or LIVE
activation toggle is implemented here. PAPER and any future LIVE adapter must use
the same validated portfolio rules; current LIVE stays disabled.

## Migration, remaining work and acceptance

No database migration or deployment is included in this checkpoint. Existing
single-position schemas and frozen fixtures remain untouched. The integration must
choose a versioned migration that preserves original IDs and receipts, verify a
backup before mutation, and specify that rolling back migrated storage requires
restoring the matching backup. Never reinterpret newer storage using an old binary.

Native atomic reservation, fill/reconciliation, two-play protection/recovery,
selection, model schemas, continuous feed, dashboard selector and admin controls
are NOT implemented by this checkpoint. Contract metadata and entitlement remain
unresolved; weekend sample success is not market freshness acceptance. Do not run
a connected PAPER test, deploy this as two-play support, or claim engine completion.

Next verification must include concurrent native admission, partial entry/cancel,
uncertain submission, duplicate receipts, independent and simultaneous exits,
restart at every transition, legacy compatibility and realistic browser fixtures.
Then validate ongoing fresh delivery/reconnects and simulated fills on the host at
market open. The operator runs server commands; no provider/model calls, credentials,
production services or hosted CI are involved in this offline checkpoint.
