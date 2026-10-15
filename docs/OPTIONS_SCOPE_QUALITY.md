# Scope quality and known-level path review

`app.options.scope_quality.scan_scope_quality(frame, context, policy, now=...)`
recomputes the complete Scope context review, then reports deterministic research
quality and potential price obstructions for every detected alternative. It is a
pure supplied-evidence calculation with false trade/LIVE authority. Scores are
**classifications, not win probabilities or evidence of profitability**.

`ScopeQualityPolicy` requires the complete context policy, explicit ordered
observe/watch/arm/convexity thresholds and minimum first-target reward/risk.
The minimum settings are the pinned research baselines: 80/90/94/97 and 1.5R.
Higher thresholds may be frozen. No configuration authorizes LIVE or changes
account limits, position size, fees or model budgets.

## Auditable scoring

The fixed v1 point schedule adapts the pinned
[SignalFlow Scope implementation](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard.py)
at `f9eaf2c1b5d13dca287ee7138126883065b00395`:

| Original pattern | Base score |
| --- | ---: |
| Opening-range break/hold | 88 |
| VWAP reclaim continuation | 86 |
| Trend pullback continuation | 85 |
| Compression expansion | 84 |
| Failed reversal continuation | 89 |
| Failed-break reversal | 90 |
| Opening-drive failure | 87 |
| VWAP rejection reversal | 84 |
| Trap reversal | 93 |

Each context variant starts from its retained parent, without stacking unrelated
variant bonuses: dealer acceptance +2 capped at 94, dealer rejection +2 capped at
95, prior-level variants +2 capped at 95, implied-move boundary rejection +3 capped
at 96, exhaustion confluence +5 capped at 98. Alternatives stay separate and retain
exact parent geometry; correlated variants are not independent trades.

Seven named components are stored, including zero contributions:

- SPY/QQQ confirmation: +4 for both, +3 for one. Existing confirmation/conflict
  gates and explicitly frozen directional thresholds still apply.
- Aligned options flow: +2; neutral: zero. Opposing flow remains blocked upstream.
- Aligned broad-market news: +1; neutral: zero. Opposing news remains blocked.
- Clear economic-event risk: +2; elevated: −2. Unknown/expired/high-impact states
  cannot reach scoring through a successful context review.
- First objective at least 2R: +2; otherwise zero.
- ATM expected-move consumption at or below one-half: +3; above it: +1, within
  the already enforced frozen consumption ceiling.
- Required dealer context present: +1. This is context, not directional authority.

The final score clamps to 0–100; the uncapped component sum remains inspectable.
Threshold equality qualifies for its classification. `CONVEXITY_THRESHOLD` means
only that score threshold was reached. It does not select a cheap option, establish
a clear path or grant convexity eligibility.

Global context failure produces no quality observations. A blocked or watching
context observation stays unscored with its original reasons. A high parent score
cannot rescue missing evidence, neutral/reset requirements, wrong contract identity,
material confirmation conflicts or context risk.

## Geometry and potential obstructions

First-target R uses the actual stored reference, invalidation and first objective.
The gate compares exact Decimal products before rounding the displayed ratio down
to twelve decimal places. No epsilon converts insufficient reward into a pass.
Geometry rounding can conservatively reject a marginal case; admission must later
review executable prices, all fees and slippage separately.

The current completed SPX close must still be before the first objective. An old
reference-to-target ratio cannot rescue an objective already reached. This is a
conservative added research gate, not a claim that the reference was executable.

The review enumerates supplied dealer nodes, prior-session high/low and both ATM
expected-move boundaries from the current completed close through the original
second objective, in the setup direction. Levels behind price or beyond that
objective are excluded. Endpoints are inclusive, and equal-priced levels retain
their separate evidence types in deterministic order.

