# Scope management plans and entry premium protection

New research books may explicitly enroll `ScopeWatchPolicy.management` with a
`ScopeManagementPolicy`. It requires the existing frozen arming, contract and owned
admission policies. A successful fresh admission stores a management review using
the selected contract observation, original geometry and the common governor's
actual approved quantity. The caller cannot supply a replacement quantity, profile,
target or account balance to this review.

The review remains research evidence: `authority=false`, `live_enabled=false` and
`native_execution_ready=false`. Passing this plan review does not enable Scope
orders or complete its full management acceptance. The generic native entry guard
remains in force.

## Source rules and the missing third objective

The pinned SignalFlow reference is commit
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Its
`play_orchestration._entry_sizing_plan()` explicitly selects the **balanced sizing
profile for Scope**, independently of the Responsive/Balanced/Convexity contract
classification. `play_sizing.allocation_plan_for_quantity()` defines these whole
allocations:

| Approved contracts | T1 | T2 | T3 | Runner | Current plan review |
| --- | --- | --- | --- | --- | --- |
| 1 | 0 | 1 | 0 | 0 | One full exit at locked T2 |
| 2 | 1 | 0 | 0 | 1 | One exit at locked T1, one protected runner |
| 3 | 1 | 1 | 0 | 1 | One exit at each locked objective, one protected runner |
| 4 | 1 | 1 | 1 | 1 | Blocked: approved Scope geometry has no T3 |

Our existing Scope geometry and the reference `scope_wizard.py` supply exactly two
Scope objectives. The reference emits `scope_t1` and `scope_t2` candidates, while
the generic `_select_targets()` accepts neither method and can fall back to its
generic fixed-R targets. Copying that fallback would replace the locked Scope
objectives. This implementation does not do so.

A four-contract review retains the source allocation, including the distinct T3
contract and runner, but returns `SCOPE_THIRD_TARGET_UNSPECIFIED`, `passed=false`
and no native schedule. It does not silently sell the T3 allocation at T2, invent
a price, relabel it as runner or reduce an approved four-contract size to three.
The account admission can remain eligible while this separate management plan is
blocked. Resolving the third objective/allocation remains a recorded Scope gate.

For one through three contracts, the review produces the existing native
`TargetExitSchedule` at the exact locked prices. Its stage index counts executable
steps: for a one-contract plan, native stage 1 refers to Scope T2. It is not a new
Scope target label. Any stricter cash, fee, liquidity or exposure limit has already
reduced quantity through the common governor before allocation occurs.

## Source estimate versus enforceable protection

The pinned orchestrator uses premium-stop **estimates** of .35 for Responsive,
.45 for Balanced and .60 for Convexity in its sizing calculation. These are not
proof of executed stops or guaranteed maximum losses. Our explicitly enrolled
`ScopeManagementPolicy` requires separate loss-fraction values no larger than
those reference ceilings:

```python
ScopeManagementPolicy(
    responsive_loss_fraction=".35",
    balanced_loss_fraction=".45",
    convexity_loss_fraction=".60",
)
```

The stored plan records the source estimate separately. Its proposed native
`EntryPremiumProtection.maximum_loss_fraction` is the smaller of the enrolled
profile fraction and the owner's frozen premium-catastrophe fraction. For example,
an owner limited to .20 keeps .20 even when the Balanced policy specifies .45.
Convexity remains blocked by incomplete path evidence and cannot obtain a passed
management plan. No profile threshold weakens account-level full-premium sizing.

Separately, a new native PAPER owner can enroll
`OptionExecutionPolicy.entry_premium_protection="tighten-only-v1"` and supply an
`EntryPremiumProtection` through the trusted deterministic OPEN_LONG preparation
API. Preparation rejects fractions above the owner's limit. The object freezes in
decision inputs, approval and buy intent; dispatch rechecks both binding and the
owner ceiling. It is not a model field, cannot attach to a CLOSE, and does not alter
existing AI entry plans or old cohorts.

Verified buys carry the object into the owned position. Fresh executable option bid
is compared to actual remaining FIFO premium basis, using the tighter of entry and
owner limits. A boundary touch latches the ordinary `PREMIUM_CATASTROPHE` full-exit
reason. Target scales, partial fills, reconciliation and restart retain the entry
protection. Rebounds cannot erase its latch. Original/tightened underlying stops and
time/expiry exits keep their precedence. Missing or stale executable bids retain
the existing supervision block rather than manufacturing a trigger or fill.

Actual execution fees, entry/management charges and full-premium reserves remain
in native accounting. Neither a stop estimate nor a tighter exit threshold discounts
the debit or full-premium loss admission. A trigger is not a guaranteed sale price;
unknown/working orders still retain reservations. Stored close attribution inherits
the exact original entry protection. Independent owners retain independent thresholds.

## Stored evidence and acceptance

Management reviews retain policy, contract observation, exact geometry, source
allocation, native schedule/protection, admission and contract-scan hashes, and the
original validity window. Exact action retries return the historical receipt. Failed
fresh admission replaces the old review without retaining an old management plan.
Existing research books cannot add or change management policy on reopen.

The observer validates stored policy, geometry, admission identity/quantity/times
and owner premium limit. It displays the saved plan with the admission's stale-time
label. Reads do not refresh arming, rerun profile selection, allocate again or submit
orders. Inconsistent stored plans become unavailable rather than repaired on read.

Fixture/native-worker acceptance covers both directions and profiles, one-to-four
contract reviews, exact premium boundaries, tighter owner/profile limits, all native
fees and entry/management-cost regressions, target/stop races, runner/restart
retention, independent owners, stale evidence, tamper rejection and rollback.

Scope still requires reviewed four-contract allocation, native watch/entry linkage,
complete obstruction coverage, Scope family loss/reset, full management behavior
and runtime/replay acceptance. The shared native target engine now supports
[explicit frozen stop adjustments](OPTIONS_TARGET_EXITS.md#optional-frozen-target-stops),
but Scope previews omit those fields until actual entry binding defines their prices.
The separately enrolled [v2 native milestones](OPTIONS_TARGET_EXITS.md#stop-only-target-milestones)
now support tightening at objectives with no sale allocation. Scope previews remain
v1 and require actual-entry binding before using this capability.
Native [fill-bound underlying observations](OPTIONS_FILL_UNDERLYING.md) now retain
separate quotes for actual option fills, including partial-fill coverage and explicit
missing evidence. This supplies the evidence dependency; it does not yet define
Scope's fill-bound stop rule, change its previews or authorize its native entries.
The shared [premium trail](OPTIONS_PREMIUM_TRAIL.md) now has a separate frozen-owner
enrollment; full Scope management and its strategy-specific enrollment remain open.
Authentic provider/calendar/host, prospective economic and UI acceptance
remain separate. Main untouched, PR #1 draft, LIVE disabled and deployment frozen.

See [target execution](OPTIONS_TARGET_EXITS.md), [owned admission](OPTIONS_SCOPE_OWNED_ADMISSION.md),
[contract profiles](OPTIONS_SCOPE_CONTRACTS.md), [partial closes](OPTIONS_PARTIAL_CLOSE.md)
and [source of truth](SOURCE_OF_TRUTH.md).
