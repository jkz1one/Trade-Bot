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
deadline or changes the premium catastrophe fraction. Optional frozen target stops
are described below; separately enrolled [premium trails](OPTIONS_PREMIUM_TRAIL.md)
now retain executable bid peaks against completed entry basis. Separately enrolled
[entry premium protection](OPTIONS_SCOPE_MANAGEMENT.md) can now freeze a tighter
premium limit before a deterministic entry.

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

Native session export and portable economic replay preserve the saved
`target_exit_stage` but exclude it from fill-derived ownership comparisons. A target
touch is management evidence; venue fills do not reconstruct it. Frozen schedule
terms, remaining lots, original protection and completed entry premium basis still
must match exactly. This allows touched positions, partially filled scale orders
and retained runners to export with their actual cash and execution fees.
`OPEN_BOUNDARY_POSITION_UNVALUED` still withholds a net return; unresolved orders,
missing scheduler coverage and unknown model/data/host costs remain explicit.
Export does not close, value or manage the remaining position.

## Optional frozen target stops

New PAPER cohorts can additionally enroll
`OptionExecutionPolicy.target_stops="frozen-target-stops-v1"`. This requires frozen
target exits and their whole-contract close policy. An explicitly supplied
`TargetExitStep.tighten_underlying_to` freezes a stop adjustment at that particular
target. Omitted values retain the current stop; old serialized schedules and cohorts
are unchanged and cannot adopt this enrollment on reopen.

For example, a four-contract CALL plan with original invalidation below 600 can
exit two at 602 and tighten to 600, then exit one at 604 and tighten to 602:

```python
schedule = TargetExitSchedule(
    entry_quantity=4,
    steps=(
        TargetExitStep(underlying_price="602", quantity=2, tighten_underlying_to="600"),
        TargetExitStep(underlying_price="604", quantity=1, tighten_underlying_to="602"),
    ),
)
```

This is an explicit deterministic plan. Preparation requires exact common-governor
quantity, unconsumed directional targets and stop prices that strictly tighten from
the original invalidation and each preceding specified stop. Each stop must remain
strictly behind its own target. PUT comparisons reverse. Dispatch rechecks frozen
terms and enrollment. Neither callers nor the model can revise a schedule after entry.

Fresh underlying observations latch targets as before. Stop application requires
both valid underlying and executable option quotes. A gap applies all reached
steps, retaining the tighter of their stops and any existing manual/model tightening.
If a target latched while the option quote was unavailable, fresh recovery applies
its stop and checks the current underlying in the same assessment. A rebound onto
or through that stop immediately latches `UNDERLYING_INVALIDATION`.

Stage, effective stop and any mandatory exit latch persist atomically with supervision
evidence. Reconciliation and restart retain them through partial fills, scales and
runners. A terminal partial entry still cannot run resized target allocations, but
its actual held contracts retain the frozen protective stop rules. Only verified
fills retire size. Attempted/unknown orders retain their reservations; protection
can supersede only never-attempted prepared scales. Existing mandatory exit reasons
and deadline/premium protection keep precedence.

The stored entry schedule exposes the stop terms, and supervision records the
effective `target_stop_price`. Reads do not advance targets or stops. Touching an
underlying entry price is not option breakeven: spreads, actual premiums, all fees
and every entry/management charge remain in native outcomes. No cost is discounted.

The pinned SignalFlow
[`play_management.target_stop_price()`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_management.py)
provides the target-dependent tightening precedent. This fixed-price primitive
requires explicit prices; it does not equate a native executable stage with a Scope
T1/T2 label or use a research reference price as an actual entry. Scope v1 previews
omit these fields. The separately enrolled [fill-bound extension](OPTIONS_ENTRY_REFERENCE.md)
now supplies the first-milestone reference and Scope v2 plan; native Scope linkage,
its missing third objective and full management acceptance remain open. Shared native premium trailing
is now separately available through an explicitly frozen owner policy.

## Stop-only target milestones

