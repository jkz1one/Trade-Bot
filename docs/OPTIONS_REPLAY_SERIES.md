# Multi-session native replay and export

Delivered P3 extension, 2026-10-12 UTC. The [replay scheduler](OPTIONS_REPLAY.md)
now runs an ordered series of sealed market tapes on the **same** three native
PAPER accounts. The [native exporter](OPTIONS_EVALUATION_EXPORT.md) reconstructs
each session from a saved closing journal, instead of treating the latest ledger
as every day's closing balance. All market/model/settlement inputs remain explicit
local fixtures. No authentic AI performance or profitability is established.

The optional [arm D extension](OPTIONS_MANAGED_REPLAY.md) applies these same
continuity rules to four independent accounts and includes management costs/attribution.
Optional [shared Degen/Swing tapes](OPTIONS_SHARED_REPLAY.md) now apply those same
rules to the joint session-close strategy universe, frozen identically across sessions.

## State and settlement

`await run_replay_series(settings, tapes, new_directory)` accepts the existing
`ReplaySettings`, with a manifest containing one to sixty ordered complete XNYS
sessions and exactly matching tapes. Experiment identity, original declaration,
setup, contract selection and market limits must agree throughout. Three owners
are created once. Capital, settled cash, position, high watermark, realized P&L,
fees, daily history, model attempts/costs, halts and event sequence continue across
the series. A new session never reenrolls a strategy or resets an account.

Each arm runs every session on its own clock and original native journal/venue.
Quotes from the previous session are cleared from the replay cache. The existing
rules for subsequent-quote fills, equal-time receipts, model leases, uncertainty
and independent exits still apply. A carried position stays owned and blocks new
entry. There is no invented overnight mark, expiry close or physical-exercise
receipt. Open boundary positions keep economic comparisons inconclusive.

`ReplaySettings.settlements` optionally supplies `ScriptedSettlement(arm,
receipt)` entries. Only positive `FUNDS_SETTLED` receipts with no contract,
quantity or settlement value are accepted. Each must name an exact arm, unique
receipt ID, native event sequence, amount and time between a preceding session's
close and the next open. At application it must follow the retained prior
boundary. The existing venue requires complete terminal order history, the next
sequence number and an amount no larger than actual unsettled funds.

There is **no inferred T+1 credit**, assumed settlement schedule, automatic sweep
or credit calculated after seeing a profitable result. No receipt means proceeds
remain unsettled. Settlement changes spendable cash, not total cash or P&L. These
scripted receipts are frozen in admission before any replay; they are not broker
confirmations. Invalid timing/sequence/amount stops the run and leaves evidence.

Model usage remains separate from venue cash and is deducted exactly once in
net comparison accounting. An unknown earlier charge retains its native entry
halt and remains unknown in the earlier row. A later session cannot erase it or
restore complete series totals. Data/host allocations apply per arm per session;
missing allocations are never silently zero.

## Closing evidence and continuity

After each arm/session finishes with no active cycle task, the runner creates
`ARM/sessions/YYYY-MM-DD.db` using SQLite's consistent backup API. The source is a
read transaction; the destination is a new mode-600 file, bounded by the existing
64 MiB journal capacity and a five-second copy deadline. Files and their containing
directory are fsynced. A small matching JSON receipt retains the capture time and
scheduler outcome. No restore authority companion, venue or key is copied into
these snapshots. They are evidence, not usable execution backups or proof of
off-host retention. Live fixture sources remain in the arm directory.

`export_series(manifest, tapes, sources)` reads these private snapshots without
opening an execution owner. `sources` maps each session key to A/B/C source
entries with `journal`, `data_cost` and `host_cost`. Every declared session needs
all three sources and the exact ordered tape. Each snapshot is internally
consistent; this is not a global transaction across three independent accounts.

For each arm, the exporter validates the full cumulative native audit, then
extracts only new orders, calls, cycles and receipts. The first opening ledger is
original capital. Every later opening ledger is exactly the preceding exported
closing ledger, including settled funds and unresolved exposure. Between-session
funds receipts belong to the following session and continue the global sequence.

Later sources must preserve the previous audit prefix, native configuration/owner
identity and every earlier economic row exactly. Removing an unknown call,
replacing a venue, altering an old order, resetting cash or omitting/reordering a
boundary cannot produce a complete comparison. Source receipts include event,
configuration and export hashes and the preceding export hash. These bind supplied
content; they do not authenticate a provider or defeat coordinated owner tampering.

Historical corrections, such as a newly discovered fill or newly settled model
usage for an earlier boundary, currently make export unavailable. They are never
silently charged to a later day or used to rewrite a saved close. Existing sources
remain available for review. A correction/revaluation protocol is not implemented.
Exercise/expiry settlement simulation is also outside this extension.

