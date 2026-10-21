# Continuous Scope runtime inputs

A new local PAPER population can enroll Scope watches, deterministic shared entry
or full shared entry/position reasoning in the installed options runtime. This is
normalized fixture plumbing. It performs no provider collection and does not turn
fixtures into authentic model, provider, host or economic acceptance. LIVE remains
disabled. The deployed experiment is unchanged.

## Frozen enrollment

`RuntimeSettings.scope_policy` carries the same `SharedScopePolicy` as the native
coordinator. `RuntimePolicy.scope_inputs="scope-runtime-inputs-v1"` explicitly
selects the new transport. Owner `scope_execution`, `scope_arbitration`, all family
loss policies, source bindings, SPX universe and the combined eight-contract quote
budget must agree. The existing installed `runtime_cli init` and `run` commands
create and reopen this configuration. Existing populations cannot acquire it.

Model-off enrollment uses `shared-scope-selection-v1`. Full entry reasoning uses
`shared-scope-entry-v1`, the existing frozen key/limits/cost configuration and
`scope-fixed-plan-v1`; optional management also requires
`scope-fixed-position-v1`. The runtime binds its own delivered-input reader before
any cycle. Scope B remains an explicitly isolated replay role; neither old replay
adapters nor the choice-only B adapter can enter this runtime. Combined Scope/Swing
carry remains a separate unfinished contract and is still rejected.

## Delivered packets and watch actions

The private, bounded feed file now accepts `ScopeRuntimePacket`, version
`option-scope-fixture-v1`, with the existing population ID, positive sequence,
recorded time and `DegenFrame`. Its explicit kind is:

| Kind | Meaning |
| --- | --- |
| `WATCH` | Exactly one `ScopeRuntimeAction`, bound to the nested Scope play and observation. |
| `MARKET` | Delivered quotes/context for supervision and fresh post-cost review. No ordinary strategy scan inputs or watch instruction. |
| `CYCLE` | Full family inputs eligible for the current five-minute entry/management slot. No watch instruction. |

Watch actions are `CALL`, `OBSERVE_ARMING`, `ADVANCE`, `NEUTRALIZE` and
`OBSERVE_QUOTE`. CALL supplies its own play/action key and locked choice. Other
actions cannot change the choice. Only timer-only ADVANCE may omit Scope evidence.
Admission remains native to the decision cycle; the producer supplies no admission,
account revision, model approval, order or fill. Native watch policy still owns
arming continuity, context/quality, source-clock advancement, original geometry,
neutral resets and cutoff decisions. A recorded watch action may contain a native
blocked/reset result; the receipt is not permission to trade.

All packets are read from owned regular mode-0600 files with the existing byte and
freshness bounds. Scope sequences start at one and advance by exactly one for each
new packet. Identical rereads are harmless. A missing sequence, reused action key,
changed same-sequence packet, foreign identity/source, future receipt, contradictory
nested/common quote, changed original watch session or invalid format fences entry
before the next awaited snapshot. The last accepted receipt is retained. Producers
must observe stored acceptance before replacing the file; this latest-file transport
is not a queue. A gap cannot be repaired by silently skipping watch instructions.

WATCH and MARKET receipts do not consume a decision slot. CYCLE packets retain the
existing one-claim-per-slot behavior and cannot queue a late decision while another
cycle is pending. Supplying an old frame in a new receipt does not freshen any source
clock. Legacy packets retain their historical serialization/default version and
reject nested Scope explicitly; Scope packets cannot enter an unenrolled owner.

## Independent protection and native actions

The runtime combines exact common and nested Scope quotes for each protective tick.
It rejects conflicting/duplicate representations before projection. No source time,
price or quote is synthesized. A nested-only update can therefore trigger the held
contract's mandatory stop/target/time protection while paid reasoning waits. Missing
feeds still fence entry and run native reconciliation/protection without invented
quotes. The original unfilled-watch entry cutoff expires the native watch even if
the feed is absent or the owner is halted. Submitted entries retain their native
order/position lifecycle instead.

An accepted packet is persisted before suspension. Its watch action is then executed
synchronously after supervision against the owner's actual current revision and
actual execution time. Original recorded/source times remain in the retained packet.
Expired delivery or blocked readiness is a recorded rejection, never a delayed retry.
A process ending between receipt and completion leaves an interrupted action; reopen
halts and marks it interrupted without applying it again. Existing runtime shutdown,
unknown model charges and signed recovery rules still apply. Fresh feeds never clear
a halt automatically.

## Paid refresh, stored evidence and export

Shared AI reads only the latest accepted, completed runtime delivery for the exact
play. Pending/interrupted/rejected watch instructions, missing Scope coverage,
expired receipts, a blocked owner or shutdown cannot supply a fresh admission.
It does not reread the feed independently and jump past an unprocessed instruction.
The existing full paid receipt and post-cost native review still require advancing
source clocks, the original terms, account revision, budgets and approval/model
deadlines. A fresh packet grants no execution authority on its own. Late, rejected
or unapplied advice retains every settled charge; missing usage stays unknown.

`execution_option_scope_runtime_inputs` retains packet hash/content, receipt time,
action identity/status, exact native step, expected revision and result. The stored
runtime report exposes bounded receipt summaries without reading the feed. Scope
native export includes this optional table only when present, verifies packet and
native action/request links and reconstructs its status summary. No feed/key filename
or credential is added to the export. Export remains bounded and rejects oversized
evidence rather than silently truncating it. Historical exports without runtime
inputs retain their structure. Cash, fills, full costs and incomplete accounting
still come from the native account, not transport status.

See [testing](OPTIONS_TESTING.md) and [latest status](SLICE2_STATUS.md) for measured
installed-wheel proof. Independent [Scope A/B/C/D comparison](OPTIONS_SCOPE_COMPARISON.md)
is already implemented for one session. Combined Scope/Swing carry, remaining
families, mixed stock/options ownership and Scope multi-session/benchmark plumbing
remain ahead of final UI and authentic PAPER testing.
