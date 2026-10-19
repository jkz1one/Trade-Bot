# Native Scope execution and loss controls

`scope-native-v1` closes the Scope execution/loss integration for newly enrolled,
independent PAPER owners. It connects the original called watch and fresh armed
admission to a native buy, fills, target management, final exit, full-cost outcome,
family cooldown/lock and signed reviewed reset. It includes create-only fixture
replay, portable accounting reconstruction and stored observer labels.

This is offline implementation acceptance. Authentic normalized data/calendar,
prospective economics, host deployment and the final UI/visual pass remain separate.
LIVE stays disabled; existing research cohorts and the deployed experiment are frozen.

Separate [shared deterministic selection](OPTIONS_SCOPE_ARBITRATION.md) now permits
Scope/Degen/optional session-close Swing in one explicitly new owner. It retains
all native Scope terms and adds a mandatory common selection receipt; the standalone
contract below and existing cohorts retain their original behavior.

## Frozen enrollment

The owner explicitly enrolls `OptionExecutionPolicy.scope_execution="scope-native-v1"`.
It requires v2 target milestones, target stops, whole-contract partial closes,
fill-weighted entry references, tighter entry premium/time protection, and a
`NativeLossPolicy` with a `FamilyLossPolicy(family="SCOPE", ...)`. Scope loss policy
allows at most two consecutive losses and at least 1,800 seconds of cooldown;
stricter account/family limits remain authoritative.

The watch explicitly enrolls `ScopeWatchPolicy.native_execution="scope-native-v1"`.
It requires entry binding, v2 management, observed quote lifecycle, sampled arming,
contract/quality/context/admission policies and direction-reset rules. Enrollment
requires a fresh owner without order, model-call, decision, opportunity or runtime
history. Neither owner nor watch policy can be added to an existing cohort.

The generic OPEN_LONG API remains blocked for research books and for native Scope
owners without an exact Scope request. HOLD and owned/protective closes remain
available. Scope remains a deterministic specialist; this does not add a paid Scope
model, merge its account into another population or alter Degen/Swing arbitration.

## Original evidence through actual execution

After `review_admission()` returns an eligible, current receipt:

```python
prepared = book.prepare_entry(
    "play-key", expected_revision=admission_receipt["revision"], now=observed_at,
)
# Use newly observed exact option/underlying quotes for the existing async dispatcher.
status = await engine.dispatch(prepared["client_id"], quote, underlying, now=dispatch_at)
```

`prepare_entry()` is a convenience wrapper. The execution owner independently
re-reads the exact revision, original call, latest action, frozen policy, account,
contract, geometry, admission and management terms inside its write transaction.
The common governor and loss guard run again. Proposal, quote, ceiling, quantity,
profile limit, target schedule and original protection time cannot be substituted.
The source identity binds the play and admission action. A stale preparation is
retained as rejected evidence; a genuinely new admission can retry preparation.
A successfully consumed play has exactly one native entry, including after an
unfilled/canceled/rejected attempt. Identical native preparation retries return
their original result. No retry grants a second submission.

Decision, order, original watch evidence, immutable `SCOPE_ENTRY_CONSUMED` receipt
and watch transition commit atomically. SCOPE lineage derives from that receipt;
it is never inferred from a thesis, contract symbol or caller-provided family.
Dispatch rechecks the original decision/receipt, current quotes, retained coverage
freshness, exact contract/profile, price tier, remaining R, known path, current
account/risk and the original admission lifetime. It cannot extend the original
window. Reconciliation and stored attribution also verify native linkage.

The watch records `ORDER_WORKING`, `POSITION_OPEN`, `CLOSED` or `ENDED_UNFILLED`
from native orders and reconciled fills/holdings. Partial buys and canceled unfilled
remainders retain their actual position. A failed/uncertain attempted order retains
its reservation and existing reviewed-recovery requirements. There is no synthetic
cancellation, fill or automatic resubmission. Invalid stored linkage retains the
watch reservation for review; reads cannot repair it.

Called-play limits still include never-filled calls. A consumed play cannot rearm
or accept research price mutations. An opposite-direction call still requires a
separate neutral reset, cooldown, fresh completed post-reset bars and a reversal.
Closed/unfilled native plays may record that reset only after terminal evidence.
Reset never refunds a call or reopens the play. One active watch/position remains.

## Supported management and source boundary

