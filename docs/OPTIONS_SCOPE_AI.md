# Shared Scope entry AI

`shared-scope-entry-v1` enrolls a new PAPER owner in one paid entry decision across
Scope, Degen and optional session-close Swing. It shares the native cash ledger,
reservation and account/family loss controls. Independent research owners keep
separate journals, capital and costs. Existing deterministic shared Scope and
Degen/Swing model populations retain their frozen configuration and behavior.

This is fixture-tested entry plumbing, not authentic model/provider acceptance,
a profitability result or permission to deploy. [Shared Scope position-model enrollment](OPTIONS_SCOPE_POSITION.md) is separately
opt-in for new owners. Common A/B/C/D Scope tapes, continuous watch ingestion and combined
Scope/carry enrollment remain separate work. Native Scope target, profile-stop and
time protection remain independently deterministic.

## Explicit enrollment

Use `OptionExecutionPolicy.scope_arbitration="shared-scope-entry-v1"` with the
existing native Scope enrollment and a loss policy for every enabled family.
Use `SharedScopePolicy(version="shared-scope-entry-v1", watch=..., family_priority=...)`.
The full watch policy and family set remain frozen; the priority orders evidence,
while the model may choose any admitted family or HOLD.

Pass the existing explicit `EntryReasoningPolicy`, adding
`scope_selection="scope-fixed-plan-v1"`, with `judgment_limits`, the absolute private
`key_file`, and an asynchronous `scope_refresh(play_key)` reader to `DegenCoordinator`.
The reader returns a `ScopeCycleInput` for the exact selected play. It supplies new
normalized observations, never balances, replacement trading terms or approval.
No module here fetches a provider feed on its own. The reader implementation is
not a frozen market-data identity; source/entitlement/clock and watch identity
checks still validate every supplied observation.

The model path requires a new healthy, untraded owner with a frozen cost policy.
Reopening must use the same policies and key path plus an available fresh-input
reader. Legacy deterministic enrollment still rejects model settings. Shared entry
AI rejects the old scripted replay model and combined Swing carry. Position-model
settings require explicit `scope-fixed-position-v1` enrollment; see the linked
management contract. The separate [native C/D tape enrollment](OPTIONS_SCOPE_MODEL_REPLAY.md)
binds full scripted receipts, exact delivered fresh observations and native post-cost
approval without a key file. The old adapter and unbound new adapter stay rejected;
continuous runtime inputs and full comparison remain separate.
No test limits are implied production defaults.

## One request, fixed Scope terms

The existing bounded entry worker receives the admitted Degen/Swing opportunities
and optional strict `ScopeReasoningEvidence` in one packet. Exact active Scope
coverage is mandatory before the request, including when Degen/Swing could trade.
There must be at least one admitted opportunity. No candidates means no paid call;
no active Scope watch permits ordinary Degen/Swing reasoning without a Scope packet.

The new prompt/schema version permits:

- HOLD, with `scope=false`, as a complete paid outcome.
- Degen/Swing ENTER, with `scope=false` and their existing reviewed underlying
  condition, invalidation, target, horizon and evidence references.
- Scope ENTER, with `scope=true`, the supplied fixed-plan digest and evidence
  reference. Condition, trigger, invalidation, target and horizon fields must be
  null. There is no model quantity, replacement contract or management schedule.

The model receives the explicit Scope candidate digest in its binding envelope.
Scope evidence includes the original contract, account/admission, geometry,
management schedule, profile protection and exit deadline. Software verifies the
packet against the retained immutable watch action. Selecting Scope cannot replace
these terms. Pure entry-plan review only accepts Scope's original evidence at its
original time; subsequent approval requires the owned post-cost path below.

Prompt/schema/model/rates and token/time bounds are frozen. The installed child
uses the existing isolated interpreter, bounded pipes, watchdog, fixed SDK origin,
no retries and no tools. Counting uses the same strict payload as generation.
Known usage is retained for HOLD, late or rejected decisions. Lost/foreign usage
remains unknown and fences the owner. An interrupted opportunity is never retried.
These boundaries are not an OS filesystem/network sandbox or proof of real billing.

## Post-cost native consumption

