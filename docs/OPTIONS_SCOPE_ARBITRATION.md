# Shared Scope, Degen and Swing selection

`shared-scope-selection-v1` adds deterministic candidate selection to one newly
frozen options PAPER owner. Scope, Degen and optional session-close Swing share
one coordinator, five-minute entry claim, native ledger, reservation and loss
controls. Each research account still owns its separate journal and capital.
Existing Scope-only and Degen/Swing populations do not migrate.

This documents the frozen deterministic selection baseline. Separately enrolled
[shared Scope entry AI](OPTIONS_SCOPE_AI.md) now connects paid entry decisions,
post-cost owned admission and native cost attribution. Shared position reasoning,
continuous watch ingestion, common A/B/C/D Scope tapes, combined carry/Scope and
mixed stock/options ownership remain open. Both paths are offline fixture
capability, not authentic provider or trading-edge acceptance.

## Explicit enrollment and inputs

Set `OptionExecutionPolicy.scope_arbitration="shared-scope-selection-v1"` together
with the existing native Scope policy. Enroll account loss control plus a family
loss policy for every enabled family. Pass a `SharedScopePolicy` to
`DegenCoordinator(..., scope_policy=...)`; it contains the full native
`ScopeWatchPolicy` and an explicit unique `family_priority`, covering DEGEN/SCOPE
and SWING exactly when `swing_policy` is supplied. There is no default priority or
implicit new risk limit. Existing native Scope profile/quantity requirements apply.

The coordinator creates `scope_book` in the same owner. Use its existing call,
quote observation, sampled arming and direction-reset APIs with exact revisions.
These are explicit supplied-evidence operations; this slice does not synthesize
calls, confirmations or missed samples. Arming still needs its faster sampled
cadence. The five-minute entry cycle cannot replace those samples.

A `DegenFrame.scope` contains a `ScopeCycleInput` with the exact active `play_key`,
current `ScopePreflightInput`, `ScopeContextInput` and executable underlying quote.
The ordinary frame retains the exact Degen/Swing quote coverage. An active unfilled
Scope watch requires its matching input; omitting it cannot make Degen win by
hiding a competing watch. An absent/ended Scope watch requires no Scope input.
The quote plan for Degen/Swing is unchanged; Scope's contract is already locked by
its watch, and its supplied evidence is separately validated.

No model settings or scripted replay model may enroll in this v1 coordinator.
Recorded model expenses remain expenses; disabling new calls does not erase past
entry/management charges or treat an unresolved call as free. The existing separate
Degen/Swing AI populations keep their previous behavior and configuration hashes.

## Selection, native authority and lifecycle

After common reconciliation, held/unresolved orders take precedence. Only a flat,
healthy owner collects entry candidates. The cycle performs a fresh Scope owned
admission after other journal events, then retains its exact packet alongside
admitted Degen/Swing candidates. No intervening event can silently refresh its
revision. An ordinary ineligible Scope admission remains visible while separately
valid candidates may compete; it never substitutes SPY, another contract or a
later expiry for that Scope play.

Frozen family priority selects the first admitted candidate. Existing deterministic
ordering within Degen/Swing remains stable. The receipt retains every candidate's
family, identity, hash and native source, the policy hash, cycle and selected entry.
If fresh preparation or dispatch rejects that selection, the cycle stops. It does
not submit the second choice or retry an expired Scope plan.

Both generic entry and `scope_book.prepare_entry` must pass the common selection
boundary. A source key, admission ceiling or direct Scope request cannot bypass
it. The decision, order, selection audit event and Scope consumption (when selected)
commit together. A write failure rolls them back. Repeated cycles return the stored
receipt; an interrupted cycle stays interrupted. Native dispatch rechecks original
selection and family membership before an attempt, then applies all ordinary
account, loss, current quote, price and freshness gates.

Scope retains its exact original admission quantity, price ceiling, fee reserves,
contract, setup, targets, profile stop, protection time and called-play consumption.
Responsive/balanced one-to-three-contract support is unchanged; convexity and
four-contract missing-T3 plans remain rejected. Degen/Swing do not inherit Scope's
SPX targets. Filled Scope cycles use the exact supplied Scope quote for independent
native target/stop/deadline protection. Manual and protective scales keep their
original entry identity and selection receipt. No quote observation grants a fill.

Restart verifies the frozen coordinator/watch configuration and selected evidence.
Shared alternatives also bind to the original immutable Scope admission action,
so later watch observations cannot rewrite an earlier selection. Scope and family
loss counters retain full-cost exactly-once outcomes; a partial exit is not a closed
trade. Common account halts and unknown cost still fence every entry family.

## Stored views and portable accounting

The read-only observer shows the shared family set, Scope candidate, selection
receipt and actual native proposal/approval/attempt/fill attribution. SCOPE filtering
includes its shared cycles. Stored Scope quotes also supply held-position evidence;
reading a page performs no sampling or entry work. This is data plumbing for the
later UI pass, not completed visual acceptance.

`export_scope_execution(journal, now=..., data_cost=..., host_cost=...)` recognizes
explicit shared owners and emits `shared-scope-native-export-v1`. Scope-only exports
retain `scope-native-export-v1`. The existing verifier reconstructs the fixed native
schema in memory, including Swing seed locks, every native entry/exit, Scope actions,
selection receipts, loss outcomes and the whole account cash/fee ledger. It accepts
only the owner's enrolled families and verifies each selection against retained
history. It grants no restore or execution authority.

Net cash after all costs subtracts every recorded entry/management model charge
and explicit data/host costs. Execution fees are already in the conserved cash
ledger. Open holdings, unresolved orders, incomplete outcomes, unknown calls or
missing operating costs suppress the net result. A family filter cannot remove
another family's cost. Retain the export hash independently; portable verification
does not prove provider authenticity or historical operator signatures.

## Reproduce

Use the isolated noneditable wheel procedure in [testing](OPTIONS_TESTING.md), with
copied tests outside the checkout and the installed interpreter's `-I` flag.
`tests/test_option_scope_arbitration.py` contains the complete supplied-evidence
setup, including native Scope enrollment, arming samples, combined frames and
independent owners. Run it with the Scope execution/replay, Degen/shared strategy,
entry-lineage, position-outcome, family/account loss, carry and observer regressions.
`tests/test_option_scope_arbitration_history.py` additionally checks later watch
termination against original alternatives and entries without an active Scope watch.
Retain a distinct pytest base directory so later runs do not discard fixture evidence.

Coverage includes CALL/PUT selection of each family, Scope-only eligibility,
ineligible/missing Scope, direct-entry bypass rejection, one order per cycle,
partial/final exits, fees and known/unknown advisory costs, restart, altered receipt
rejection before an attempt, atomic write failure, independent-account isolation,
held target protection and detached accounting. Exact installed results are in
[status](SLICE2_STATUS.md).

Main stays untouched, PR #1 stays draft, LIVE stays disabled and the deployed
experiment stays frozen. No provider/model/broker, host or dependency change is
required to run these offline fixtures.
