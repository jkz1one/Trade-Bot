# Native PAPER loss cooldown and lock

Current extension: [native Scope execution/loss integration](OPTIONS_SCOPE_EXECUTION.md)
is available only to explicitly enrolled new PAPER owners. Existing research versions
retain the boundaries below. The native extension supports responsive/balanced
one-to-three-contract plans; convexity and missing-T3 four-contract plans stay blocked.

New populations can explicitly freeze `OptionExecutionPolicy.loss_control` with a
`NativeLossPolicy`. It allows a maximum consecutive-loss threshold of one or two
and a cooldown of at least 1,800 seconds (at most one day). These preserve the
pinned Scope two-loss/30-minute baselines as conservative bounds. They are research
settings, not approved LIVE limits.

This is an **account-wide common-engine guard**, also used by native Scope integration.
It applies to every native entry in its explicitly enrolled population, including
shared Degen/Swing entries. Native Scope derives its label only from a consumed
watch receipt. Optional family controls below add stricter independent checks. Independent populations
retain separate state. Existing
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
global `resume` command do not clear it. Only the separately signed reviewed
`RESET_LOSS_LOCK` operator command can clear an eligible account-wide lock;
deleting state or changing its frozen policy is not a recovery path.

Previously consumed outcomes are revalidated. Changed or missing economic evidence,
rewound clocks, future closing evidence and capacity overflow fail closed. No new
outcome is consumed across an incomplete history. Outcome rows, state and audit
events commit together or roll back together. History is bounded to 200 buy intents
and 2,000 native orders; overflow blocks entries rather than discarding old losses.

## Enforcement and inspection

### Reviewed account-wide reset

The existing [local operator capability](OPTIONS_OPERATOR_RECOVERY.md) now accepts
`RESET_LOSS_LOCK`. The read-only review artifact includes stored loss state at the
exact event revision. Submit signs that saved revision; the owner rejects stale
reviews rather than silently substituting fresh evidence. Signature, journal,
population, generation, command ID and expiry checks are unchanged. A model has
no signing key or reset tool.

Reset requires an already locked, explicitly enrolled account, expired cooldown,
fresh matching account/supervision, no open position or working order, known model
costs, positive remaining daily/total loss budgets, and no active model/runtime task
or runtime blocker. The owner revalidates every consumed outcome and rejects
incomplete or changed history. Newly consumed outcomes require another review;
their risk state can persist even when the reset request is rejected. Refreshing
evidence cannot shorten a new loss's recognition-time cooldown.

An applied reset sets the consecutive-loss streak to zero and clears only the
account-wide loss lock. It retains the expired cooldown timestamp, consumed outcome
records and hashes, all entry/management charges, ledger balances, daily P&L,
global limits, and any global halt. Future losses count normally; prior losses are
not counted twice. It does not clear Scope's separate research or direction gates.
The audit binds command ID, actor/reason, exact reviewed revision, population,
event time, and prior/new state. State, audit and command receipt commit atomically;
an authenticated replay returns the original result without another reset.

This is common account recovery; Scope's separate targeted reset is described below. It
does not approve an order, resume a globally halted runner, or enable LIVE.

### Entry gates and stored reads

`OPEN_LONG` preparation and dispatch both refresh and enforce this guard. Dispatch
excludes only its own still-unattempted prepared buy from pending-outcome detection.
Blocked preparation records the normal rejected decision. Blocked dispatch records
`REJECTED`, clears the active order lock and starts no attempt/worker. HOLD, owned
CLOSE, management and protective exits retain their existing gates.

The journal report's `loss_control` field is stored evidence, with its last checked
time and reasons; reading it does not refresh risk or authorize a trade. Refreshing
risk never changes cash, P&L, settlement, fee/model records or global limits. The
guard now also runs at `begin_model_attempt` for entry reasoning and candidate
selection, before a model-attempt/unknown-cost row is written. Newly recognized
outcomes, cooldown state and a source/input-bound `OPTION_ENTRY_MODEL_RISK_PAUSED`
event commit together before `EntryModelBlocked` is returned. An expected loss
pause starts no worker and adds no model charge. Corrupt or changed history still
fails closed through the normal failure path.

