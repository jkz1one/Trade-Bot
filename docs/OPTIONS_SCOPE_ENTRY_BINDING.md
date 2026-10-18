# Scope watch-to-entry evidence binding

New research cohorts can enroll
`ScopeWatchPolicy.entry_binding="scope-entry-binding-v1"`. This requires observed
Scope quote lifecycle and management v2, in addition to their existing arming,
contract, quality and owned-admission prerequisites. Existing cohorts omit the
field and cannot add it on reopen.

This delivers the durable selection link needed by later native Scope integration.
It does **not** enable native Scope entry, family loss/reset, runtime enrollment or
performance evaluation. `EntryLineage` for executed native trades remains limited
to its existing Degen/Swing owners. A Scope evidence label is not a trade label.

## Binding and original identity

An eligible fresh admission records a `ScopeEntryBinding` in the same transaction
as its watch state, action receipt and audit event. The binding retains:

- Population and account identity, play key, frozen watch and owner policy hashes.
- The original call receipt hash, with original choice, exact instrument, geometry,
  source inputs and original reviews checked against that call's audit event.
- The latest admission action key, request hash and exact native journal revision.
- A hash of the entire current watch record, including the owner-sourced account,
  effective limits, current quote/context evidence, arming, admission and management.
- The original admission evaluation time and validity deadline, without extension.

The record hash excludes only the binding itself. Selection cannot replace the
original stop, objectives, contract, quantity, fee reserve, account snapshot or
profile by relabeling the latest record. Management also binds the exact latest
contract scan and selected observation, admission, quantity, validity, original
geometry and tighter owner premium limit. Stored consistency hashes are not
signatures and do not prove provider authenticity or protect against a party that
can rewrite the complete journal and all independently retained evidence.

Four-contract admission still records its exact four-contract plan and missing-T3
blocker. Binding does not resize it to three or fabricate a third objective. No
setup/approval quote becomes an actual fill-bound entry reference.

## Selection without mutation

The owned book exposes:

```python
selection = book.entry_selection(
    "play-key",
    expected_revision=admission_receipt["revision"],
    now=observed_time,
)
```

The read verifies frozen enrollment, original and latest receipts, current active
watch, complete binding, exact journal revision and unexpired admission. It returns
the original proposal, fee-inclusive admission, management plan, instrument/quotes,
geometry, account, effective limits and session, plus the binding and its hash.
There is no caller-supplied quantity, balance, stop, profile or replacement quote.

Any later native journal event requires fresh admission; passing the newer revision
cannot make the old binding current. Any subsequent watch mutation removes the
old binding, including an unsuccessful admission, arming observation, quote-only
observation or terminal transition. An identical old action retry may return its
historical receipt, but cannot restore its binding to current state. A fresh valid
admission can create a new binding while retaining the same original call hash.

Restart preserves stored evidence and its original deadline. Reopening alone does
not add an event or refresh evidence; reconciliation or another journal action
makes an older selection unusable. Reads do not call a strategy scanner, governor,
provider, model or venue, and create no decision, reservation, order, fill or cost.

`authority=false` and `live_enabled=false` remain explicit. The selection lists
incomplete path proof and missing native execution enrollment; a four-contract
selection also lists its missing third objective. This is not an exhaustive live
readiness assessment. A future execution consumer must re-read this exact binding
and freshly enforce owner, market, risk, loss and dispatch gates within its native
transaction. The existing generic `prepare()` and dispatch Scope guard remains in
force even when supplied with the exact selected proposal and admission ceiling.

## Stored reads, costs and reproduction

The observer verifies the binding against its original call and current saved
receipt, then shows both validity status and whether its revision remains current.
It can display intact historical evidence after expiration or an unrelated owner
event without granting selection authority. Conflicting evidence makes the report
unavailable; it is never repaired or refreshed on read. Failed writes roll back the
binding, state, action and audit together.

Research replay includes enrolled binding records in action receipts and the stored
view. Portable verification reproduces them in independent temporary ownership,
using the independently retained request hash. Changed account/receipt bindings fail
reproduction even if an export's local receipt hash is recalculated. Old unenrolled
research cohorts retain their prior record encoding and behavior.

All amounts come from the existing common governor/accounting path. Entry fees,
reserved per-contract exit-order fees and known/unknown model costs are unchanged.
The binding itself incurs no model call. Independent accounts cannot share a
binding, even with identical play keys and market observations. Data and host costs
remain in session economic evidence; this research handoff produces no net return.

Fixture checks cover CALL/PUT quantities one through four, original identity,
expired/future evidence, subsequent events and retries, frozen enrollment, restart,
rollback, cross-account substitution, coordinated latest-record/receipt damage,
portable reproduction and the unchanged native guard. Scope order/fill lineage,
full-cost family loss/reset, complete obstruction coverage and runtime acceptance
remain open. UI and authentic provider/model/calendar/host/economic validation
remain final passes. Main untouched, PR #1 draft, LIVE disabled, deployment frozen.

See [owned admission](OPTIONS_SCOPE_OWNED_ADMISSION.md),
[management plans](OPTIONS_SCOPE_MANAGEMENT.md),
[research replay](OPTIONS_SCOPE_REPLAY.md) and [status](SLICE2_STATUS.md).
