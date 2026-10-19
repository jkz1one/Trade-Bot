# Native bounded Swing carry

New PAPER populations can explicitly enroll bounded overnight Swing in the existing
shared Degen/Swing owner. This is a fixture-tested local adaptation, not a replicated
external holding strategy, provider acceptance or permission to deploy. Existing
session-close populations keep their frozen configuration. The research-only
[carry preflight](OPTIONS_SWING_CARRY.md) still grants no execution authority.

## Frozen enrollment

All of the following are required together:

- `SwingPolicy.holding_policy="BOUNDED_CARRY_V1"`, an explicit `carry` policy and
  `unfilled_lifecycle="observed-lifecycle-v3"`.
- The original pre-open `SwingSeed.carry_exit_session`, exact contract and original
  `first_target`. Changing the seed after enrollment is rejected.
- `OptionExecutionPolicy.swing_carry="bounded-swing-carry-v1"` and a native
  `loss_control` rule for family `SWING`. Scope enrollment in this owner remains
  unsupported; no family switch bypasses a loss lock.
- For entry reasoning, explicit `EntryReasoningPolicy.max_carry_horizon_seconds`.
  This selects the separately hashed `option-entry-plan-carry-v1` schema/prompt.
  Candidates without carry terms, including Degen, keep the intraday horizon cap.
- For held reasoning, `PositionReasoningPolicy.swing_carry="bounded-swing-carry-v1"`
  selects an explicitly carry-aware prompt and requires original Swing context.

The policy contains maximum actual-session and calendar-day spans, minutes before
final close, and a whole-session expiry buffer. No new numeric trading defaults
are supplied. Calendar/contract/expiry guards and fresh full-horizon catalyst
clearance must all pass. The approved deadline is reconstructed from the original
seed and frozen policy; caller-provided evidence reports cannot authorize it.
There is no mutation API that turns a frozen session-close population into carry.

## Entry, ownership and protection

The journal binds the original seed/policy hashes, enumerated XNYS sessions,
first target, catalyst coverage and final exit to the decision, approval and BUY
intent. Partial fills inherit those exact terms. Dispatch, reconciliation, restart
and stored attribution independently recheck the original binding. Removing terms
from the intent does not turn a carry trade into an ordinary entry.

The entry approval remains short lived. The order remains DAY and expires no later
than the entry close or a tighter model exit. An unfilled remainder needs observed
terminal reconciliation; elapsed wall time is not a cancellation receipt. No
retry creates a new position or rolls the carry deadline. Cash, settled funds,
reservations, loss budgets and entry/exit fees use the same native account governor.

The original invalidation and premium protection stay active. The first observed
original T1 touch closes the whole held quantity; this adaptation adds no partial
profit ladder. An AI can choose an earlier target/horizon or tighten its stop; it
cannot move T1 farther away or extend the locked exit. A model horizon must end
inside one of the enumerated regular sessions. Full-period expiry and the actual
contract trading cutoff remain independent constraints.

Missing overnight observations are explicitly unknown. A fresh reopening quote can
trigger an exit; it cannot prove when an overnight stop was crossed. At the fixed
exit deadline, protection can latch without a quote, while order submission still
needs fresh executable evidence. No fill or guaranteed stop price is invented.
Owned positions and protection survive restart; exercise/unexpected exposure uses
existing fail-closed reconciliation, not presumed exercise funding.

## Held AI and costs

Carry management packets include the immutable original daily Swing scan plus
fresh completed intraday context and current account/quote evidence. The original
scan is labeled original evidence; `overnight_coverage=NOT_CONTINUOUSLY_OBSERVED`
prevents it from masquerading as current daily or continuous overnight coverage.
The AI still has only MAINTAIN, TIGHTEN and EXIT_ALL advice, without broker authority.
Original context, proposed action, review, application and fills stay attributable
through the existing observer/export path, including advice that creates no order.

Actual entry and management calls remain separately charged and deduplicated.
Native full-cost loss outcomes span the original entry through the final close,
including fees and all attributable calls; partial/unresolved exposure or unknown
cost is not a completed zero-cost result. Reconciliation refreshes Swing family
loss accounting. Existing cooldown, lock and signed reset boundaries remain.

## Multi-session replay and detached accounting

`run_replay_series` keeps four independent A/B/C/D accounts across carry sessions.
A is deterministic, B narrow selection, C full entry reasoning, and D additionally
pays for management. Exact later quote fills, DAY expiration observations, saved
session boundaries and every entry/management/data/host cost remain retained.
Detached attribution resolves an exit or management decision to the original BUY
from earlier session evidence, rather than requiring a new entry that day.

Daily reports remain `INCONCLUSIVE` with `OPEN_BOUNDARY_POSITION_UNVALUED` whenever
a boundary has open exposure. The additional `carry_accounting` reports whole-period
cash arithmetic only when the first and last boundaries are flat, all session
accounting/costs/coverage are verified, and sealed tape evidence is present. It
subtracts every entry and management charge and each session's allocated data/host
cost. Allocations must include the supplied cohort's overnight data/host expense;
a missing allocation is never a zero. Fees and slippage are already in native cash. Unknown costs, unresolved
orders, missing sessions or an open final position suppress net results.

This diagnostic has no benchmark comparison: the existing SPY session compound
excludes overnight gaps. It reports no marked daily equity, drawdown, statistical
significance or economic acceptance. Overall economic conclusions remain
`INCONCLUSIVE`; no profitable-strategy or authentic-market claim is made.

## Reproduction and next work

Use the installed-wheel isolation in [OPTIONS_TESTING.md](OPTIONS_TESTING.md).
`test_option_swing_execution.py` exercises native CALL/PUT entry, AI horizons,
weekend rollover, restart, missing quotes, original T1, partial DAY orders,
management, tamper rejection and legacy model contract identity.
`test_option_swing_carry_replay.py` runs full Friday/Monday A/B/C/D tapes and verifies
portable full-cost accounting. The research calendar suite covers holidays, DST,
early closes and expiry boundaries reused by native carry construction.

Remaining P7 work includes broader families, Scope/shared arbitration and mixed
stock/options ownership. Authentic daily/catalyst/options feeds and model evidence,
prospective full-period comparisons, host acceptance and the final UI/visual pass
remain separate. Main, PR draft status, LIVE and the deployed experiment are unchanged.
