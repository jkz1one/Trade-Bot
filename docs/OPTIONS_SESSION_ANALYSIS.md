# Whole-session uncertainty diagnostics

Optional P3 offline analysis, 2026-10-12. `EvaluationManifest.session_analysis`
freezes one primary B/C/D comparison against A. The pure evaluator consumes its
already verified, paired session net-equity differences after every venue, entry
model, management model, data and host charge. Independent accounts, tape checks,
stored attribution and the enrolled underlying comparator retain their existing
gates. Replay/export pass the manifest through to this same evaluator.

No policy means `session_analysis.status = NOT_ENROLLED`. The omitted field does
not change old manifest serialization or hashes. Enrolling a policy changes the
manifest hash and requires a new declared evaluation; do not retrofit it to make
an observed winner the primary arm.

## Frozen contract

Example policy for a separately declared horizon of at least 20 XNYS sessions:

```json
{
  "version": "paired-circular-block-v1",
  "primary_arm": "D",
  "block_sessions": 5,
  "minimum_blocks": 4,
  "replicates": 2000,
  "seed": 17,
  "confidence": "0.95",
  "declared_trial_ids": ["full-plan-entry-v1", "managed-entry-v1"]
}
```

D must be enrolled. All fields above except the version are required; the example
does not prescribe an adequate economic sample. Block length is 2–15 sessions,
minimum blocks 4–30, replicates 1000–10000, seed an unsigned 32-bit integer, and
confidence an exact decimal from 0.80 through 0.99. The declared horizon must meet
both `minimum_sessions` and `block_sessions * minimum_blocks`. The existing
60-session manifest bound remains. An impossible horizon is rejected, not silently
shortened. Trial IDs must be distinct and nonempty. Optional `regime_labels` must
give one predeclared label for every session in order; omitted labels produce
`NOT_PROVIDED`, with no inferred regimes.

The review boundary is the last declared session close. This offline evaluator
does not authenticate declaration time, enforce a wall-clock embargo, verify a
trial registry, or prevent reruns. Prospective enrollment must independently freeze
these choices before outcomes and retain all attempted model/prompt/strategy
trials, including abandoned candidates.

## Calculation and output

For the primary arm only, sample fixed-length contiguous blocks of paired session
differences, with replacement. Blocks wrap from the last session to the first.
Each replicate contains exactly the original number of sessions; truncate only
the final sampled block. Trades, fills, calls and arms are never resampled
independently. This preserves within-session outcomes and local serial structure
under the explicitly assumed block model.

Version 1 draws start indices using SHA256 of UTF-8
`paired-circular-block-v1:<seed>:<counter>`, counter starting at zero. Interpret the
digest as an unsigned big-endian integer; reject values at or above
`2**256 - (2**256 % session_count)`, then take modulo session count. Increment the
counter after each draw. Sort replicate means and interpolate linearly at
`(replicates - 1) * p`, with tails `(1 - confidence) / 2` and its complement.
Arithmetic uses a private 192-digit Decimal context, matching evaluation's bound.

Output includes the primary mean, percentile interval, interval endpoints minus
the predeclared economic hurdle, and largest absolute session contribution divided
by the sum of absolute contributions (null for all-zero results). Chronological
blocks, calendar months and optional declared regimes list their session keys,
planned/complete counts and net-difference sums. These groups are descriptive;
there are no secondary arm intervals, winner selection, p-values or pass labels.

Any missing/unknown arm, cost, tape, SPY boundary or enrolled underlying result
withholds the overall mean and interval. The full declared denominator remains;
an incomplete group's sum is also null. Complete group subtotals remain explicitly
descriptive. No complete-case estimate replaces missing sessions. Complete
arithmetic and complete diagnostics are separate statuses; even a lower endpoint
above the hurdle leaves `economic_conclusion = INCONCLUSIVE` and execution
authority false. Existing CLI exit codes continue to describe accounting completeness.

## Limits and next evidence

Circular wrapping is an assumption, not evidence of stationarity or independence.
Short histories, regime shifts, the chosen block length and percentile method can
give misleading coverage. The minimum block count is an input bound, not a power
analysis or acceptance threshold. Trial disclosure is caller-supplied; no correction
for repeated peeking, multiple trials or selection is supplied. Historical fixture
results do not establish prospective profitability or authorize LIVE.

Method reference: the [arch time-series bootstrap documentation](https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html)
describes fixed-length circular blocks with end-to-start wrapping. This implementation
does not depend on arch and does not claim validated inferential coverage.

Remaining P3 evidence is authenticated collection/coverage, frozen prospective
enrollment and trial history, and a separately justified untouched evaluation
horizon/precision design. The proposed 20-session feasibility pilot in the
[research plan](AI_TRADER_RESEARCH_PLAN.md) remains a pilot. Actual provider/model
acceptance, runtime/UI and deployment are separate gates. The deployed experiment
is unchanged and LIVE stays disabled.
