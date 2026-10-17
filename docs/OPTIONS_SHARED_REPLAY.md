# Shared Degen/Swing research replay

The optional shared-family tape now drives the existing independent A/B/C or
A/B/C/D PAPER replay owners. Each account has one coordinator, cash ledger, order
reservation and model budget spanning Degen and Swing. Accounts do not share cash,
fills, model calls or settlement receipts. This extends the
[shared strategy contract](OPTIONS_SHARED_STRATEGIES.md) and
[multi-session replay](OPTIONS_REPLAY_SERIES.md); it does not create an additional
trading engine or change previously frozen Degen cohorts.

## Frozen common inputs

Set `TapeHeader.swing` to the approved `SwingPolicy` when creating a new tape.
Omitting it preserves the historical header serialization and digest. Every tape
in a series must retain the same Swing policy, Degen setup, contract-selection
policy and market limits. Native export also binds each journal's frozen Swing
configuration to its tape. Removing or replacing the policy and resealing the
tape cannot relabel a shared native account as Degen-only.

Cycle frames may contain the existing `DegenFrame.swing` inputs. Recording checks
unique scoped symbols, exact seed/metadata contracts, daily/catalyst/metadata
sources and all source/receipt/creation clocks. Daily bars must already be complete
when their history was observed. Future evidence is rejected. Missing, stale,
blocked or otherwise ineligible evidence remains subject to the normal shared
coordinator's gates; a tape never grants admission. Swing evidence without frozen
enrollment, and daily/seed evidence in quote-only MARKET events, are rejected.
The common eight-contract quote bound includes both families.

`replay_shortlist` now returns both families in the frozen priority order. It uses
only the recorded prefix available at the requested instant and retains the first
valid supplied seed per symbol/session. A missing seed or a conflicting replacement
is explicit and suppresses partial-family plans. This market-only diagnostic has
no account state or execution authority: held-position priority, native seed locks,
cash, costs and fresh preparation/dispatch checks belong to each actual replay
owner. It does not predict whether a particular account can trade.

## Matched comparison roles

| Arm | Shared-family behavior |
| --- | --- |
| A | Deterministic frozen family/setup priority; no model calls. |
| B | Scripted SELECT/HOLD among admitted candidates from both families; no geometry changes. |
| C | Scripted full entry plan over the same common candidate universe. |
| D | C's exact entry script and configuration, plus paid position-management proposals. |

B's optional shared comparison uses an explicit `DEGEN_SWING` packet and
`shared-candidate-choice-v1` prompt identity. Its candidate types and family scans
are checked together; a Swing contract must match its locked seed. The historical
Degen SELECT/HOLD packet, prompt and hashes remain unchanged. Narrow shared
selection is allowed only in the isolated scripted replay comparator. The normal
shared runtime continues to require full-entry AI or model-off operation.

Replay models remain tool-less scripted fixtures. Synthetic token counts and
delays cannot establish authentic model quality, pricing receipts or latency.
Scripts select one supplied candidate or HOLD; deterministic software still owns
quantity, full-premium funding, original limits and independent protection. Each
owner processes later quotes on its own virtual clock, including partial fills,
delayed decisions, uncertainty, model deadlines and unresolved orders.

## Continuity, attribution and costs

The same native accounts continue across sessions. A new Swing seed is associated
with its own actual target session; no cash, settled funds, fees, model budget,
halt or previous audit row resets at the next open. Only explicitly supplied and
validated funds-settlement receipts may increase settled cash.

The existing exporter retains proposal, deterministic review, order attempt and
observed fill attribution, including D's management proposals. It charges every
known entry and management call exactly once and retains unknown charges as
unknown. Spread, slippage, venue fees and supplied data/host allocations continue
through the common cash-conserving evaluation. Another family cannot bypass an
account's unknown-cost halt. The other research accounts remain independent.

Shared export adds `strategy_universe` with the two family names, frozen Swing
policy hash and `SESSION_CLOSE` holding policy. This identifies the joint cohort;
it does not allocate common costs into hypothetical standalone family returns.
Existing installed replay/export commands and private create-only input/output
rules are unchanged. Complete arithmetic still does not imply economic acceptance
or promotion: the conclusion remains INCONCLUSIVE without the required evidence.

## Remaining boundaries

This is shared **session-close LOCAL_FIXTURE** replay. It does not enable overnight
Swing, additional Swing setups, Scope/SPXW or mixed stock/options ownership.
Authentic daily/catalyst/option collection, real model evidence, prospective
enrollment/economics, target-host acceptance and dashboard visual acceptance remain
separate gates. LIVE stays disabled, main and the deployed experiment stay untouched,
and PR #1 remains draft. Exact installed verification is recorded in
[SLICE2_STATUS.md](SLICE2_STATUS.md).

## Optional family loss evidence

The same native loss policy must be frozen across all comparison arms. Optional
Degen/Swing family rules remain additive to each account's global loss guard.
Closing snapshots now retain cumulative loss state, exact consumed-entry lineage,
recognition times, entry pauses and reviewed-reset summaries. A lock in one arm
cannot reset or lock another account. Session transitions do not clear locks or
refund calls. The two-session fixture covers A/B/C/D preservation, including D's
entry and management charges and later unpaid entry pauses.
See [native risk export](OPTIONS_EVALUATION_EXPORT.md#native-loss-control-evidence)
for validation, capacity and provenance limits.