A supplied level at the current close or before/at the first objective adds
`KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE` and fails this review. A level between the
first and second objectives is retained as a potential obstruction without failing
the first-objective gate. This is an explicit conservative adaptation of the
[playbook's clear-path requirement](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md),
not a claim that an unsigned dealer node is proven resistance/support. The pinned
implementation does not supply a complete obstruction classifier.

`complete_path_proven` is always false. Absence of a supplied intervening level
cannot establish that the full price path is unobstructed. Complete directional
obstruction coverage remains open; the [contract review](OPTIONS_SCOPE_CONTRACTS.md)
now explicitly blocks convexity without it.

### Optional completed SPX structural levels

A new frozen quality policy can set
`structural_path="completed-spx-levels-v1"`. Omission retains the original policy
serialization and checks; an existing watch cohort cannot adopt or change this
field on reopen. The same nested quality policy must be used by watch, contract
and arming/admission integration.

After existing complete-session, source/time, payload-hash and positive-volume
checks pass, this review adds levels derived from the supplied completed SPX bars:

- Opening-range high and low from the first three five-minute bars, known at the
  third bar's close.
- Strict three-bar pivot highs/lows. A center must exceed both neighboring highs
  or be below both neighboring lows. Its confirmation time is the right-hand bar's
  close, not the center's. Equal-height/low plateaus and the final unconfirmed bar
  are not labeled pivots.
- Session VWAP from volume-weighted typical prices across every completed bar,
  known at the latest completed close.

Every included structural level retains `confirmed_at`. Levels are checked in the
setup direction from the current completed close through the second objective,
with inclusive endpoints. A level at/before the first objective fails the existing
`KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE` gate. Later levels remain visible. Distinct
kinds and repeated pivots retain their evidence, even at the same price. Levels are
conservative potential obstructions; a pivot is not claimed to be proven directional
resistance/support or automatically removed because price previously crossed it.

VWAP uses exact rational arithmetic for path inclusion and first-objective checks.
Its displayed level rounds down to twelve decimal places and cannot change a gate.
The combined display is ordered by displayed price, kind and confirmation time.
Up to 96 input bars, 12 dealer nodes and the other existing context levels fit the
208-record output bound without truncation. Numeric output failures remain blocked.

The score and its components do not change. The structural result is recomputed
inside existing quality/contract/watch/arming reviews; a blocked new watch consumes
no called play. Stored scans retain the input and policy hashes. No caller-supplied
clear-path flag or precomputed pivot list is trusted.

This strengthens the known-level review, but **does not complete full path proof**.
Overnight structure, other horizons, plateau/supply-demand zones and authentic
coverage remain unproven. `complete_path_proven` remains false and convexity/native
Scope execution remain blocked. Absence of these finite known levels is not proof
that price can move unobstructed to the objective.

`passed` requires detected context, sufficient exact first-target reward, the arm
score threshold, an unconsumed first objective and no supplied level before it.
It means only these research checks passed. No order, model call, account mutation,
contract ranking, quantity or fills are produced. Input/policy hashes and the
complete underlying context scan remain attached. Arithmetic uses a fixed Decimal
context; unrepresentable derived output fails with a numeric-range blocker.

## Optional watch integration

A new frozen `ScopeWatchPolicy` may explicitly include `quality`. Its nested context
must exactly match the watch context policy. `call()` recomputes the quality scan
and requires the selected exact pattern/parent/right to pass. Rejection is atomic
and consumes no called play. Success locks the full original quality scan beside
the frame, context, geometry and other original evidence.

Absent `quality`, the field is omitted and old policy serialization and watch
behavior remain unchanged. Existing cohorts cannot add or retune it on reopen.
The separate [sampled arming hold](OPTIONS_SCOPE_ARMING.md) is an optional frozen
watch capability.
Direction-reset, daily calls, owner readiness and all global gates remain binding.

Filled-position linkage, every entry/management cost, loss/cooldown and reviewed
family reset, native sizing/admission, shared execution/runtime/
replay, complete obstruction coverage, authentic data and economic acceptance remain
open. See [watch contract](OPTIONS_SCOPE_WATCHES.md), [source of truth](SOURCE_OF_TRUTH.md)
and [status](SLICE2_STATUS.md). Main remains untouched, PR #1 draft, LIVE disabled
and the deployed experiment frozen.

[Optional sampled arming](OPTIONS_SCOPE_ARMING.md) now holds this review across
fresh observations for a new frozen watch cohort. It retains false authority and
does not supply complete obstruction coverage.