After trustworthy usage settlement, the full request/result, original alternatives
and completion time are rechecked. A Degen/Swing choice follows its existing full-
entry native review. A Scope choice invokes the fresh-input reader once and obtains
a new owned watch admission. The reader wait is bounded by the shared packet's
remaining original lease. Every required Scope source clock must advance; replaying
the old observations fails. Account evidence comes from the owner after all costs.

The [post-cost review](OPTIONS_SCOPE_POST_COST.md) retains original/fresh admission
identities and exact intervening model usage. It refuses changed quantity, trading
terms, expanded fee-inclusive ceilings, stale revision, expired original lease or
unknown cost. No rejection falls through to a second candidate. The earlier of the
original and fresh admission deadlines, also capped by the original shared model
packet deadline, becomes the actual native approval expiry. Clock progress between
family scans and Scope admission is retained; request creation cannot precede its
latest Scope admission.

Native preparation independently validates the complete paid decision, original
selection and current owned review. The native Scope proposal is deterministically
materialized from the fixed plan; the selection receipt and model attribution retain
its paid origin. Decision, order, selection event and watch consumption commit in one
transaction. A write failure leaves no partial order or consumed watch, while the
already incurred model cost and observations remain recorded.

Dispatch, restart and stored attribution verify both immutable admission actions,
full model receipt, original/fresh plan correspondence and original deadline.
Current account/quote/contract/loss checks still apply before any native attempt.
A stored diagnostic alone cannot authorize an order or convert HOLD into ENTER.

## Costs, outcomes and views

The paid five-minute cycle and the freshly approved Scope entry have different
source keys. Attribution now joins them through the verified selection and paid
review, never just by matching a contract. It retains the model proposal, native
approval, actual attempt and observed fills separately. Linked scale and final
exits preserve the same original selection and paid review.

Closed native outcomes count the entry model charge exactly once with all linked
management costs and actual execution fees. Partial exits do not close a trade or
consume a loss outcome. Other unknown/unallocated costs retain the existing
incomplete-result guards. Whole-account portable export still includes every
recorded entry/management charge plus explicit data/host allocations; unknown cost
and incomplete exposure never become zero or an invented net result.

The existing shared native export format verifies the new frozen owner policy,
full paid receipt and source linkage from its fixed typed tables. Read-only observer
views follow the paid cycle and use the stored fresh Scope quote when available.
No dashboard styling or visual acceptance is claimed by this data integration.

## Reproduce and continue

Use the noneditable installed-wheel procedure in [testing](OPTIONS_TESTING.md).
`tests/test_option_scope_ai.py` covers Scope CALL/PUT, Degen/Swing choice, Scope-only
eligibility, HOLD, actual bounded worker with mocked transport, post-cost failures,
unknown/late/invalid responses, restart, write failure, receipt tampering, original
expiry, independent owners, scales/full-cost loss outcomes, portable export and
observer reads. Run with entry reasoning/worker/coordination, shared strategy,
Scope reapproval/native boundaries, lineage, outcome, loss and observer regressions.
Exact installed results are recorded in [status](SLICE2_STATUS.md).

Next: common A/B/C/D Scope replay, continuous watch
input/runtime integration, then remaining family/mixed ownership plumbing and the
final UI/authentic-data acceptance pass. Main remains untouched, PR #1 draft,
LIVE disabled and the deployed experiment frozen.

## Common Scope input checkpoint

[Sealed Scope observations](OPTIONS_SCOPE_MARKET_TAPE.md) now freeze their source/watch
policy and session deadlines and support original-time diagnostic reproduction.
This does not complete independent Scope A/B/C/D native replay/export. Existing
comparison consumers explicitly reject Scope tapes until the full model, fresh
owned admission, deadline, later-fill and all-cost contracts are connected. The
shared Scope AI replay-adapter restriction remains in place.


## Runtime continuation

[Independent Scope A/B/C/D comparison](OPTIONS_SCOPE_COMPARISON.md) and
[continuous Scope runtime inputs](OPTIONS_SCOPE_RUNTIME.md) now have native fixture
plumbing. Earlier open-work descriptions above are historical checkpoints. Combined
Scope/Swing carry, remaining families and mixed stock/options ownership still precede
final UI and authentic PAPER testing. Original paid terms, mandatory protection,
full costs and all authentic acceptance gates remain unchanged.
