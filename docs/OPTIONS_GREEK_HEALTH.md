# Observed Greek evidence and pressure review

`OptionQuote.greeks` can retain an optional `OptionGreekObservation` with its own
source/receipt times, entitlement, completeness, exact instrument and provenance
(`OBSERVED`, `ESTIMATED` or `UNAVAILABLE`). The original quote, approval, model
packet, recorded fill and sealed tape retain this evidence. Omitted observations
keep legacy serialization and hashes unchanged. This is normalized fixture plumbing;
it does not add a provider adapter or estimate missing Greeks.

Explicit units are required: `theta_unit="USD_PER_SHARE_PER_DAY"` and
`volatility_unit="DECIMAL_FRACTION"`. Thus theta `-.10` means a quoted sensitivity
of ten cents per option share per day, not ten cents per contract; IV `.40` means
40%, not `.40%`. Delta remains signed and bounded between -1 and 1. Fields use
bounded Decimal values, with no float/bool/NaN coercion. Missing values remain null.
A Greek observation must bind the exact quote instrument, including provider mapping
and contract terms. These are declared normalized units, not proof of a real feed.

## Source-backed review

`app.options.greek_health.review_greek_pressure(entry_quote, current_quote, limits,
entry_at=..., now=...)` is a pure review. The fixed `observed-greek-pressure-v1`
reference adapts the Greek components of SignalFlow's v1 `assess_management` at
[`f9eaf2c1b5d13dca287ee7138126883065b00395`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_management.py).

| Component | Calculation | Reference thresholds |
| --- | --- | --- |
| Theta pressure | `abs(theta) / executable bid × 100 / 6.5` | At least 6% per reference hour |
| IV contraction | `(current IV / original IV − 1) × 100` | Warning at -15%; severe at -25% |
| Absolute delta deterioration | `(abs(current delta) / abs(original delta) − 1) × 100` | Warning at -20%; severe at -35% |

Threshold comparisons use exact products before display rounding. Metrics display
six decimal places. Caller Decimal precision cannot change decisions. A boundary
touch counts. CALL and PUT deltas must have the correct sign. A zero original delta
or IV cannot supply a ratio; a valid zero current value represents complete observed
deterioration. A genuine zero theta is distinct from missing theta.

The source's fixed 6.5-hour division is labeled a **reference heuristic**. It is
not an option-value forecast, an intraday decay model or the remaining length of
a real/half-day session. Positive theta follows the source's absolute-value rule.
No Greek metric proves a profitable trade or a safe position.

## Evidence gates and uncertainty

Both quote and Greek sources must match the owner's option source. Each must be
complete, REALTIME and fresh under the owner's existing quote-age/receive-lag
limits; the Greeks must additionally be OBSERVED, received by quote receipt and
synchronized to the quote source time. Estimated observations may be retained as
evidence but cannot satisfy this review. A fresh, positive, sized, uncrossed bid is
required; ask/midpoint/last cannot substitute for it.

The entry observation is checked at the original preparation time, not against
today's clock. The current quote must match that original instrument and contain
post-entry source observations. Old, future, delayed, unsynchronized or missing
current evidence is incomplete. The tape rejects foreign Greek sources and
observations unavailable by the containing quote's receipt, preventing future
Greek evidence from being introduced into an earlier recorded event.

`status=READY` means these Greek inputs are available. It never means overall trade
health is good. Valid pressure flags may be true on a READY result. `INCOMPLETE`
retains explicit reasons and null flags for unavailable components. An independent
valid component can still produce a flag when another is missing. For example,
current theta pressure can be known while original IV is absent. The
`known_warning_count` counts only the three available warning components; it is
neither the source's full divergence score nor an overall health rating.

Every result retains `execution_authority=false` and `live_enabled=false`, hashes
of supplied quotes, original/current Greek evidence and evaluation times. It does
not attach an account, consume model calls, change stops or floors, latch an exit
or prepare/dispatch an order. Position accounting, fees and model charges are
unchanged.

## Stored observer and native replay

When an owned entry or its latest stored quote contains Greek evidence, the observer
adds `position.greek_pressure`. It binds the baseline to the exact original entry
approval and matching preparation inputs. It does not backfill an old missing
baseline from later quotes or selection metadata. Conflicting latest observations
withhold current signals; stale evidence stays incomplete. Invalid baseline binding
makes the report unavailable. Existing `ContractMetadata.delta` selection/profile
gates remain independent and are not replaced by this optional evidence.

The observer uses the existing bounded frame/decision search in one read snapshot.
Reads compute diagnostics only; they do not refresh market evidence, alter native
state or contact a model, venue or provider. Detached journal copies work without
an execution owner. The authenticated stored API exposes the fields; dedicated
HTML/dashboard visual treatment remains part of the UI pass.

Native fixtures verify entry-to-fill storage, exact baseline identity, read-only
copies, seal tamper rejection and independent A/B/C/D replay with Greek-bearing
market quotes. All entry and management charges remain attributed through the same
native economic report; unknown costs and data/host allocations retain their
existing semantics. The test fixtures are not authentic provider/model acceptance.

## Remaining management gate

This closes the missing normalized Greek evidence and diagnostic-calculation part
of health management. [Durable progress diagnostics](OPTIONS_PROGRESS_HEALTH.md)
now retain original underlying risk geometry, progress/stall/peak history and
premium divergence/giveback. Full source health still needs remaining liquidity/session
context and composition, plus frozen enrollment and native execution/restart/replay acceptance for
any health-driven stop or exit. No partial Greek score enables those actions.
Scope watch/entry linkage, full path proof, the missing four-contract T3, family
loss/reset, provider/host evidence, prospective economics and the dedicated UI pass
remain open. Main untouched, PR #1 draft, LIVE disabled and deployment frozen.

See [whole-trade floors](OPTIONS_TRADE_FLOOR.md), [premium trails](OPTIONS_PREMIUM_TRAIL.md),
[stored observer](OPTIONS_OBSERVER.md) and [source of truth](SOURCE_OF_TRUTH.md).
