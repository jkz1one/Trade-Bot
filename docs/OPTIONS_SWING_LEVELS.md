# Native higher-timeframe level break/retest

`SwingPolicy.higher_levels` enrolls `swing-level-retest-v1` in a new PAPER owner.
Its frozen unique `keys` allows previous-week high/low, previous-month high/low and
weekly open. Each original seed locks one `level_key`. High setups are CALL, low
setups PUT; weekly open follows the current completed daily 10/50 SMA direction.
Each setup retains a distinct `SWING_*` identity within the shared SWING family.

## Source contract

The pinned SignalFlow commit is `f9eaf2c1b5d13dca287ee7138126883065b00395`,
setup engine blob `af7912bc06dbf0bee94c148cfe7fb1540842d85b`.
`build_level_registry`, `evaluate_swing_playbook`, `evaluate_level_break_retest`
and directional candle confirmation supply the fixed rules. There is no caller-
supplied level price, model-derived stop or new strategy choice.

The signal date is the last completed daily bar, not the later entry date. Previous
week/month extrema are computed from all actual exchange sessions of that completed
calendar period. Weekly open is the first actual session's open in the signal week.
The original source-period start/end are retained with the price. Missing sessions,
partial periods, foreign histories or incorrect exchange boundaries are rejected.
Holidays, early closes, DST and month/year boundaries use the actual XNYS calendar.

A completed directional close cross must exist within the source's twelve-bar
lookback (thirteen bars including the preceding close). The latest cross is retained.
The current range must retest the level ±0.7%; its close must hold the favorable side
within the source's 0.4% tolerance. Directional engulfing, rejection or strong-close
confirmation is required. Repeat clusters beyond the preferred second retest remain
a warning, as in the pinned source. Scores and neutral candle tags grant no authority.

The original reference is the signal-day high/low. The stop is the original level
minus/plus 1.5 times the 0.7% tolerance; fixed 1R/2R/3R objectives use that original
risk. Native exact Decimal prices and conservative 12-decimal stop rounding are
retained instead of source float/four-decimal presentation rounding. The original
level/geometry is never regenerated from a new session, current quote or paid reply.

## Native integration

Use `SwingLevelHistory(version="swing-level-daily-v1")` with 56–260 consecutive
completed daily sessions, matching `daily_lookback`. This covers daily regime and
complete previous month/week evidence. All observations retain the original source,
REALTIME completeness, positive observed volume and source/receipt clocks. Creation
must precede the target session's open. Hourly/MA fields are unsupported for this
family and rejected rather than ignored. The existing create-only target-builder
API/CLI produces the original seed, not approval or an order.

Native next-session completed break/hold, exact contract, catalyst, quote/chase,
account risk, paid-cost, deadline and dispatch checks remain independent. Source
family diagnostics and geometry are rederived during native review and stored
reconstruction. Original stop/T1 retirement, runtime delivery, restart, actual
fills, mandatory native protection and carry retain their existing authority.
Paid fresh rejection charges remain charged; missing usage remains unknown.
Independent A/B/C/D replay/export retains separate balances and every entry/
management charge, execution fee and explicit operating allocation.

New optional fields remain absent in old cohorts. This enrollment still locks one
Swing seed per symbol/session and is separate from base/MA enrollment. Concurrent
Swing-family candidate enumeration/selection and mixed stock/options ownership are
remaining plumbing. Authentic provider/model/host/economic/PAPER and final UI
acceptance follow plumbing. LIVE remains disabled and deployment frozen.

See [testing](OPTIONS_TESTING.md) and the newest [status](SLICE2_STATUS.md).


## Complete family batch enrollment

The separately frozen [complete family batch](OPTIONS_SWING_BATCH.md) now permits
concurrent native family selection from one original source per symbol, with atomic
locks, exact selected lineage, bounded unique quotes, runtime and independent
carry/export. The single-seed limits above continue to describe legacy enrollment.
Mixed stock/options ownership and its runtime/accounting integration remain open.
