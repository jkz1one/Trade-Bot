# Native PAPER loss cooldown and lock

New populations can explicitly freeze `OptionExecutionPolicy.loss_control` with a
`NativeLossPolicy`. It allows a maximum consecutive-loss threshold of one or two
and a cooldown of at least 1,800 seconds (at most one day). These preserve the
pinned Scope two-loss/30-minute baselines as conservative bounds. They are research
settings, not approved LIVE limits.

This is an **account-wide common-engine guard**, a foundation for Scope integration.
It applies to every native entry in its explicitly enrolled population, including
shared Degen/Swing entries. It does not label trades as Scope or replace future
family-specific controls. Independent populations retain separate state. Existing
cohorts omit the field and retain their original serialized configuration; policy
cannot be added, removed or changed on reopen. No existing cohort is enrolled.

## Outcome consumption

`engine.refresh_loss_control(now=...)` runs inside the existing owned journal,
transaction, lifetime lease and paired restore fence. It rebuilds each filled buy's
stored native outcome and records each complete outcome once, retaining the exact
entry, closing time, quantities, premiums, fees, settlements and attributed model
calls. It accepts no caller-supplied P&L, outcome or loss count.

The operational basis is net execution cash flow after all recorded trading fees
and attributable entry/management model charges. This is not an all-in economic
return: data/host allocation and authentic settlement-fee coverage remain outside
this fixture basis. Existing global cash, daily/total loss and model-spend budgets
remain authoritative. Known unallocated calls and unknown usage cannot silently
become zero: an incomplete outcome blocks another entry. Open/partially filled
positions also block; terminal never-filled attempts neither count as losses nor
clear a streak. Their charges still remain in account-level economics.

A verified LOSS increments the streak and starts or extends cooldown from the
**actual recognition time**. Delayed reconciliation cannot backdate the cooldown.
Before lockout, a verified WIN or FLAT breaks the consecutive-loss streak, but
cannot shorten a still-running cooldown. Once the threshold is reached the lock
is persistent: elapsed time, restart, date change, later outcomes and the existing
global `resume` command do not clear it. There is deliberately no reset command in
this slice. Reviewed scoped reset is still required before a locked cohort can
trade again; deleting state or changing its frozen policy is not a recovery path.

Previously consumed outcomes are revalidated. Changed or missing economic evidence,
rewound clocks, future closing evidence and capacity overflow fail closed. No new
outcome is consumed across an incomplete history. Outcome rows, state and audit
events commit together or roll back together. History is bounded to 200 buy intents
and 2,000 native orders; overflow blocks entries rather than discarding old losses.

## Enforcement and inspection

`OPEN_LONG` preparation and dispatch both refresh and enforce this guard. Dispatch
excludes only its own still-unattempted prepared buy from pending-outcome detection.
Blocked preparation records the normal rejected decision. Blocked dispatch records
`REJECTED`, clears the active order lock and starts no attempt/worker. HOLD, owned
CLOSE, management and protective exits retain their existing gates.

The journal report's `loss_control` field is stored evidence, with its last checked
time and reasons; reading it does not refresh risk or authorize a trade. Refreshing
risk never changes cash, P&L, settlement, fee/model records or global limits. The
guard is a final entry boundary, not a model-call scheduler: proposal calls can
still incur costs, which remain accounted for. Runtime/model preflight integration
remains separate work.

The [Scope research entry guard](OPTIONS_SCOPE_OWNED_ADMISSION.md#native-execution-boundary)
remains in force. Watch/order association, family-scoped consumption/reset,
complete path coverage, Scope dispatch/runtime/replay and dashboard controls remain
open. LIVE stays disabled and the deployed experiment stays frozen.
