# Scope admission after a paid decision

`app.options.scope_reapproval.review_paid_scope` is a read-only prerequisite for
shared Scope AI. It verifies the original admission, the intervening settled model
charge and a new revision-bound owned admission. It grants no native order authority.
The deterministic shared coordinator still rejects model enrollment. Full shared
Scope model request/result binding, atomic consumption and trade-outcome cost
attribution remain the next integration work.

## Why a second admission is necessary

A Scope entry packet names the journal revision at which its account, sampled
arming, contract and management were reviewed. Model attempt and usage events
advance that revision and reduce available risk budgets. Reusing the first packet
would waive both the revision and post-cost account checks. Replacing it with the
latest packet alone would lose the original decision's price and expiry ceilings.

The caller must retain the original immutable admission action, durably record the
model attempt and usage, obtain genuinely newer observations for every required
Scope stream, and call the existing watch `review_admission` again. A repeated
quote or receipt-only timestamp refresh cannot stand in for a fresh observation.
An expired arming hold, changed market, unknown bill or reduced capacity can stop
this path. The original selection is never refreshed in place.

## Read API

Within one journal read transaction, call:

```python
review_paid_scope(
    engine, db, scope_watch_policy,
    original_action_key=original_action,
    play_key=selected_play,
    expected_revision=current_revision,
    model_source_key=paid_cycle_source,
    request_hash=retained_request_hash,
    decision_hash=retained_decision_hash,
    now=now,
)
```

The function reconstructs the original packet from its stored watch action and
audit event, checks its original-call binding, and obtains the latest packet through
`select_entry`. It does not accept caller-supplied account balances or replacement
plans. Both actions must name the same account, population, original call, play,
watch and owner policies. The latest revision must still be exact.

The contract, proposal, geometry, target schedule, premium protection, allocation,
quantity, session protection and effective limits stay fixed. A cheaper fresh
admission may fit the original price/debit/full-premium-loss/exit-fee ceilings;
higher costs or a different quantity reject the review. Quantity reduction needs
a new management plan and cannot silently alter the model's selected Scope plan.
The usable deadline is the earlier of the two admissions, never the new lease alone.
Option and underlying source/receipt clocks and account capture time cannot regress.

The paid call must have a complete usage receipt whose request and decision hashes,
request ID, model and exact Decimal charge match the stored cost policy and call.
Its attempt and settlement events must occur once, in sequence between the two
admission actions, with matching timestamps and payloads. The current account must
exactly match the post-cost admission and remain entry eligible. Other unresolved
entry or management costs continue to block the owner's risk budgets. Independent
owners cannot borrow one another's receipt or charge.

The returned hashed diagnostic retains both packet hashes, both bindings, both
native source identities, the model charge, current account hash and the original
bounded deadline. Both `authority` and `live_enabled` remain false. Reading it
writes no events, decisions, orders or cost rows and is repeatable at the same
revision. A review hash is correspondence evidence, not a provider signature.

## Deliberately separate remaining boundary

A fresh admission has a different native Scope source identity. The future shared
AI coordinator must retain the original alternatives and full model response,
bind the selected plan to this review, and atomically consume it while attributing
the paid cycle to the resulting native entry and every scale/final exit. This API
checks charge correspondence; it does not establish that the model selected this
play or attach the charge to a trade outcome. No existing deterministic enrollment
can use it to bypass shared selection, convert a HOLD into an order, or enable AI.
Unknown cost is never converted to zero. Existing full-account export includes all
recorded charges regardless of selection; native trade attribution needs its explicit
integration before shared Scope AI can be enabled.

Installed fixtures cover CALL/PUT, newer admission after settled costs, unchanged
original terms, bounded expiry, stale revisions, unknown and foreign calls, changed
cost/audit/original evidence, event ordering, independent owners and refusal of
native preparation without common selection. The tests also retain the existing
shared selection, owned admission and native execution boundary regressions. See
[status](SLICE2_STATUS.md) for exact installed results. No real model/provider/broker
request, deployment or dependency change is part of this work.
