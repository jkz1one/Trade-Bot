# Observed daytrade health policy

New PAPER cohorts can freeze `OptionExecutionPolicy.health_management =
"observed-daytrade-health-v1"`. The original buy's preparation inputs, approval and
intent retain enrollment. Dispatch checks those terms against the frozen owner;
existing owners cannot adopt the policy by reopening with changed configuration.
Absent enrollment keeps legacy serialization and behavior.

This policy composes the pinned SignalFlow v1 health components at
[`f9eaf2c1b5d13dca287ee7138126883065b00395`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_management.py)
with native evidence and execution authority. It applies to options expiring on
the original entry's New York date; explicitly labeled Swing entries and longer
dated contracts are `NOT_APPLICABLE`. It does not enable overnight Swing, Scope
entry, a model-selected health policy or LIVE trading.

## Evidence and source adaptation

The owner first runs existing mandatory protection, then records
[durable progress](OPTIONS_PROGRESS_HEALTH.md). Health actions require a current
READY progress record, READY [observed Greek pressure](OPTIONS_GREEK_HEALTH.md),
an available uncrossed bid/ask spread and the native XNYS session window. The
original Greek quote must match original preparation/approval evidence. Exact
instrument, source, entitlement, timestamps, original completed fill basis and
original underlying risk geometry remain mandatory.

Missing, estimated, stale, regressing, conflicting or gapped evidence produces
`INCOMPLETE` and withholds new health stops/exits. Known component signals and a
partial `known_score` may remain visible, but condition stays UNKNOWN. The native
quote-age limit is never relaxed to the source's 120-second allowance. Consecutive
missing quote evaluations are retained diagnostically, with same-time repeats
counted once; they do not authorize an action on missing prices. Unverified free-form
market regime labels are not adopted. This is a bounded observed v1 adaptation,
not the source's entire platform or v2 management system.

When the evidence is complete, the fixed weights are:

| Component | Weight |
| --- | --- |
| Covered stall | 2 |
| Underlying/premium divergence | 2 |
| Premium giveback | 1 |
| Underlying giveback | 1 |
| Theta pressure | 1 |
| IV contraction warning | 1 |
| Absolute delta deterioration warning | 1 |
| Spread above the owner's execution limit | 2 |
| At most 90 session minutes left, no target reached, current progress below .5R | 1 |

The linked diagnostic contracts define exact Greek/progress thresholds and coverage.
Spread compares `ask - bid > max_spread_fraction × ask`, matching native admission.
Minutes to close come from the native calendar, including its early-close window,
using the source's floor-to-whole-minute convention. Contract cutoff, expiry guard
and the original independent exit deadline still take precedence.

## Tightening and exits

Score zero is HEALTHY, one is CAUTION, and at least two is DEFENSIVE, provided all
required evidence is available. Before the first latched native target, caution
proposes `entry reference − direction × .50 × original risk distance`; defensive
proposes the corresponding `.25` distance. CALL stops can only increase; PUT stops
can only decrease. Existing stricter stops always win. Prices round toward tighter
protection to the native 12-decimal price bound; comparisons precede display rounding.

If the current directional underlying mark has already crossed the proposed
effective cap, the owner latches `HEALTH_MANAGEMENT` immediately. A covered stall
also requires this exit when accompanied by theta pressure, severe IV contraction,
severe absolute-delta deterioration, premium divergence, or at most 45 session
minutes remaining. A target touch is not a sale; after a native target, this policy
does not introduce a new pre-target cap. Existing target stops, premium trails and
cost-aware whole-trade floors continue to govern independently.

The first exit timestamp survives recovery, rebound, missing health inputs and
restart. An existing mandatory exit reason keeps priority. Retained health stops
become ordinary native invalidation protection and do not require future Greek
availability to remain effective. `HEALTHY` in the outer supervisor still describes
its existing native protection status; inspect the nested health assessment for
health-input completeness. A stored health assessment grants no caller authority.

## Native execution, accounting and concurrency

Health assessment runs inside the same audited owner transaction as supervision,
partial-close review and paid position-management rechecks. Stop changes survive
discretionary rejection; a model MAINTAIN or stale plan cannot undo them. Audit
failure rolls back the health record, progress record and protection changes.
Semantic decision identity uses condition, effective stop and exit reason, so a
numeric diagnostic refresh does not reset the decision time.

Mandatory health exits use the existing governed close path. Only a never-attempted
prepared scale may be superseded; attempted, partial or unknown orders retain
reservations until reconciliation. Remaining quantity comes from verified fills.
Incomplete enrolled health evidence blocks new discretionary scales and automatic
target sales; independent full/protective exits retain their existing authority.

No health assessment invokes a model or adds an external call. All entry and
management charges, execution fees, independent account limits and unknown-cost
gates stay in native accounting. Source premium-return diagnostics are before
costs and never establish net profit; whole-trade floors and session economics
retain their full-cost calculations. A rejected paid model response retains its
charge. The policy does not rebalance the four replay accounts.

Entry and linked closing attribution expose original enrollment. Native export
retains the policy and actual tightened/latched position state. Portable accounting
requires each buy's enrollment to match the arm's frozen definition; mismatch
withholds verified accounting and net change. Open holdings remain inconclusive.
The native journal retains the detailed health/progress audit; no separate portable
health-history schema is introduced.

## Stored observer and acceptance boundary

`position.health_management` reads the saved `execution_option_health` row and
checks its latest `OPTION_HEALTH_ASSESSED` audit event. It labels `stored_only` and
observation freshness separately from historical status, retains component evidence
and reasons, and performs no reassessment or network work. Historical journals
without the optional table remain readable. HTML/dashboard visual treatment is
part of the dedicated UI pass.

This is local normalized-fixture PAPER acceptance. Authentic provider/model
evidence, prospective economics, host acceptance, Scope integration, remaining
Swing/mixed-instrument work and the dedicated UI pass remain open. Main untouched;
PR #1 draft; LIVE disabled; deployed experiment frozen.

See [source of truth](SOURCE_OF_TRUTH.md), [continuation status](SLICE2_STATUS.md),
[stored observer](OPTIONS_OBSERVER.md) and [whole-trade floors](OPTIONS_TRADE_FLOOR.md).
