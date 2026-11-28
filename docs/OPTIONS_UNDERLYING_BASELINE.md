# Eligible long-underlying comparison

Delivered offline P3 comparison, 2026-10-12 UTC. The existing paired evaluator,
replay and native exporter can explicitly enroll one separate long-share account.
It uses A's approved deterministic CALL opportunity schedule and the same sealed
market tape. It does not create another execution owner or touch any brokerage,
deployed population or LIVE configuration. All evidence remains `LOCAL_FIXTURE`.

## Frozen identity and comparison meaning

Set `EvaluationManifest.underlying_baseline` to `UnderlyingBaselinePolicy` before
replay. Its account and population IDs must differ from every options arm. Freeze
its positive share tick, whole-share cap, entry/exit per-share and per-order fees,
and explicit per-session data/host allocations. Missing allocations remain unknown.
Omitting the policy returns `NOT_ENROLLED` and preserves legacy manifest hashes.

The comparator starts with A's original virtual capital, but owns its resulting
cash, settled funds and shares independently. A's prepared BUY intents supply the
opportunity time, symbol, original underlying invalidation and exit deadline.
Only US-listed EQUITY/ETF CALL opportunities qualify. PUT and index opportunities
remain cash; no short stock, index substitution, fractional shares or borrowing.
It does not depend on whether the option subsequently fills, how much it fills,
or when an option premium stop closes it. One share position or pending entry
blocks another; skipped opportunities remain in the report.

This is an **A-approved opportunity benchmark**, not a separately rerun stock
signal strategy, an AI-selection ablation or a claim that stock and option risk
are equivalent. The schedule still reflects A's own options admission/occupancy.
A/B/C/D keep their own native positions and all entry/management model charges.
The deterministic share comparator makes no model calls and reports zero model cost.
SPY midpoint/session price return and cash price return remain separate measures.

## Fills, risk and exits

The quote available at preparation sets an adverse-slippage, upward-tick-rounded
entry limit. The original A approval lifetime, session entry cutoff and earliest
exit deadline bound entry. Whole quantity fits the separate settled balance and
the matched entry/exposure/full-loss caps, remaining daily/total loss envelope,
share cap, entry fees and reserved exit fees. Known allocations count against
loss headroom. A budget smaller than one share stays cash; the evaluator does not
relax the frozen ceiling to force participation.

`UnderlyingQuote` now permits optional `bid_size` and `ask_size` in **shares**.
Absent sizes are omitted from serialization, preserving existing tape hashes and
price-benchmark behavior. Provider normalization must supply actual sizes before
an executable underlying comparison is accepted; no option size is reused.

Fills require a quote recorded by fill time with a source timestamp strictly after
the relevant decision, matching source/symbol, real-time entitlement, completeness,
freshness, receipt lag and valid bid/ask. Entry also enforces minimum price and
spread limits. Ask plus adverse slippage, rounded upward to the frozen tick, must
fit the entry limit. The first executable quote fills up to its observed size;
unused entry quantity is canceled instead of added later. Known zero size or an
unmarketable limit is not a fill. Missing executable size is incomplete evidence,
including when a later stop cancels entry. No midpoint or stale decision quote
substitutes for an executable fill.

The independent underlying stop or earliest original/session exit deadline latches
a full exit. A subsequent fresh bid supplies sale price, adverse slippage and
downward tick rounding. A stop-trigger quote cannot also fill its own new exit.
Partial exits retain owned shares; the per-order exit fee applies once and
per-share fees apply to every sold share. Repeated source timestamps, including
a changed receipt timestamp, cannot supply additional size. A low-priced held
asset can still exit even when it no longer qualifies for a new entry. Unknown
exit liquidity, an unavailable fee-paying sale or open closing exposure remains
inconclusive, with no invented liquidation mark.

## Continuous accounts and output

Sale proceeds increase cash but remain unsettled. Optional
`UnderlyingSettlement(receipt_id, occurred_at, amount)` evidence belongs in
`EvaluationBundle.underlying_settlements`, or in the corresponding
`ReplaySettings` / single- or series-export request field. Export functions accept
the same keyword. Receipts have distinct IDs, occur strictly after a preceding
close and no later than the next open, and cannot exceed this account's unsettled
cash. They never consume an options arm's receipt or create profit. No inferred
T+1 credit, automatic sweep or session capital reset exists.

The report's `eligible_underlying` section retains every session, opportunity
outcome, source-linked fill/quote hash, fees, turnover, realized price P&L,
allocation, settlement and closing state. It reports per-session arm-minus-share
net differences and complete-series net return, worst session and session-boundary
drawdown. Arm totals include net return excess versus the share baseline when the
entire enrolled comparison is complete. A missing tape, incomplete A/source
evidence, missing cost/size, invalid credit or unresolved position suppresses the
enrolled comparison totals. An incomplete baseline session blocks a later restart.
Economic conclusions remain `INCONCLUSIVE`, even for complete fixture arithmetic.

Use the existing evaluator with `--bundle` and all session `--tape` inputs. Native
replay/export includes the baseline report automatically when enrolled. Neither
path opens a share trader, creates share authority or submits orders. Tests and
wheel identity are in [status](SLICE2_STATUS.md). Actual data/model acceptance,
whole-session statistical/prospective evaluation, continuous options runtime/UI,
host acceptance and the remaining families/dashboard remain separate gates.
