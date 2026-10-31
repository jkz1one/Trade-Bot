# Native Swing source preparation

The collector can now bind retained pre-open history to native stock Swing
sources, single option seeds or complete option-family batch roots. Both the
standalone collector and coordinated runner pass the enrolled runtime settings
to this step after collection. It makes no additional provider or model calls.

This is source preparation, not completed strategy delivery or trading readiness.
The subsequent [runtime assembly](SWING_RUNTIME_DELIVERY.md) joins verified
originals with current metadata/quotes and explicit typed catalysts. Actual
catalyst provider/provenance delivery remains work.
The actual history mapper still emits UNKNOWN entitlement, so its current output
correctly produces a BLOCKED receipt with no prepared sources or seeds.

## Original evidence and native checks

`bind_sources` accepts typed original history and a policy bound to the full
runtime-settings hash, exact stock identities and explicit candidate contracts.
It requires the complete symbol set, original source/receipt clocks and creation
after capture but before the target session opens. It never backdates a late
preparation or promotes UNKNOWN entitlement.

Each native policy gets exactly its enrolled lookback from the end of the retained
history. OHLC, volume, source timestamps and receipt times remain unchanged. Stock
sources use the existing native validator. Option seeds use the existing native
target builder and validation. Complete batches run every enrolled variant through
the original batch builder before retaining their common root; no family is
silently omitted. Hourly evidence is required only for families that use it.

Contracts must match the source symbol/provider and native DTE/contract rules,
with reviewed metadata and tradability. A single-source enrollment requires one
exact eligible contract. A complete batch requires exactly one CALL and one PUT.
Ambiguous choices are blocked rather than resolved by list order. Multiple MA or
level variants require complete-batch enrollment or an explicit single variant.
Carry dates are not invented; a policy needing them stays blocked without an
explicit original exit session. [Connected carry schedules](CONNECTED_CARRY_INTENT.md)
now provide that explicit input; operational schedule enrollment remains unfinished.

PREPARED means the original sources passed their native source validators. It
does not indicate a confirmed signal, fresh catalyst clearance, executable quotes,
available account capacity or entry approval. Every receipt retains
trading_ready=false and live_enabled=false. If any required source fails, the
result records blockers and publishes no partial set of prepared sources.

## Durable preparation and restart

The collector stores an original per-session result in its additive
swing_source_bindings table. Runtime configuration and original history hashes,
creation time, exact sources/seeds and blockers are retained. Existing capture,
history and execution tables are not rewritten or migrated.

The collector reuses the result after restart, including a blocked result. Reading
it rebuilds the binding from the retained raw-verified history and enrolled
settings at its original creation time. Changed configuration, source evidence,
targets, status or a rehashed result is rejected. Restart cannot restamp the
preparation or upgrade unknown evidence. `load_swing_sources` returns the full
verified typed original without creating or refreshing a result. Historical reads
remain distinct from current-session eligibility.

If no original history exists, the collector reports
SWING_PREOPEN_HISTORY_UNAVAILABLE and does not fabricate a source. Missing
entitlement produces explicit per-symbol blockers. Neither path opens a broker
account, changes virtual cash, resumes an entry halt or submits an order.

## Validation and remaining work

SWING_SOURCE_BINDING_PROOF.json records installed offline validation. Eligible
synthetic histories produce native sources and all 14 option variants in the
enrolled fixture. The real-schema normalization path retains UNKNOWN entitlement
and stays blocked across restart. Tests cover single derived targets, missing and
ambiguous contracts, clocks, duplicate subjects, insufficient history, carry
requirements and rehashed-result rejection.

Runtime assembly and separate Degen/Swing expiry routing are implemented in the
subsequent delivery slice. Still required: catalyst provider/provenance delivery,
operational carry schedule rollover, Scope feeds, reviewed data eligibility, dynamic
replacement contracts and operational setup. Actual daily/hourly response
acceptance also remains pending. The host is still the a653cc7 frozen dashboard.

This publication is a **slice end**. More offline code can be implemented; it is
not a request to repeat collection or a claim that connected trading is ready.
