# Native daily moving-average pullbacks

`SwingPolicy.ma_pullback` explicitly enrolls `swing-ma-pullback-v1` in a new
PAPER owner. Its frozen `periods` selects supported 8 EMA, 21 EMA and/or 50 SMA
variants; each original seed locks one `ma_period`. Setup identities are
`SWING_DAILY_8_EMA`, `SWING_DAILY_21_EMA` and `SWING_DAILY_50_SMA`, all inside
family SWING. They use the existing shared Degen/Swing/Scope owner, account,
reservation, paid model slot, protection and loss accounting.

## Pinned rules

SignalFlow commit `f9eaf2c1b5d13dca287ee7138126883065b00395`, setup engine blob
`af7912bc06dbf0bee94c148cfe7fb1540842d85b`, supplies
`evaluate_swing_playbook`, `evaluate_moving_average_pullback`,
`detect_candle_confirmations`, `_touch_clusters`, `build_trend_context` and `_targets`.
The native implementation uses exact Decimal arithmetic and conservative native
12-decimal stop rounding, not the source's floating-point/four-decimal output.

| Rule | Completed original evidence |
| --- | --- |
| Direction | Current daily 10/50 SMA regime matches CALL/bullish or PUT/bearish |
| Established MA trend | Prior close on the favorable side and three-bar MA slope at least +0.02% or at most −0.02% |
| MA test | Current range intersects the average ±0.4% for either EMA, ±0.6% for 50 SMA |
| Hold | Current close on the favorable side; at least one held bar after the latest touch |
| Confirmation | Directional engulfing, rejection wick or strong-body close; neutral inside/doji tags alone do not qualify |
| Original reference | Signal-day high for CALL, low for PUT |
| Original stop | More conservative of signal-day extreme and MA ±max(tolerance, 0.15 × current ATR14) |
| Objectives | Fixed original 1R/2R/3R ladder bound to complete seed/policy hashes |

EMA starts from the first supplied close with weight `2/(period+1)`; SMA uses
fifty closes. The complete input window is frozen. Prior-five-bar volume ratio,
last-sixty-bar touch clusters and hourly opposition are retained diagnostics. The
pinned source does not make these CONFIRMED-phase blockers, so the native adapter
does not silently promote them into new strategy rules. It does not import a
score, claim horizontal-level confluence or grant authority from a candle tag.
The native next-session break/hold, catalyst, quote/chase, contract, account,
cost and approval/deadline gates independently remain required.

## Enrollment and evidence

Provide 56–260 consecutive completed actual XNYS daily sessions as
`SwingMAHistory(version="swing-ma-daily-v1")`, matching `daily_lookback`.
Fifty-six bars cover the source's longest minimum (`period+6`) and daily trend.
Use the existing `SwingHourlyHistory(version="swing-base-hourly-v1")` with the
frozen hourly source and 54–260 actual exchange-open-anchored hourly intervals.
The reused hourly wire contract includes final short intervals, early closes and
DST. Both histories require observed positive volume, REALTIME completeness,
regular sessions, split adjustment, exact symbol and original source/receipt clocks.
Missing hourly evidence is unavailable, not neutral. Original creation precedes
the next actual open; future, foreign, gapped and interpolated evidence is blocked.

The existing `SwingSeedBuildRequest` API/create-only CLI accepts `ma_period` and
these histories. Building a seed fixes geometry; it does not prove a confirmed
setup or authorize an order. Native scanning reproduces every rule. Fresh entry
review and portable stored reconstruction independently verify original family,
variant, source evidence, geometry and diagnostic identity. An unenrolled variant,
changed policy or altered stored evidence cannot borrow an old valid seed hash.

All native execution paths retain original stop/T1 retirement, exact deadlines,
mandatory premium/time exits, paid fresh rejection charges, unknown costs and
once-per-revision management. Independent A/B/C/D carry/export retains four
accounts, actual fills and every model/management charge, execution fee and explicit
session/gap operating allocation. Runtime delivery and restart preserve original
MA evidence and terminal unfilled states.

Legacy policies/seeds/scans omit every new optional field. Base and MA enrollments
are mutually exclusive in this slice; one original Swing seed remains locked per
symbol/session. Concurrent base/MA/level candidate enumeration and common selection
are a separate remaining integration task, not implied by support for three MA
variants. [Higher-timeframe level families](OPTIONS_SWING_LEVELS.md) now have their
own native enrollment. Joint selection and mixed stock/options ownership remain open. Authentic data/model/host/economic/PAPER and final visual acceptance
follow plumbing. LIVE stays disabled and deployment frozen.

See [testing](OPTIONS_TESTING.md) and the newest [status proof](SLICE2_STATUS.md).


## Complete family batch enrollment

The separately frozen [complete family batch](OPTIONS_SWING_BATCH.md) now permits
concurrent native family selection from one original source per symbol, with atomic
locks, exact selected lineage, bounded unique quotes, runtime and independent
carry/export. The single-seed limits above continue to describe legacy enrollment.
Mixed stock/options ownership and its runtime/accounting integration remain open.