New PAPER owners may instead enroll
`target_exits="frozen-target-milestones-v2"`, with the existing whole-contract
partial-close and frozen-target-stop policies. The schedule must name the same v2
version. Preparation and dispatch reject any schedule/owner version mismatch;
existing v1 cohorts and serialized schedules retain positive exit quantities.
Enrollment cannot be changed on reopen.

A v2 step may have `quantity=0` only with an explicit `tighten_underlying_to`.
It observes an objective and tightens protection without requesting a sale. For
example, a one-contract position can tighten at its first objective and sell at
its second:

```python
schedule = TargetExitSchedule(
    version="frozen-target-milestones-v2",
    entry_quantity=1,
    steps=(
        TargetExitStep(underlying_price="602", quantity=0, tighten_underlying_to="600"),
        TargetExitStep(underlying_price="604", quantity=1, tighten_underlying_to="602"),
    ),
)
```

Prices above are explicit illustrative inputs, not inferred Scope entry/target
prices. The existing directional, original-stop, common-governor quantity and
freshness checks still apply. A step cannot be a no-op, loosen protection or carry
a negative/fractional quantity. An all-stop schedule leaves the whole position as
a runner under mandatory protection; it does not imply a later voluntary sale.

The pinned `play_management.target_stop_price()` advances protection from observed
target labels independently of scale fills. Previously our native schedule could
only represent milestones with positive allocations, so a one-contract T2 exit
could not represent a separate T1 tightening. The new version closes that engine
gap without changing source allocations or fabricating Scope's missing third target.

Stages now count explicit milestones, including stop-only steps. Fresh underlying
observations latch them, valid executable quotes allow tightening, and rebound
checks, restart and atomic supervision persistence use the existing native path.
A gap sums only actual scheduled sale quantities. Verified earlier sales reduce
that total; a later stop-only stage cannot sell the same contracts again. Zero due
means no close decision, order, reservation, fee or proceeds. A caller cannot turn
a zero-allocation milestone into a target sale. Terminal partial entries retain
protective tightening but cannot silently resize the planned allocation.

When separately enrolled, the existing 0/10/25% whole-trade floor references apply
to the explicitly ordered milestones, even when a milestone sells nothing. They
still require verified original entry basis and complete recorded fees/model costs,
with future exit fees reserved. A target touch never supplies sale proceeds or
proves profit. Native exports preserve original schedule, actual holdings and all
costs; open boundaries remain inconclusive. Independent owners do not share stage,
stop, cash or fill state.

New [fill-bound target protection](OPTIONS_ENTRY_REFERENCE.md) can resolve the
first milestone stop from complete native entry observations under a separately
frozen policy. Scope management v2 now emits both milestones with this entry-bound
marker and the T2-to-T1 stop; v1 remains unchanged. Scope execution linkage and its
entry guard remain separate, and no missing T3 or path requirement is bypassed.

## Acceptance boundary

Fixture and installed-worker tests cover CALL/PUT, one-to-four-contract full exits,
scales and runners, gap targets, constrained liquidity, attribution, restart,
rollback, mandatory-exit precedence, unknown/failed attempts, partial-entry review
and independent accounts. Native partial-close regression retains known and missing
entry/management charges through completed and incomplete outcomes.

Scope entry remains blocked. The [Scope management factory](OPTIONS_SCOPE_MANAGEMENT.md)
now produces one-through-three-contract schedules from owned admission and explicit
premium protection capped by the owner. Four-contract plans retain an unresolved T3
and cannot produce a schedule. Complete obstruction coverage, frozen watch linkage,
Scope family loss/reset and full management/runtime/replay acceptance remain open. This
shared deterministic capability grants no Scope, authentic provider, host or LIVE
acceptance. Main stays untouched, PR #1 draft, LIVE disabled and deployed experiment
frozen. See [partial closes](OPTIONS_PARTIAL_CLOSE.md),
[execution](OPTIONS_EXECUTION.md), [Scope admission](OPTIONS_SCOPE_OWNED_ADMISSION.md)
and [source of truth](SOURCE_OF_TRUTH.md).