The existing paired evaluator independently replays all fills/receipts from the
original bankroll, checks sequences and opening continuity, charges known costs
once and keeps incomplete sessions in the denominator. An incomplete session
withholds whole-series totals. SPY remains session-only compounded midpoint price
return, not buy-and-hold total return. The economic conclusion stays INCONCLUSIVE
even after the manifest's minimum sample count is reached.

## Installed interfaces and bounds

The existing replay command now also accepts a private request containing
`settings` plus an ordered `tapes` array of absolute tape paths. Legacy `tape`
requests remain supported; using both forms is rejected. The installed command
and create-only output-directory behavior are unchanged.

The export CLI additionally accepts `SeriesExportRequest` with `manifest` and
ordered `boundaries`. Each boundary contains `session_key`, absolute `tape`, and
three existing `ExportSource` records. Legacy one-session export requests retain
their original API. Both CLIs retain exit 0 for complete arithmetic, 1 for
inconclusive and 2 for sanitized unavailable input/evidence. Neither deploys or
starts a service. The replay CLI still requires a new output directory.

Requests remain private and bounded to 256 KiB. Each tape retains its 32 MiB and
4,096-event bounds; tapes are loaded incrementally with a 64 MiB combined bound
and sixty-tape ceiling. Existing native venue, journal, audit, observer-read and
16 MiB comparison-bundle capacities still apply to the cumulative series. The
runner does not prune/reset history to fit a bound. A capacity failure leaves
admission and completed snapshots without a final result. The per-arm/session
wall deadline remains 900 seconds.

## Next

[Position reasoning and durable management](OPTIONS_POSITION_REASONING.md) now
have fixture proof, including atomic revision consumption and native PAPER exits.
Arm D replay/export and stored proposal/approval/fill attribution are now
implemented. The A/B/C exporter still rejects managed cohorts labeled as arm C;
four-arm export requires explicit D enrollment.
Authentic normalized market/model evidence,
continuous options runtime, finished UI, prospective evidence and host/recovery
acceptance remain separate gates. LIVE stays disabled and the deployed population
stays frozen. See [source of truth](SOURCE_OF_TRUTH.md) and [measured proof](SLICE2_STATUS.md).

## Optional eligible underlying comparison

The [long-underlying baseline](OPTIONS_UNDERLYING_BASELINE.md) can be frozen in
`manifest.underlying_baseline`. Replay/export then includes its independent
continuous cash/share report from the same tapes and A-approved opportunities.
Optional `underlying_settlements` carry only that account's own explicit receipts;
options-arm settlement and model charges remain separate. Missing share sizes
never become assumed fills. See the contract for enrollment and cost fields.

## Optional loss-control continuity

When the manifest's matching execution policies enroll native loss controls,
each independent owner refreshes those controls after the session's final native
reconciliation and before saving its boundary. This consumes newly complete losses
at the actual replay recognition time, including a final close with no later entry
cycle. Pending outcomes and unknown costs remain pending. A late task still retains
its real clock; it cannot backdate a review to the session close.

The next session inherits account-wide and family streaks, cooldowns and sticky
locks along with cash, fills, costs and audit history. Replay does not issue an
operator reset or clear a lock overnight. A paused entry call creates no paid
attempt; already admitted calls and D's management charges remain in economics.
Boundary export now carries [audit-bound native risk evidence](OPTIONS_EVALUATION_EXPORT.md#native-loss-control-evidence).
Previously unenrolled policies retain their prior behavior and omitted fields.
This is LOCAL_FIXTURE proof, not provider, host, strategy-profitability or LIVE acceptance.

## Common Scope input checkpoint

[Sealed Scope observations](OPTIONS_SCOPE_MARKET_TAPE.md) now freeze their source/watch
policy and session deadlines and support original-time diagnostic reproduction.
The separate [native C/D tape path](OPTIONS_SCOPE_MODEL_REPLAY.md) now binds full
model receipts, delivered fresh post-cost admission, original deadlines, later fills
and native full-cost export. This does not complete independent A/B/C/D comparison;
B and the matched comparison wrapper remain open. Existing comparison consumers
still reject Scope tapes, and the old/unbound model adapters remain blocked.

## Independent Scope comparison continuation

The [Scope A/B/C/D comparison](OPTIONS_SCOPE_COMPARISON.md) now adds explicitly
enrolled choice-only B and matched independent one-session native replay/export.
The historical runners and C/D contracts described above retain their original
versions and rejection boundaries. The separate wrapper preserves unknown costs,
all native fees/charges and inconclusive economic status. Continuous Scope runtime
inputs, carry/family/mixed plumbing and authentic acceptance remain open.
