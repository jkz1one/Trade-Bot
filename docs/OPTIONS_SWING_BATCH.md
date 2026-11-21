# Concurrent Swing-family selection

`SwingPolicy.family_batch="complete-family-batch-v1"` explicitly enrolls a new
PAPER population. Daily base, 8/21 EMA and 50 SMA, previous-week/month high/low and
aligned weekly-open setups can now compete in the same native cycle. Existing
single-seed populations keep their original serialization, quote planning and
model packet contracts. This does not change a deployed population.

## One original source per symbol

`DegenFrame.swing_batches` supplies one `SwingBatchInput` for every frozen symbol.
Its original `SwingBatchSeed` contains the completed daily history, original hourly
history when base/MA is enrolled, creation and target-session clocks, original carry
exit session, and exactly one locked CALL and PUT instrument in that order.
Current metadata binds those exact two instruments; catalyst evidence binds the
symbol. Legacy `frame.swing` inputs are rejected under batch enrollment, and batches
are rejected without enrollment. Missing or duplicate symbol coverage cannot become
a partial-family entry opportunity.

Daily source coverage is 56–260 actual consecutive completed exchange sessions.
Base and MA share one frozen hourly source and count; levels use the same daily
source and derive their original complete calendar periods. Existing source,
receipt, calendar, volume, completeness, original target and contract rules apply.
The original batch is immutable. Current metadata/catalyst refreshes do not rewrite
it or extend original approval, session, expiry or carry deadlines.

Software enumerates every enrolled variant: base and each MA on CALL/PUT, high
levels on CALL, low levels on PUT, and weekly open on both sides with the existing
regime gate. Source defects reject the complete batch. A variant without positive
directional original risk/targets remains a blocked diagnostic; it is not silently
removed or repaired with a current quote. Every valid child retains its original
stop and fixed 1R/2R/3R objectives, full frozen policy hash and original batch hash.
Pure source derivation is cached with a bounded, exact serialized input key; no
account, approval, terminal, present-time or database evidence is cached.

## Native ownership and selection

The owner atomically locks all supplied original roots and their complete derived
children. Each symbol/session has one original root. Missing inputs, invalid source
or a conflict in any root cannot partially replace the batch. Separate tables keep
legacy single-seed rows unchanged. Native review and portable reconstruction rederive
the complete child set, including blocked and untraded variants, before using it.

Every setup keeps its own scan, admission, candidate ID and original terms, even
when several use the same instrument. Quote reads are deduplicated only when full
instrument identities agree; conflicting aliases reject the plan. Native review,
model opportunities and carry reconstruction join by exact family, symbol, right
and instrument. A paid proposal remains distinct from approval, attempt and fill.

Enumeration order follows frozen symbol order, then base, enrolled MA period order,
and enrolled level-key order; two-sided variants use CALL then PUT. The existing
Degen/Swing priority and Scope selection contract remain authoritative. There is no
new source score, automatic confluence ranking or extra per-family bankroll. Model
selection can choose any admitted family; deterministic selection retains its
ordered baseline. One cash ledger, reservation, position, cost budget and loss policy
own the result. Original stop/T1 retirement remains independent per child and survives
current-price recovery, runtime delivery and restart. Held protection stays independent
of new candidate collection.

## Bounds and stored evidence

The worst-case quote reservation counts two Swing contracts per symbol and must fit
the existing eight-quote limit, including the existing Scope tape allowance.
Wire tapes and runtime packets remain limited to 256 KiB, as do model requests.
The 24-candidate, token, cost and response limits remain unchanged; oversized
candidate/model requests fail closed rather than dropping candidates or increasing
budgets. The separately tagged joint journal record permits at most 30 scans,
30 read plans, 24 candidates and 4 MiB of expanded evidence. Legacy stored records
retain their 256 KiB bound. Observer scan capacity follows the frozen enrollment;
reading evidence creates no calls, approvals or orders.

A separate `DEGEN_SWING_BATCH` choice packet binds exact admitted-family scans.
Blocked diagnostics stay in the native journal; all model-visible opportunities
remain bounded and tool-less. Full entry/Scope/carry model contracts retain their
existing fresh post-cost admission and original deadlines. Old replay-model
restrictions are unchanged.

## Runtime, common tapes and export

Continuous runtime consumes the compact original batches through the existing
owned cycle and faster independent protection. Common CYCLE tapes retain complete
batch inputs; held-session cycles can carry the same original batch rather than
inventing a new seed. Account-free prefix replay preserves the first complete root
lock and per-child terminal history. It grants no account or execution authority.

Independent native A/B/C/D carry replay uses separate owners, balances, reservations,
fills, loss controls and model charges. Exports include original roots, the complete
child set and exact selected lineage; reconstruction rejects altered roots, missing
or substituted children, changed policies and wrong selected-family evidence.
Every entry/management charge, execution fee and explicit session/overnight allocation
is retained. Unknown usage and operating costs remain unknown.

The remaining major implementation is mixed stock/options ownership and its unified
runtime, settlement, recovery and independent accounting/export. Final UI and
authentic provider/model/host/economic/PAPER acceptance follow plumbing. LIVE stays
disabled and deployment frozen. See [testing](OPTIONS_TESTING.md) and the latest
[status](SLICE2_STATUS.md) for installed-wheel evidence and its limits.