The authority is the pinned approved SignalFlow V2 playbook at
`f9eaf2c1b5d13dca287ee7138126883065b00395`,
[`docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md).
Its unobstructed-path requirement applies to cheap **CONVEXITY** consideration.
Earlier continuation notes overstated that as a prerequisite for every Scope
profile. This implementation follows the pinned rule: responsive/balanced entries
retain all enrolled known-level, reachability and remaining-R gates; no component
claims complete obstruction coverage. Convexity stays blocked.

One-to-three-contract management v2 plans execute their exact original T1/T2
allocations and stop-only milestones. T1 protection uses complete original native
fill-weighted underlying evidence; T2 protection uses locked T1. Missing entry
reference blocks scales while independent whole-position protection remains.
Partial fills, scales and restart retain the original basis. Premium protection
uses the tighter owner/profile limit, and the exit deadline is the earliest of
original Scope protection time, owner cutoff and expiry guard.

Four-contract plans remain explicitly rejected with
`SCOPE_THIRD_TARGET_UNSPECIFIED`: the approved allocation needs T3, while locked
Scope geometry supplies only T1/T2. No fixed-R target, quantity reduction or extra
runner is substituted. This is a supported rejection boundary, not an incomplete
native order/loss connection. Broader strategy changes require their own frozen
policy and evidence.

## Full-cost losses and reviewed reset

The common native outcome engine reconstructs linked buys, partial sales, final
sales/settlements, every execution fee and all recorded entry/management charges.
An open runner, pending order, unknown charge or unallocated advice cannot become
a complete realized outcome. A never-filled play is neither a trade loss nor a win.
Reconciliation refreshes Scope's loss state. Preparation/dispatch independently
recheck it, and new call/admission reviews respect the persisted pause.

Completed losses count exactly once in both account and SCOPE family state. The
cooldown starts when complete loss evidence is recognized; delayed or unknown
charges cannot shorten it. Locks persist across restart/session changes. Other
accounts retain their own cash, fills, costs, histories and risk state.

The existing signed operator path now accepts `loss_family="SCOPE"` for
`RESET_LOSS_LOCK`. It requires the exact current revision, an actual family lock,
expired cooldown, fresh flat reconciled evidence, complete known costs and reviewed
outcomes. Its audit retains actor, reason, time, session, previous count/state and
command identity. It clears only Scope's operational streak/lock. Account locks,
daily losses, P&L, charges, fills and any separate halt remain. Existing account
recovery requires its own explicit reviewed command; a Scope reset cannot bypass it.

## Fixture replay and portable accounting

`ScopeExecutionReplay` combines existing `ScopeReplayStep` watch actions with
`ScopeNativeStep` actions: ENTER (fresh review/prepare/dispatch), FILL, CLOSE,
PROTECT, TERMINAL, SETTLEMENT and signed fixture RESET_LOSS. Inputs are ordered,
bounded, frozen and cannot contain future received evidence. It creates a new
isolated PAPER owner, uses the built-in durable venue and writes `inputs.json`,
`report.json` and `native.json`. Existing output paths are refused. Interruption
creates `interrupted.json`, never a successful result. TERMINAL supplies an observed
fixture order outcome; it is not a cancellation API. FILL/TERMINAL can reference
the key of an earlier ENTER/CLOSE/PROTECT action, including protective orders whose
native client/source IDs are generated during execution.

```bash
python -I -m app.options.scope_execution_replay /absolute/request.json /absolute/new-run
```

The request schema is exported by
`ScopeExecutionReplay.model_json_schema()`. A complete CALL/PUT example is exercised
in `tests/test_option_scope_execution_replay.py::request`. The original research
replay remains order-free and rejects native execution enrollment.

`export_scope_execution(journal, now=..., data_cost=..., host_cost=...)` takes one
read-only snapshot. The report includes original/native receipts, order/fill
attribution, reconstructed outcomes, retained risk/reset evidence and full account
costs. Data/host costs default to unknown. Open holdings, unresolved orders or unknown
costs make `net_after_all_costs=None`; no unrealized price mark is called realized net.

Retain its `export_hash` independently. Then
`verify_scope_execution_export(value, expected_export_hash)` reconstructs the fixed
native evidence schema in an in-memory database and rechecks original bindings,
fill/settlement accounting, full costs, risk history and report values. It accepts
no SQL, restore authority, owner path or network transport from the export. This
verifies recorded native accounting, not authentic provider data, historical operator
signatures, strategy profitability or replay of every historical risk decision.

The observer remains read-only and now distinguishes native PAPER plays from
research watches, showing the exact native entry link. This semantic correction
is not the final visual acceptance pass.
