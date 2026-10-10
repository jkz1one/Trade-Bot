# Broader entry reasoning contract and bounded worker

P2 contract and native worker slices. `app.options.entry_reasoning` adds a pure, tool-less
proposal/review boundary alongside the unchanged SELECT/HOLD model. It makes no
model/provider call, opens no database and has no order or execution authority.
The separate `entry_judgment` / `entry_judgment_worker` protocol can request a plan
from the model. Neither is wired into the current coordinator, runtime or observer.

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

## Native model boundary

`configuration(costs, limits, entry_policy)` freezes prompt/schema hashes, model,
configured token prices, policy and process/token ceilings. Maximum configured
token charge must fit the per-call cost reservation. `create_request` binds this
configuration to the packet, unique request ID, parent PID and original remaining
lease. It does **not** reserve or settle costs: the caller must durably admit an
attempt before starting the child, then record its result or uncertainty.

`run_entry_process(request, api_key)` starts the installed Python module with `-I`,
a separate process group and an environment limited to the model key plus basic
locale/path fields. The child has no broker tools, credentials or journal handles.
This boundary is not an OS filesystem/network sandbox. The SDK origin is fixed,
retries are disabled, and the same full strict-schema payload is counted before
one generation attempt. It uses no tools, streaming, background work or storage.
The model receives explicit binding hashes and evidence IDs, not a hash-computation
task. Its output is initially reviewed against the supplied original evidence;
that review does not replace fresh, post-cost deterministic dispatch approval.

Request/response pipes are capped at 256/128 KiB. The parent bounds the call and
reaps the process group on timeout, overflow, invalid output and cancellation,
including repeated cancellation. The child uses the existing parent/deadline
watchdog. Success requires matching request/configuration/packet identity, model,
input count, bounded usage and an acceptable strict plan. Refusal, incomplete or
malformed output and invalid geometry yield a bound HOLD. Error strings contain
only exception class names; valid usage captured before rejection is retained.
An error receipt may preserve mismatched usage as evidence, not settled cost.
Missing usage, a lost child or an undecodable receipt remains unknown to the
future durable caller; none establishes that no billable request occurred.

Tests use real SDK serialization with fake responses and native subprocesses.
They do not establish authentic model latency, compatibility or economics. No
service, cohort enrollment or broker path invokes this worker yet.

## Integration boundary and next work

Do not pass only the nested `OptionProposal` to existing execution and claim broader
reasoning is enabled: that type does not retain this target/horizon/condition.
Next P2 work must add durable coordinator receipts for the versioned native
request, freeze enrollment, persist the full plan and its exit requirements,
settle usage before review, and revalidate at dispatch without renewing authority.
Target/time management must be enforced independently of future model availability.
Existing protective exits remain authoritative. No API here changes a frozen cohort.

Adversarial tests cover both CALL and PUT, changed geometry, foreign/stale outputs,
unknown references, invalid terms, HOLD, trigger sides, cost-reduced sizing,
original ceilings/deadlines, fresh admission and tampered packet revalidation.
Installed-package regression proof is recorded in [status](SLICE2_STATUS.md).
Authentic market/model acceptance, durable integration, position-management proposals
and deployment remain open. See [the completion plan](AI_TRADER_RESEARCH_PLAN.md).
