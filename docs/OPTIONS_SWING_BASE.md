# Native daily base breakout/breakdown

`SwingPolicy.daily_base` explicitly enrolls `swing-daily-base-v1` for a new PAPER
owner. The existing small `SWING_DAILY_BREAKOUT` adaptation remains frozen. The new
`SWING_DAILY_BASE` candidate enters the same Degen/Swing/Scope selection boundary,
native account, paid model slot, reservation, fills, management and loss accounting.
It does not create a second Swing worker or share cash between research accounts.

## Pinned setup rules

The source is SignalFlow commit `f9eaf2c1b5d13dca287ee7138126883065b00395`,
`backend/platform/setup_engine.py`, blob `af7912bc06dbf0bee94c148cfe7fb1540842d85b`:
`evaluate_daily_base_breakout`, `build_trend_context`, `atr_series` and `_targets`.
Rules are fixed by the enrollment version, not tunable per cycle.

| Rule | Required original evidence |
| --- | --- |
| Base | Fifteen completed sessions preceding the signal day; width at most 12% of midpoint and 6.5 times average ATR |
| Boundary | Signal-day close above the base high for CALL, below the base low for PUT |
| Close strength | At least 70% of the daily range for CALL, at most 30% for PUT |
| Volume | At least 1.20 times the prior twenty-session average; observed positive volume throughout |
| Extension | Signal close no farther than 1.25 prior-day ATR beyond the boundary |
| Regime | Available prior daily and completed hourly 10/50 SMA contexts must not oppose the direction |
| Original reference | Signal-day high for CALL, low for PUT |
| Original stop | Base boundary plus/minus the greater of 0.18 prior-day ATR or 0.15% of the boundary |

ATR is the source's simple average of fourteen true ranges. Compression uses the
fifteen prior ATR values. Regime direction uses the source's three-bar SMA slopes.
Arithmetic is exact Decimal; the existing conservative 12-decimal native stop
rounding is retained. Original 1R/2R/3R objectives come from the
[target builder](OPTIONS_SWING_TARGETS.md), with the complete policy and original
daily/hourly evidence bound into the seed proof.

The source function can return a base signal with only 35 daily bars and an
unavailable trend context. This native adaptation requires at least 55 daily bars
and 54 hourly bars so both required contexts are actually available. Missing data
does not become neutral support. Source scores and candle tags do not grant
authority. Only a setup satisfying every rule can produce a base candidate.

## Input and clock contract

Set `daily_lookback` to 55–260 and provide a `SwingBaseHistory` with explicit
`version="swing-base-daily-v1"`. `daily_base` supplies a frozen `hourly_source`
and `hourly_lookback` of 54–260. The seed also requires `SwingHourlyHistory`, version
`swing-base-hourly-v1`. Both histories are regular-session, split-adjusted,
complete REALTIME observations with exact identity and positive observed volume.

Daily bars cover consecutive actual XNYS sessions through the immediately prior
close. Hourly bars cover consecutive exchange-open-anchored intervals through that
same close, including the actual final short interval and holiday/early-close/DST
boundaries. Every source and receipt clock precedes original seed creation, which
precedes the next actual open. Gaps, future or unfinished bars, interpolation,
foreign sources, missing hourly data and unenrolled family inputs block the seed.

Use the existing `SwingSeedBuildRequest` API or installed `app.options.swing_targets`
CLI with the new policy, daily history and `hourly_history`. The returned seed goes
through the existing `SwingInput` runtime/tape path. The native next-session completed
break-and-hold, current chase, exact contract, catalyst, expiry and account gates still
apply. A base confirmed on the prior day does not authorize an immediate order.
Longer histories remain subject to existing packet/token/cost limits; limits are
not silently increased and no authenticated model call is part of this fixture proof.

## Native and portable behavior

Scans retain reproducible `base_evidence` and explicit rule blockers. Selection and
native lineage retain setup `SWING_DAILY_BASE` within family `SWING`. Source evidence,
original geometry, actual fills and all paid costs remain distinct. Stored native
reconstruction compares the selected scan and seed, rederives every base rule and
rejects family/enrollment or evidence substitution even after rehashing an export.

Observed unfilled original stops and T1 retire the seed permanently across runtime
delivery and restart. Later recovery cannot revive it. Held positions retain their
native premium/time protection and original carry deadline. Paid proposals can
still be rejected by fresh native admission; their costs remain charged and unknown
usage remains unknown. The separately enrolled carry-series wrapper preserves four
independent A/B/C/D owners, original seed terms, paid reopening management, execution
fees and explicit session/gap allocations in portable exports.

Old seeds/policies omit the new optional fields. Their twenty-bar ceiling, original
geometry, serialization and cohort behavior are unchanged. The new enrollment locks
one base seed per symbol/session within the existing Swing boundary; it does not
silently add MA-pullback or higher-timeframe-level candidates. Those remaining Swing
families and mixed stock/options ownership are still open. LIVE stays disabled and
deployment frozen. Authentic provider/model/host/economic/PAPER and final UI acceptance
follow plumbing. Installed proof is recorded in [Slice 2 status](SLICE2_STATUS.md).
