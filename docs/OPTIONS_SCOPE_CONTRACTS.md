# Scope exact-contract profile review

`scan_scope_contract(frame, context, policy, now=...)` recomputes Scope quality and
reviews the exact supplied SPXW contract for each setup alternative. It is a pure
research eligibility check, with false trade/LIVE authority. It creates no shortlist,
quantity, order price, debit approval, model request or execution candidate.

`ScopeContractPolicy` freezes the complete quality policy, ordered minimum/cheap/
medium/maximum ask thresholds, a midpoint-spread ceiling, and volume/open-interest
minimums. Prices stay inside the pinned research envelope of $0.20–$5.00; spread
must not exceed 15%. The source baseline cheap/medium ceilings are $1.25/$2.50.
All values are explicit rather than silently applied to an existing account.

## Evidence and classification

Full preflight, structure, context and quality gates run first. Same-day PM SPXW
identity, exact metadata/quote matching, fresh sources, supported contract ticks,
current two-sided quotes, directional confirmation and target-two strike
reachability remain binding. A profile cannot rescue a failed upstream check.

Observed, nonzero, correctly signed delta is required. Estimated/missing delta
cannot become a ranking default. Volume and open interest must both be known and
meet their frozen minimums, even if those minimums are zero. Zero is a supplied
measurement; absence is not zero. These stricter missing-data rules are explicit
conservative adaptations of the pinned source.

Ask bounds are inclusive. Spread compares exact Decimal products against
`(ask - bid) / midpoint`; rounded display values cannot change eligibility. The
preflight spread limit also remains binding, even if it is stricter than this
profile policy.

The classification order follows the pinned
[SignalFlow implementation](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard.py):

| Condition, in order | Profile | Reference absolute delta |
| --- | --- | ---: |
| Reversal with absolute delta at least .35, or any setup at least .48 | Responsive | .50 |
| Ask at/below cheap ceiling, score at/above convexity threshold, and strike beyond target one or absolute delta below .25 | Convexity | .18 |
| Ask at/below medium ceiling | Balanced | .32 |
| Remaining otherwise eligible contract | Responsive | .50 |

Reference deltas describe the source profile; they are not hard maximums or a
computed ranking. Higher observed delta is allowed inside the other limits.
CALL/PUT direction determines whether the strike is beyond target one. Every
alternative retains its own pattern, parent and direction, plus explicit reasons.

Convexity is classified but **always rejected while complete path evidence remains
unproven**. Today's quality scan deliberately reports `complete_path_proven=false`.
Neither an A+ score nor the absence of supplied obstacles overrides this blocker.
No failed convexity contract falls back to another profile to bypass the gate.

## Frozen watch integration

New `ScopeWatchPolicy.contract` enrollment requires the identical nested quality
policy already enrolled by the watch. Old cohorts omit this optional field and
cannot enable or change it on reopen. A successful call stores the full contract
scan; a rejected call consumes no play, revision or audit event.

When arming is also enrolled, each sample recomputes current contract eligibility.
A failure persists the full scan and resets the hold. The original instrument and
geometry stay locked. Current profile classification may change with fresh
observed delta/price; it grants neither a replacement instrument nor position size.
Exact retries, revisions, owner readiness, global limits and restore fencing remain
in force. Explicit price-only advancement cannot grant contract eligibility.

## Still required

This completes supplied-contract profile gates, not native Scope admission.
[Owned account admission review](OPTIONS_SCOPE_OWNED_ADMISSION.md) now stores
common-governor sizing, fees/slippage and debit checks for fresh armed evidence.
Native dispatch, full entry/management cost and filled-position/loss/cooldown linkage, full obstruction coverage,
common-owner Scope execution/runtime/replay and stored observer integration remain
open. The source's premium-based quantity ceilings now narrow the common governor;
its floating-point rank score is not a competing account calculator. The existing deterministic owner
must approve all costs and quantities; unknown costs cannot become zero.

Independent A/B/C/D ledgers and shared Degen/Swing execution are unchanged. Authentic
provider/calendar/model, host, visual and prospective acceptance remain separate.
See [watch lifecycle](OPTIONS_SCOPE_WATCHES.md), [arming](OPTIONS_SCOPE_ARMING.md),
[quality](OPTIONS_SCOPE_QUALITY.md) and [status](SLICE2_STATUS.md). Main untouched,
PR #1 draft, LIVE disabled and deployed experiment frozen.

[Scope management previews](OPTIONS_SCOPE_MANAGEMENT.md) now use the selected
contract profile for explicitly enrolled premium limits and the independently
selected balanced sizing profile for allocations. The native entry premium
primitive only tightens owner protection. Four-contract Scope plans retain an
unresolved third objective; no plan bypasses convexity or native execution gates.
