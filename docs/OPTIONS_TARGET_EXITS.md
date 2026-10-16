# Frozen native target exits

New PAPER cohorts may enroll `OptionExecutionPolicy.target_exits="frozen-targets-v1"`
together with `partial_closes="whole-contract-v1"`. Trusted deterministic software
can supply a `TargetExitSchedule` to `OptionExecution.prepare()` for an OPEN_LONG.
The schedule contains the exact approved entry quantity and one to three ordered
underlying prices, each with a positive whole-contract exit quantity. Allocations
cannot exceed entry quantity; the unallocated remainder is a runner.

The schedule freezes in the decision inputs, approval, buy intent and held position
before the entry attempt. Its quantity must equal common-governor approval rather
than overriding that approval. CALL targets must strictly increase beyond the
current underlying ask; PUT targets must strictly decrease beyond the bid. Dispatch
rechecks the original schedule and rejects entry after the first objective is consumed.
No schedule may be attached to a model-origin entry or its existing single-target
entry-plan protection. Historical omitted fields and existing cohorts stay unchanged.

Example for a deterministic four-contract CALL admission:

```python
from app.options.lifecycle import TargetExitSchedule, TargetExitStep

schedule = TargetExitSchedule(
    entry_quantity=4,
    steps=(
        TargetExitStep(underlying_price="602", quantity=2),
        TargetExitStep(underlying_price="604", quantity=1),
    ),
)
# Pass target_exit_schedule=schedule to the existing native prepare() call.
# The common governor must independently approve exactly four contracts.
```

This is an explicit software allocation contract, not a model sizing field or a
Scope profile-selection rule. The pinned SignalFlow playbook requires quantity-
and objective-dependent management, but its RESPONSIVE/BALANCED/CONVEXITY contract
profiles are distinct from the shared FRONT_LOADED/BALANCED/BACK_LOADED sizing
profiles. This change does not equate them or invent a Scope allocation mapping.
The source catalog retains the pinned playbook, `play_sizing.py`,
`play_management.py` and `premium_scaling.py`; Degen's premium ladder is also a
separate policy and is not enabled by this schedule.

## From target observation to verified sale

The existing independent `protective_tick()` reconciles ownership, evaluates
mandatory protection, and then services an enrolled schedule when supervision is
healthy. Fresh validated underlying bid (CALL) or ask (PUT) crossing a target latches
the highest reached stage. The latch survives a rebound, reconciliation and restart.
An underlying observation never manufactures an option fill.

For the latched stage, required sales equal cumulative scheduled quantities minus
verified sales linked to that exact entry. Discretionary and protective sales count
toward this total; a later target cannot sell the same allocation twice. A gap across
several targets produces one cumulative close request. The existing governor caps
each actual order by remaining ownership, executable bid size and the fixed price.
After verified completion, a later tick can request any still-due contracts. Every
order retains its own execution fees and actual fills. Reusing a quote does not
renew its consumed fixture liquidity.

Preparation and dispatch bind the close's `target_exit_stage` to observed progress,
the exact held entry and remaining cumulative quantity. The stored observer/export
attribution exposes the frozen entry schedule and close stage alongside requested,
approved and filled quantities. Reading evidence performs no target evaluation.

A never-attempted PREPARED target order survives restart and is dispatched by its
original client ID. It retains its original approval deadline and limit. An expired
local preparation may reject; a later fresh tick may prepare a new order. Attempted
OPEN/PARTIAL/SUBMITTING/UNKNOWN orders retain their reservation and are never replayed.
Attempted REJECTED/CANCELED/EXPIRED closes require review before another automatic
target sale. No broker cancellation API is introduced.

## Protection and accounting

Original/tightened invalidation, catastrophic premium protection, session/expiry
deadlines and latched exit reasons retain precedence. Protection can supersede only
a never-attempted prepared scale. An attempted scale must reconcile before protection
addresses actual remaining ownership. Target progress never widens a stop, extends a
deadline or changes the premium catastrophe fraction. This version does not add
automatic breakeven stops, premium trails or profile-specific catastrophe settings.

Only a completely filled entry can run its automatic allocation. A working partial
entry retains the existing single-order reservation; a terminal partial entry returns
`OPTION_TARGET_COMPLETE_ENTRY_REQUIRED`. It is not silently resized or assigned a new
runner profile. Independent mandatory protection and explicit owned closes remain
available against actual holdings.

All orders use native FIFO accounting and the existing per-contract exit reserves.
Target touches are underlying observations, not claims about option returns. Actual
option fills can produce a loss even after both targets. Every entry/management
charge remains attributed to the original entry; unknown charges withhold complete
economics. Independent accounts retain separate progress, cash, reservations and
loss state. Sale proceeds require the existing explicit settlement evidence.

## Acceptance boundary

Fixture and installed-worker tests cover CALL/PUT, one-to-four-contract full exits,
scales and runners, gap targets, constrained liquidity, attribution, restart,
rollback, mandatory-exit precedence, unknown/failed attempts, partial-entry review
and independent accounts. Native partial-close regression retains known and missing
entry/management charges through completed and incomplete outcomes.

Scope entry remains blocked. Its source-derived profile/allocation factory,
profile-specific premium protection, complete obstruction coverage, frozen watch
linkage, Scope family loss/reset and runtime/replay acceptance remain open. This
shared deterministic capability grants no Scope, authentic provider, host or LIVE
acceptance. Main stays untouched, PR #1 draft, LIVE disabled and deployed experiment
frozen. See [partial closes](OPTIONS_PARTIAL_CLOSE.md),
[execution](OPTIONS_EXECUTION.md), [Scope admission](OPTIONS_SCOPE_OWNED_ADMISSION.md)
and [source of truth](SOURCE_OF_TRUTH.md).