The coordinator completes an expected pause as `HOLD` with
`ENTRY_MODEL_RISK_PAUSE` and the specific blocker. It does not add a global halt
that would prevent normal cooldown expiry from allowing a future cycle. Historical
cycle retries return the saved result without another model attempt or risk event.
Account reconciliation, data selection and packet construction may still occur;
this is the final pre-call cost gate, not a promise of zero data/host costs.

Owned-position model requests use their existing strict request, position,
revision, cost and account gates. They skip the entry-only loss pause so a pending
entry outcome cannot disable MAINTAIN or EXIT_ALL reasoning. Every admitted
management charge remains recorded. Passing a nonempty arbitrary position request
does not bypass its existing validation. Ordinary HOLD, CLOSE and independent
protective exits retain their normal rules. In-flight calls are not canceled or
refunded; the existing preparation/dispatch checks remain authoritative afterward.
Unenrolled cohorts preserve their existing model-admission behavior.

The [Scope research entry guard](OPTIONS_SCOPE_OWNED_ADMISSION.md#native-execution-boundary)
remains in force for research cohorts. Separately enrolled native Scope now has
watch/order association, full-cost family consumption/reset, dispatch/management,
fixture replay and stored observer labels. Convexity and missing-T3 four-contract
plans remain blocked; authentic provider and visual acceptance remain open. LIVE stays disabled and the deployed experiment stays frozen.

## Optional native family controls

New cohorts can additionally freeze `NativeLossPolicy.families` with up to three
unique `FamilyLossPolicy` entries: `DEGEN`, `SWING` and `SCOPE`. Each has a loss threshold
of one or two and a cooldown of 1,800–86,400 seconds. Omitted families preserve
legacy serialization. Adding or changing family enrollment requires a new cohort;
SCOPE uses the separate native watch receipt and explicit owner enrollment. Its
research-only entry guard remains in force for existing cohorts.

The account-wide guard still applies to every entry. Each enrolled family also
has its own consumed-entry count, consecutive-loss count, recognition-time cooldown
and sticky lock. A Swing WIN/FLAT cannot clear Degen's streak or lock. Complete
outcomes carry the verified selected-entry lineage in their stored/hash-bound
records, with all attributable entry/management model charges and execution fees.
Unknown costs still block consumption. Accounts never share state. Data/host costs
remain in session economics, outside this operational outcome basis.

All new entries in a family-enrolled cohort require stored selected-candidate
or consumed Scope-watch lineage, including entries from a family without an additional rule. Preparation
and dispatch refresh the global guard and then enforce the selected family's
pause. Direct unlabeled entries cannot bypass family review. HOLD, owned CLOSE,
validated paid management and independent protection retain their normal gates.

Before paid entry reasoning, the owner requires a valid stored candidate set and
pauses when every candidate family is locked or cooling down. A mixed packet with
an unpaused family may proceed unchanged. The model can still choose a paused
family: preparation rejects that choice and the call's cost remains recorded.
This is not candidate filtering or a promise that every paid call yields a trade.
No model worker or unknown-cost row is started for a family pause.

A signed `RESET_LOSS_LOCK` may specify `loss_family=DEGEN`, `SWING` or `SCOPE` (CLI:
`--loss-family DEGEN`). It uses the same exact-revision, signature, fresh flat
account, known-cost, positive budget and idle-runtime checks as account recovery.
The selected family must already be locked and its cooldown must have elapsed.
The owner revalidates all consumed outcomes; new outcomes require another review.
A family reset clears only that family's streak and lock, retaining its consumed
history and expired cooldown timestamp, the account-wide lock/cooldown, other
families, all economics and any global halt. Omitting the target resets only the
account-wide lock, leaving family locks intact. The target is signature-bound and
recorded in the atomic audit/receipt; replay cannot apply it twice. A target on
HALT, RESUME or REVOKE_KEY is invalid. No reset grants trading or LIVE authority.

## Session replay and export

Enrolled replay owners now refresh risk after final session reconciliation and
before saving their independent boundary snapshots. Complete final trades are
consumed even when no later entry cycle occurs; unknown outcomes remain pending.
The [read-only exporter](OPTIONS_EVALUATION_EXPORT.md#native-loss-control-evidence)
retains cumulative state, exact consumed economics/lineage hashes, pause events
and reset receipts. Export itself never refreshes or resets risk. Later sessions
must preserve prior risk evidence, and portable reports label it as stored state.
