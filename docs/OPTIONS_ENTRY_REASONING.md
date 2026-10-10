# Offline broader entry reasoning contract

First P2 contract slice. `app.options.entry_reasoning` adds a pure, tool-less
proposal/review boundary alongside the unchanged SELECT/HOLD model. It makes no
model/provider call, opens no database and has no order or execution authority.
It is not wired into the current coordinator, worker, runtime or observer.

## Inputs and review

Trusted software constructs an `EntryPacket` from existing admitted Degen
candidates, their exact scan/quotes/session, account, frozen limits and explicit
`EntryReasoningPolicy`. Each opportunity exposes hash-checked evidence IDs in its
serialized packet. The packet binds a decision ID, model-configuration digest,
five-minute opportunity, evidence time and original deadline. Construction checks
unique candidates, confirmed matching setup geometry, exact candidate fingerprint,
reproducible original admission and a 256 KiB serialized limit. These are integrity
checks, not authentication of provider data or proof the caller obtained it honestly.

`EntryPlan` permits HOLD or ENTER with a supplied candidate ID, underlying target,
invalidation, horizon, evidence references, thesis and uncertainty. Entry conditions
are NOW, ABOVE or BELOW with an explicit underlying trigger when needed. No option
premium target, quantity, contract creation, code, risk override or free-text action
is accepted. HOLD carries no entry terms. Money rejects floats, booleans, nonfinite
values and excessive decimal precision/exponents.

`review_entry_plan(packet, plan, quote=..., underlying=..., account=..., now=...)`
revalidates the full packet and output, including unchecked `model_copy` changes.
Caller-owned fresh account evidence must already reflect settled model costs;
this pure function cannot establish that a durable cost receipt exists. Output
must bind the exact packet/decision and selected evidence, within the original
deadline. HOLD needs no new quote or account access.

For ENTER, deterministic review:

- Rejects instrument changes and source/account time regressions.
- Allows original invalidation or tightening, never widening; checks CALL/PUT
  target and stop geometry against conservative current underlying quote sides.
- Enforces explicit target/trigger distance and minimum reward/risk geometry.
  This underlying ratio is not option expected return or guaranteed stop loss.
- Anchors the horizon to the original packet time, bounded by policy, entry cutoff
  and contract last trading time; waiting cannot extend the planned exit.
- Runs fresh existing option admission for entitlement, freshness, account health,
  fees, executable liquidity and money limits. Known lower remaining budgets shrink
  quantity. Lower premiums cannot increase original quantity; higher required
  entry prices cannot exceed the original price ceiling.
- Caps debit/full-premium loss and deadline at the original admitted envelope.
  ABOVE uses underlying bid and BELOW uses ask. An unmet condition ends as HOLD,
  with no standing instruction or order reservation.

The result is HOLD, REJECTED or ELIGIBLE, always `execution_authority=false`.
ELIGIBLE retains the complete plan, reviewed proposal/admission and absolute
`exit_by`. Evidence hashes establish correspondence, not truth of model reasoning.

## Integration boundary and next work

Do not pass only the nested `OptionProposal` to existing execution and claim broader
reasoning is enabled: that type does not retain this target/horizon/condition.
Next P2 work must add a versioned native model request and durable coordinator
receipts, freeze enrollment, persist the full plan and its exit requirements,
settle usage before review, and revalidate at dispatch without renewing authority.
Target/time management must be enforced independently of future model availability.
Existing protective exits remain authoritative. No API here changes a frozen cohort.

Adversarial tests cover both CALL and PUT, changed geometry, foreign/stale outputs,
unknown references, invalid terms, HOLD, trigger sides, cost-reduced sizing,
original ceilings/deadlines, fresh admission and tampered packet revalidation.
Installed-package regression proof is recorded in [status](SLICE2_STATUS.md).
Authentic market/model acceptance, durable integration, position-management proposals
and deployment remain open. See [the completion plan](AI_TRADER_RESEARCH_PLAN.md).
