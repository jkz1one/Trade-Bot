# Shared Scope scripted response contract

`app.options.scope_replay_model` supplies a separately versioned, tool-less C/D
response fixture for the existing full shared Scope entry and position protocols.
It is **not execution enrollment by itself**. The old adapter and unbound new
contract remain rejected. [Native C/D tape replay](OPTIONS_SCOPE_MODEL_REPLAY.md)
now supplies a separate frozen enrollment, scheduler and fresh-input reader.

## Declared decisions

`ScopeReplayScript` freezes `scripted-scope-judgment-v1`, `LOCAL_FIXTURE`, arm C or D,
and at most 100 unique original five-minute opportunity keys. Entry uses `degen:`;
only D accepts `position:` management. Delay is explicit, bounded to 600 seconds,
and synthetic input/output token counts are retained. B is not accepted by this
contract; its Scope shortlist/comparison integration remains open.

`ScopeScriptedDecision` permits:

- Fixed Scope ENTER with `scope=true`, no candidate index and no replacement
  condition, trigger, invalidation, target or horizon. The supplied Scope digest
  becomes both the selected candidate and its evidence reference.
- Ordinary Degen/Swing ENTER with `scope=false`, an explicit opportunity index and
  the existing complete intraday geometry. Carry is not enrolled.
- Entry HOLD or UNKNOWN without unused candidate/geometry fields.
- D MAINTAIN, EXIT_ALL or TIGHTEN, with only TIGHTEN carrying an invalidation.
  Position UNKNOWN carries no discretionary terms.

Unknown/extra fields, mixed roles, duplicate slots, authoritative quantity fields,
C management and B scripts fail validation. `MatchedScopeScripts` requires C/D to
declare exactly the same entry slots, selections, geometry, delays and usage.
D may additionally declare management. This comparison is of declared scripts,
not reached opportunities, owners, account state or actual results. A future
comparison must separately bind cost/configuration policies and independent owners.

## Full requests and receipts

`ScopeReplayModel.run(request)` accepts only a fully revalidated `EntryRequest`
with `scope-fixed-plan-v1`, or a D `PositionRequest` with
`scope-fixed-position-v1`. Original packet/configuration identities, account and
position revisions, source evidence and deadlines remain unchanged. The adapter
receives no engine, tape, venue, credentials, fresh-input reader or cost authority.

A declared response suspends on `pending=(original_as_of + delay, future)` and
signals `started`. The native tape scheduler delivers all equal-time market receipts
before releasing that future. The adapter does not move clocks, refresh evidence,
renew a lease or deem a late response timely. Known usage survives a late release;
the native owner must settle it and enforce the original deadline independently.

Entry results use the complete `SharedScopeEntryPlan` and native entry protocol.
Position results retain the exact held entry, position revision, packet hash and
position/context evidence references. Native original-evidence validators check
successful proposals. An invalid candidate, invalid geometry, widening stop or
unusable usage returns a safe HOLD/MAINTAIN error receipt with the supplied known
synthetic usage retained. Missing scripts and explicit UNKNOWN return safe error
receipts with unknown usage and no invented zero charge. Receipts grant no approval,
order attempt or fill. They do not settle any native charge themselves.

Synthetic usage IDs bind script, request and packet, preventing identical slots in
different requests from being mislabeled as one receipt. Attempted slots cannot be
retried within that adapter instance. Durable restart/retry prevention still belongs
to the native journal. Concurrent calls are rejected without consuming the second opportunity;
cancellation clears pending state while retaining the first slot as consumed.
Malformed or unenrolled requests fail before consuming a slot. Independent adapter
instances retain independent use/pending state.

## Remaining integration

This contract is fixture evidence, not authentic model performance or billing.
Native execution now requires the separate full tape enrollment. Individual C/D
runs retain their own journal and complete costs; B and full A/B/C/D comparison
remain open. Matching declarations alone do not establish comparable accounts,
reached opportunities or economic results. The old replay adapter remains blocked.

See [Scope trading replay](OPTIONS_SCOPE_TRADING_REPLAY.md),
[shared Scope AI](OPTIONS_SCOPE_AI.md), [Scope position reasoning](OPTIONS_SCOPE_POSITION.md)
and [the latest installed proof](SLICE2_STATUS.md). Main remains unchanged, PR #1
draft, LIVE disabled and the deployed experiment frozen.
