# Executable premium trailing protection

New PAPER owners may explicitly enroll
`OptionExecutionPolicy.premium_trail="executable-premium-v1"`. The frozen policy
applies equally to deterministic and model-proposed buys in that owner. It is
software protection, not a model field or new model authority. Old cohorts omit
the field and cannot adopt it on reopen. Entry approval, intent and stored decision
inputs retain the policy; dispatch requires agreement with the frozen owner.

## Fixed reference and thresholds

The original requested/approved whole quantity is stored at the first verified fill.
Only completion of that exact entry establishes its premium basis from all actual
fill prices. Partial entries do not accumulate peaks; terminal partial entries keep
their original underlying, premium-catastrophe and deadline protection. They do not
receive a resized trail. Fees are excluded from this premium-only reference and
remain fully charged in accounting.

The fixed thresholds adapt the pinned SignalFlow
[`play_management.py`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_management.py)
premium-floor rules:

| Observed executable premium gain | Premium floor |
| --- | --- |
| Below 20% | No trail floor |
| At least 20% | 97% of completed entry premium |
| At least 35% | 110% of completed entry premium |
| At least 50% | Greater of 125% of entry premium and entry premium plus 55% of peak gain |

Only a fresh, complete, correctly bound realtime **bid with positive executable
size** can raise the peak or trigger the floor. Ask, midpoint and last-price fallback
are not adopted. Original source/entitlement/time and crossed-market checks apply.
Underlying availability remains a separate supervision gate. No quote implies a
fill, and thin bid size cannot authorize selling more than the native governor allows.

Arithmetic compares original-quantity premium equivalents: bid × original quantity
× multiplier against the floor derived from original completed entry basis. This
avoids dividing a multi-fill average or rounding thresholds to a displayed option
price. CALL and PUT premiums follow the same rule. A boundary touch counts. The
peak never falls; scale-outs never rebase it onto remaining FIFO lots or realized
proceeds. For example, a 1.01 average entry with a 1.515 bid peak has a 1.28775
premium-equivalent floor before fees, costs and subsequent execution slippage.

## Native lifecycle and accounting

The independent supervisor stores the peak atomically with its ordinary evidence.
At or below the floor it latches `PREMIUM_TRAIL`, retaining the first exit time.
Rebound, refresh and restart cannot erase the exit. Original/tightened underlying
stops, existing exit latches, premium catastrophe and time/expiry exits retain
precedence. Frozen target stops cannot be widened by the trail.

Reconciliation checks original trail identity, quantity and completed basis against
replayed fill history and the native venue. It preserves the supervised peak for
the same exact entry, including after partial sales and across restart. The basis
transition from an incomplete to a complete entry cannot overwrite a later peak.
An attempted working/unknown scale retains its reservation; protection may supersede
only a never-attempted prepared scale. After reconciliation, any protective order
uses actual remaining ownership and executable size.

Original full-premium admission, exit reserves, fees, settlement and every entry or
management charge remain unchanged. Reaching a premium floor is not net breakeven,
a profit guarantee or a guaranteed fill price. Unknown costs still withhold net
outcomes; data/host costs remain in the full session report. Each independent owner
keeps its own entry basis, peaks, cash and paid usage.

Stored order attribution carries the trail policy through exact closing-entry
links. The read-only observer exposes original basis/quantity, saved peak and
`floor_original_quantity_premium` with a before-costs label. It computes the floor
from stored state without sampling quotes or updating the peak. Portable accounting
and native export comparisons ignore only the changing peak, retaining the policy,
quantity and original basis as ownership evidence.
Portable evaluation also rejects a buy whose trail enrollment disagrees with its
frozen arm policy, including a removed enrollment field on a completed trade. That
arm becomes inconclusive with accounting unverified and net change withheld.

## Acceptance boundary

Fixture/native-worker tests cover exact activation and exit boundaries, both option
directions, weighted partial entry completion, partial sales, restart, stale/invalid
bids, frozen enrollment, dispatch binding, independent owners, audit rollback,
stored-only observation and independent A/B/C/D replay with entry/management costs.

This is the shared premium trail primitive. Scope remains blocked pending its
watch/entry binding, missing four-contract objective, complete path proof, family
loss/reset and full management/runtime/replay acceptance. Source whole-trade floors
based on realized sales, management health/Greek rules and any strategy-specific
trail enrollment require their own acceptance; none is implied by this policy.
The [native whole-trade floor preview](OPTIONS_TRADE_FLOOR.md) now supplies verified
sale/fee/model-cost arithmetic for the first of those gates, without automatic
enrollment or enforcement.
Authentic provider/host, prospective economics and the dedicated UI pass remain open.
Main untouched, PR #1 draft, LIVE disabled and deployed experiment frozen.

See [target management](OPTIONS_TARGET_EXITS.md),
[entry premium limits](OPTIONS_SCOPE_MANAGEMENT.md),
[position outcomes](OPTIONS_POSITION_OUTCOME.md) and [source of truth](SOURCE_OF_TRUTH.md).
