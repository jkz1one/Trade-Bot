# Durable observed trade progress

`observed-progress-v1` records native PAPER position diagnostics during supervision
and owned protection rechecks. It implements the progress-dependent components of
SignalFlow v1 `assess_management` pinned at
[`f9eaf2c1b5d13dca287ee7138126883065b00395`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_management.py).
It does not enable a health score, stop change, order or LIVE authority.

## Original geometry and accounting

The original preparation inputs and approval must contain the same valid underlying
quote. The CALL reference is its ask; the PUT reference is its bid. These are the
native conservative entry references, not an underlying fill or a later model price.
Risk distance is the positive directional distance to the original invalidation.
Later stop tightening never changes that distance.

Only a completely filled original buy supplies the premium baseline. The recorder
uses the sum of actual original fill price × quantity × contract multiplier,
the original approved quantity, first/completion fill times, and hashes of the
original intent and complete fills. A partial or canceled partial entry remains
`ORIGINAL_ENTRY_INCOMPLETE`; independent native protection still applies.
FIFO scale sales do not rebase this premium or replace the original geometry.

Premium metrics are explicitly **before costs** sensitivity diagnostics. Execution
fees and every entry/management charge remain in native accounting and position
outcomes; data/host costs remain in session reports. These metrics do not claim a
net return, actual liquidation proceeds or whole-trade breakeven. Cost-aware
[whole-trade floors](OPTIONS_TRADE_FLOOR.md) remain separate and retain their
unknown/unallocated-cost gates.

## Observations and persistent progress

Current observations must be complete, REALTIME, from the owner's sources, fresh
under its existing age/receive-lag limits, mutually synchronized and no earlier
than completion of the original entry. The option requires the exact original
instrument and a positive uncrossed bid sized for the remaining contracts. No
midpoint, last price or estimated mark substitutes for that bid. CALL progress
uses current underlying bid; PUT progress uses current ask.

The per-entry journal row retains the original baseline, tracking start, accepted
sample times/hashes, last-progress time, highest native target stage, greatest
observed favorable underlying distance and executable bid peak. A strictly higher
underlying or bid peak, or a newly latched native target, advances last-progress
time. A target touch does not claim a sale. An older clock cannot erase newer state;
regressing observations and changed evidence at an already accepted source time
remain incomplete. An identical repeat at the same evaluation time creates no
duplicate audit event; reused quotes at a later clock never advance last-progress time.

Tracking begins with the first accepted complete observation. Historical periods
before installation or before entry completion are never backfilled as monitored
time. Restart, reconciliation and partial exits retain the row for that exact entry.
A later entry gets its own row. Independent replay accounts never share progress.

The source stall rule is conservatively gated by native observation coverage:
accepted sample gaps must remain below the owner's quote-age limit throughout the
20-minute window. An unavailable/conflicting observation breaks this coverage;
recovery starts a new coverage window while preserving the original peaks and
last-progress time. A would-be stall without sufficient coverage is null with
`PROGRESS_COVERAGE_GAP`. Missing premium evidence is never treated as a zero or
negative return. This sampled coverage is not proof of every market tick.

## Exact diagnostic thresholds

All comparisons use Decimal products before six-place display rounding. `R` is
directional underlying distance divided by original risk distance. Premium return
uses original completed premium, including after partial sales.

| Signal | Source reference condition |
| --- | --- |
| Stalled | At least 20 minutes since observed progress, current R below .25, premium return at most zero, no native target hit, and valid coverage |
| Premium divergence | Current R at least .25 and premium return at most -5% |
| Premium giveback | Observed peak premium return positive and decline of at least 25 percentage points |
| Underlying giveback | Observed peak at least .75R and decline of at least .5R |

Unavailable current observations suppress all current metrics/signals while keeping
the last accepted state. A coverage gap can suppress stall independently while the
other current signals remain available. `READY` means these inputs are available;
it is not a declaration of overall health. The source commit, evaluation time,
explicit reasons and false execution/LIVE authority are retained in every result.

## Atomic persistence and stored observer

`execution_option_progress` is a recognized options journal table. Each changed
record and its `OPTION_PROGRESS_OBSERVED` audit event commit inside the same owner
transaction as supervision. An audit failure rolls back the record and protection
changes together. This is a diagnostic addition with no new policy enrollment or
provider/model call. Native monetary state and order authority are unchanged.

The stored observer adds `position.progress_health` only when a record exists.
It checks the latest matching audit event, labels the result `stored_only`, and
evaluates `observations_fresh` separately from the saved evaluation status. Reads
never refresh the state. A detached historical journal without this table remains
readable. A stale saved READY result is historical evidence, not current readiness.
The API field does not complete the dedicated dashboard visual pass.

The native journal retains diagnostic rows/events through replay. Existing portable
economic exports continue to carry their accounting, cost and attribution evidence;
this slice does not add a portable progress-history schema or use these diagnostics
to decide economic completeness. Native open holdings remain inconclusive.

## Remaining acceptance

[Observed daytrade health](OPTIONS_HEALTH_MANAGEMENT.md) now composes this evidence
with Greek pressure and native spread/session context in an explicit frozen PAPER
policy, with native tightening/exit/restart/replay fixtures. These progress records
remain diagnostic on their own. Existing mandatory protection continues independently.
Authentic health inputs and prospective policy performance remain open, as do
Scope entry/path/family-loss/runtime integration,
authentic provider/host evidence, prospective economics and dedicated UI acceptance
remain open. Main untouched; PR #1 draft; LIVE disabled; deployment frozen.

See [stored observer](OPTIONS_OBSERVER.md), [continuation status](SLICE2_STATUS.md)
and [source of truth](SOURCE_OF_TRUTH.md).
