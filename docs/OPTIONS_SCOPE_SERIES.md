# Continuous Scope session replay and comparison

`app.options.scope_series` extends the independent Scope A/B/C/D fixture comparison
across two to sixty declared sessions. Each arm creates one native owner, journal,
venue and model adapter for the entire series. Capital, settled funds, reservations,
positions, orders, paid usage, high watermark and global/family loss controls remain
continuous. No account or strategy is reenrolled at a session boundary.

This is offline execution plumbing with supplied fixtures. It does not establish
authentic data/model, economic, PAPER host or LIVE acceptance.

## Frozen inputs

`ScopeSeries.sessions` contains ordered `ScopeComparison` requests. Every session
retains the same four distinct account/population identities, native policies,
original capital, fees, family configuration, source/universe limits and original
experiment declaration. The tapes retain their own actual calendar session and
original Scope cutoff/protection deadlines. Watch action identities are unique
across the series; approvals and account revisions are always computed by the
individual native owner.

Each model arm declares its complete bounded script in advance, identically in
every session request. Every scripted slot must occur in a declared tape. C/D entry
choices, delays and usage match, with D's separately paid management. B retains its
fixed SELECT/HOLD contract. The new `scope-native-series-model-v1` enrollment binds
the full ordered tape hashes, entire comparison request and complete per-arm script.
No mutable per-day script or model configuration is substituted into a frozen owner.
Existing single-session enrollment, prompt/schema identities and scripts are unchanged.

`settlements` accepts only explicit per-arm `ScriptedSettlement` funds credits,
timed between declared sessions. The native venue checks the actual unsettled funds,
terminal history and next receipt sequence. No inferred T+1 cash, proceeds sweep,
expiry/exercise receipt, price mark or profitable result creates a credit.
Settlement changes available funds, not profit.

## Execution and boundaries

Call `await run_scope_series(request, new_absolute_directory)` from an installed
wheel. The runner is create-only and executes arms serially with independent virtual
clocks. Every session gets empty market/held-context caches and a new delivered-Scope
reader. Previous-day quotes cannot fill orders or satisfy fresh paid admission.
The existing receipt-first, later-quote, model-deadline and independent-protection
rules still apply. Scope's original same-session terms never become overnight terms.
An unresolved holding remains owned and blocks entry; a new session does not make it flat.

After each completed arm/session, the runner saves an evidence-only SQLite closing
snapshot and a native full-cost export, plus scheduler, watch-action and delivered
fresh-read receipts. Snapshots contain no restore authority companion. The complete
series retains `inputs.json`, each account's native files and `series.json`/`report.json`.
An interruption preserves completed boundaries and `interrupted.json`; it never
publishes a successful series or authorizes resume/retry.

## Portable continuity and accounting

Retain `series_hash` independently and call
`verify_scope_series(bundle, expected_series_hash)`. Verification reconstructs every
native export and checks exact owner/model/strategy enrollment, completed tape
boundaries, declared settlement receipts and cumulative operating allocations.
Later exports must preserve the prior event prefix and every immutable economic
row. Original order authority, terminal orders and watch identities remain bound.
Backdated new orders, calls, cycles or fills cannot be silently assigned to a later
day. Historical correction/revaluation remains unsupported.

Each session report opens from the previous native closing ledger. It includes the
new execution fees and every new entry/management charge, plus that session's
explicit data/host allocations. Cumulative native totals subtract those allocations
once across the full series. An unknown earlier allocation or model cost stays
unknown. Open/unresolved exposure keeps accounting incomplete. Paired series results
require all four accounts and every boundary to be complete and flat; complete
individual account totals remain separately visible when another account is unknown.
The economic conclusion is always `INCONCLUSIVE`.

The new series enrollment also distinguishes a verified later entry request made
on a flat account from a prior closed trade. Its charge remains in account totals
and unallocated diagnostics until it gains its own entry attribution. It cannot
reopen the earlier trade's loss outcome while fresh paid admission is pending.
Management, overlapping/unproven calls and all legacy cohorts retain their existing
conservative behavior; unknown usage still blocks account-level completeness.
The separate [native repeated-entry policy](OPTIONS_NATIVE_ENTRY_ATTRIBUTION.md)
now adopts this post-close proof for new full-entry owners. Neither enrollment
silently changes existing runtime cohorts.

SPY comparison requires actual complete real-time tape quotes at both session
endpoints, using the existing five-second source/receipt rules. Missing/stale endpoint
evidence is not interpolated. The report retains per-session midpoint price returns
and their compounded series return only when every endpoint is known. This excludes
overnight gaps, dividends and benchmark execution costs; it is not buy-and-hold
total return. Cash price return is zero. No confidence, profitability or promotion
claim follows from fixture arithmetic.

Requests are bounded to 64 MiB, native exports retain existing row/file bounds, and
the portable series is bounded to 256 MiB. Each session retains the existing
900-second native execution deadline. Capacity failures preserve partial evidence.

## Remaining boundaries

This version covers the existing session-close Scope/Degen/Swing replay contracts.
Combined Scope/Swing carry remains rejected by these replay requests, including B's
original choice-only contract. The separate [combined carry series](OPTIONS_SCOPE_CARRY_SERIES.md)
now binds its own full enrollment, marked B policy and explicit overnight costs;
this version does not lift its historical restrictions. Broader family completion, mixed stock/options
ownership, statistical/authentic acceptance and final UI remain separate work.
LIVE stays disabled, the deployed experiment frozen, PR #1 draft and main untouched.
