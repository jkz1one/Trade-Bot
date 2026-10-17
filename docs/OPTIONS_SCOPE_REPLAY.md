# Scope research lifecycle replay

`app.options.scope_replay.run_scope_replay(request, directory)` runs a frozen,
ordered fixture sequence through a new native PAPER owner and `ScopeWatchBook`.
It supports CALL, OBSERVE_ARMING, REVIEW_ADMISSION, ADVANCE and NEUTRALIZE. It does
not prepare or dispatch orders, call a model, poll a provider or enroll Scope in
the trading runtime. Native Scope entry remains blocked.

This provides reproducible end-to-end watch research before Scope execution is
available. Passing a research replay is neither a filled trade nor an economic
comparison. It does not add Scope to the independent A/B/C/D trading arms.

## Frozen input and owned state

`ScopeReplayRequest` contains explicit `limits`, native `execution` policy, Scope
`watch` policy, `started_at` and one through 200 typed `steps`. Money, provider,
source, capital and risk settings remain the existing required frozen contracts;
the runner supplies no new defaults or relaxed thresholds. The SPX universe and
watch/provider/quote-source bindings must match the native owner.

Each `ScopeReplayStep` carries a unique `key`, `kind`, aware `at` and `play_key`:

| Kind | Supplied evidence |
| --- | --- |
| CALL | Choice, frame and context; the action key is the new play key |
| OBSERVE_ARMING | Optional frame/context; missing evidence produces the native reset |
| REVIEW_ADMISSION | Optional frame/context/current underlying; native review records eligibility or blockers |
| ADVANCE | Optional frame; cutoff expiry can proceed without fresh data |
| NEUTRALIZE | Required completed frame; original direction-reset policy still applies |

Only CALL accepts a choice. Only admission accepts a current underlying quote.
Advance/reset accepts no context override. Extra authority, account balance,
quantity, expected revision, outcome or fill fields are rejected. Clocks must be
ordered, and no nested observation may have a receipt time after its step. Future
validity deadlines and contract expirations remain legitimate fields. The native
scanners still enforce source, age, coverage, history and semantic constraints.

The runner creates its own built-in `DurableOptionVenue`, native execution owner
and watch book. It reconciles and supervises the empty account at each virtual
clock, then obtains the actual journal revision before invoking the requested
watch action. Call limits, locked identity/history, arming holds, directional reset,
current-price reward/path checks, profile selection and fee-inclusive common
admission are therefore the production research methods, not a second simulation
of those rules. No caller-supplied receipt or authority is accepted.

## Receipts and results

The new private output directory retains:

- `inputs.json`: exact normalized request and canonical request hash.
- `options.db` and its restore authority file, plus `venue.db`: isolated native
  state. These are local fixtures, never the deployed population.
- `actions/000.json`, etc.: each step hash, expected native revision, complete
  native receipt or explicit rejected-action reason, and receipt hash.
- `report.json`: final stored observer projection, compact step/artifact index,
  native economic/model evidence, account identity and original request hash.
- `interrupted.json` after a caught run failure: explicit incomplete status.

`RECORDED` means the native method saved its receipt. A saved arming RESET, rejected
admission or management plan with missing T3 is still a recorded action. It does
not mean approved, armed, tradable or profitable. `REJECTED` means the watch method
raised its normal blocker; the runner verifies that this action did not change
the journal revision. Native reconciliation/supervision before that action has its
own records. Unexpected failures stop the run instead of becoming ordinary rejects.

`COMPLETE_RESEARCH_REPLAY` means every supplied step was processed and the final
stored observer was available. It does not establish uninterrupted real-market
coverage. Final export requires empty order, fill, model-call and native trade-
decision tables. Each account remains independent; repeating an identical request
in a separate new directory produces the same canonical report in fixture tests.
No existing run is reopened, overwritten or resumed, including an interrupted run.

The report retains native fee-inclusive admission amounts and native recorded
account/model costs without inventing trades. `economic_conclusion=NOT_EVALUATED`;
`data_cost`, `host_cost` and `net_return` remain null. Research watches are not wins,
losses, zero-cost trading returns or missing model calls recast as successful advice.
The separate A/B/C/D trading replay still includes every entry and management charge.

Hashes bind supplied files and receipts, not provider authenticity or an independent
attestation. This runner does not implement portable re-verification of an edited
export. Incomplete runs retain their available journals/receipts; absence of a valid
final report, or an interruption marker, is not a complete replay. A process kill
may leave no interruption marker. Start a separate new directory to reproduce it.

## Local invocation

The installed module accepts a private, owned, regular mode-0600 JSON request,
without following its final symlink, bounded to 16 MiB. Output must be a new
absolute path whose parent already exists:

```bash
python -I -m app.options.scope_replay \
  --request /absolute/path/scope-request.json \
  --output /absolute/path/new-scope-research-run
```

A successful run prints a compact JSON status and exits 0, even when individual
actions were normally rejected. Unavailable/malformed requests or failed runs
return 2. This is a fixture command, not a collector, service startup or deployment
instruction. The executable CALL/PUT fixture examples and native CLI acceptance
are in `tests/test_option_scope_replay.py`; no authentic-data defaults are implied.

Scope still requires complete obstruction coverage, native watch/order linkage,
filled family-loss/reset controls, four-contract T3 resolution and trading runtime/
replay acceptance. Dedicated UI design, authentic provider/calendar/host validation
and prospective economics remain separate. Main untouched, PR #1 draft, LIVE
disabled and deployed experiment frozen.
