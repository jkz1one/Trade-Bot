# Offline options development checks

The `test_mixed_market_tape.py` and `test_mixed_replay*.py` suites verify common
original sources, exact B/C/D response contracts, four independent native accounts,
actual later fills, full known/unknown costs, management, carry/session continuity,
portable tamper rejection and the installed private CLI. Run alongside legacy
market tape, Scope/Swing replay, paid/native accounting and continuous runtime
regressions. Retain complete logs/XML, case IDs and exact wheel digests. Label
broad and final-wheel coverage separately, record the intervening application
delta, and count overlapping passing cases once. Failed diagnostics do not count.

`test_mixed_runtime.py` verifies [continuous mixed delivery](MIXED_RUNTIME.md):
real native stock fills and fast protection, slow management, exact delivered
paid refresh, retained Scope freshness rejection, immutable stock source retirement,
private input/enrollment failures, interrupted/tampered receipts, explicit settlement
and installed CLI restart. Run it with legacy runtime/Scope, mixed paid/native,
recovery/operator and shared source regressions. Preserve the noneditable wheel,
copied tests, Python `-I`, warnings-as-errors and serial native-run requirements.
Common mixed tapes and independent A/B/C/D replay/export use the separate
[MIXED_REPLAY.md](MIXED_REPLAY.md) enrollment and suites below.

`test_mixed_entry.py`, `test_mixed_position.py` and `test_mixed_paid_carry.py` verify the [paid mixed contract](MIXED_AI.md):
complete original stock/option/Scope alternatives, tool-less mock worker transport,
known/unknown charges, fresh post-cost native admission, mandatory exits,
MAINTAIN/TIGHTEN/EXIT_ALL, partial-close invalidation, restart and full-cost outcomes.
Run these alongside legacy entry/position, Scope, native mixed, loss/accounting and
runtime/replay rejection suites. Use copied tests, a noneditable installed wheel,
Python `-I`, warnings as errors and serial native processes. Keep diagnostic reruns
separate and count only distinct completed cases against the final wheel.

`test_mixed_selection.py` verifies [original stock sources and shared selection](MIXED_STOCK_SELECTION.md),
including native stock/option/Scope choices, all source families, retirement/restart,
carry binding, stored attribution and original admission deadlines. Run with the
source arithmetic, coordinator, native mixed owner and option regressions below.

`test_mixed_stock_carry.py` verifies [original stock carry](MIXED_STOCK_CARRY.md)
with native fixed children, exact calendar/catalyst/deadline binding, weekend
restart, partial closes, independent protection and full daily costs. Run it with
the mixed-owner/accounting/venue and native options regressions using the isolated
noneditable-wheel procedure below.

`test_option_scope_runtime.py` exercises the [continuous Scope runtime](OPTIONS_SCOPE_RUNTIME.md),
including explicit packet/enrollment boundaries, native watch arming, decision slots,
actual fills, independent nested-quote protection, paid fresh admission and retained
charges, interrupted/rejected actions, cutoff expiry and portable receipt validation.
Run it serially with the legacy runtime/recovery and shared Scope suites using the
installed-wheel isolation below.

The common Scope tape suites are `test_option_scope_market_tape.py`,
`test_option_scope_tape_boundaries.py` and `test_option_scope_tape_watch.py`; use the
installed-wheel isolation below. They verify the [market-input and native-watch
contract](OPTIONS_SCOPE_MARKET_TAPE.md), independent owner admissions, original
clocks/deadlines, restart and portable accounting. Run the native Scope execution/
export and legacy research replay regressions too. The separate [Scope A/B/C/D comparison](OPTIONS_SCOPE_COMPARISON.md) is covered by
`test_option_scope_shortlist.py` and `test_option_scope_comparison.py`, including
choice-only B, matched owner/configuration boundaries, independent costs and
portable all-arm reconstruction.

The deterministic Scope A tape baseline is exercised by
`test_option_scope_trading_replay.py`, including later receipt fills, partial fills,
missing executions, deadline protection, account isolation and portable accounting.
See its [contract](OPTIONS_SCOPE_TRADING_REPLAY.md) and the latest measured status.
`test_option_scope_replay_model.py` covers the separate [C/D response contract](OPTIONS_SCOPE_REPLAY_MODEL.md),
including full native request bindings, known/unknown usage, original leases,
cancellation, matched scripts and rejection without explicit execution enrollment.
`test_option_scope_model_replay.py` covers the [native C/D tape path](OPTIONS_SCOPE_MODEL_REPLAY.md),
paid fresh admission, original deadline enforcement, actual fills, management,
known/unknown charges and rejected contracts.

The settled strategy/engine plumbing is connected through explicit native fixture
contracts. Final UI work and authentic PAPER acceptance follow this plumbing.
Real market/model testing still requires authenticated samples and normalization;
the current runtime consumes normalized fixtures. This procedure does not convert
fixture success into provider, host, visual or LIVE acceptance.

## Focused research-desk presentation checks

For a template-only slice, run `test_option_dashboard.py`,
`test_option_observer.py`, `test_option_comparison_view.py` and
`test_option_scope_observer.py` against the noneditable installed wheel. Copy the
whole tests directory outside the checkout and set pytest's `pythonpath` to that
copied root and its tests directory (some fixtures import `tests.*`, others import
modules directly). Use `python -I -W error -m pytest -p anyio.pytest_plugin` with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, a fresh basetemp and retained JUnit/log files.
Run native tests serially. The latest [UI proof](DASHBOARD_REVIEW_PROOF.json) records
124 distinct final-wheel cases; an earlier collection failure counts as no tests.

Generate the eight-state drill only after native tests finish. HTML generation and
static source inspection do not meet browser acceptance. The October 23 browser
returned `ERR_CONNECTION_REFUSED` for loopback, then `ERR_BLOCKED_BY_CLIENT` for the
workspace host. Do not bypass that restriction or claim screenshots. Keep M8 open
until an allowed browser can inspect the actual desktop/mobile rendering, keyboard
interaction, long text, comparison labels and empty/stale/unknown states.

## One isolated test procedure

Use Python 3.12 on Linux, with Git and the ability to install the existing pinned
dependencies. Use a separate checkout and virtual environment under your own home
directory. Do not run this in `/opt/trade-bot`, attach deployed credentials or change
its service. The dependency locks are Linux CPython 3.12 locks; this procedure has
not established macOS/Windows acceptance. These commands create new directories;
choose different names for a second run.

```bash
git clone --single-branch --branch slice2/robinhood-read-shadow \
  https://github.com/jkz1one/Trade-Bot.git "$HOME/trade-bot-testing"
cd "$HOME/trade-bot-testing"
git checkout --detach "$(git rev-parse HEAD)"
git rev-parse HEAD > "$HOME/trade-bot-testing-commit.txt"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-build.lock
.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
.venv/bin/python -m pip install --no-deps dist/*.whl
.venv/bin/python -m pip check
```

Continue only when each command succeeds. The new virtual environment must import
the installed wheel, not an editable checkout. Retain the wheel and its digest:

```bash
TRADE_TEST_WHEEL_SHA=$(.venv/bin/python -c 'import hashlib,pathlib; p=next(pathlib.Path("dist").glob("*.whl")); print(hashlib.sha256(p.read_bytes()).hexdigest())')
printf '%s\n' "$TRADE_TEST_WHEEL_SHA" > "$HOME/trade-bot-testing-wheel.sha256"
.venv/bin/python -I scripts/options-test-kit.py \
  --wheel-sha256 "$TRADE_TEST_WHEEL_SHA" \
  --output "$HOME/trade-bot-testing-results"
```

Allow several minutes, especially for the full-session accounting replay. The
runner prints each phase as it starts and completes. It performs no installation,
broker/provider request, authentic model call, deployment or host service change.
All orders, model responses and credentials in these cases are local test fixtures.
No existing population path or credential is accepted as an argument. Fixture
subprocesses receive only basic locale/PATH values, not shell API credentials.

The output directory must be new, absolute and outside the checkout. It is private;
the CLI uses a restrictive umask. It retains copied test sources, independent
fixture state, per-phase logs/JUnit summaries, before/after installed identity,
`report.json`, `index.html` and `Trade-Bot-UI-Review.zip`. Do not reuse fixture journals as a live population.
No test outcome grants entry authority or changes the deployed experiment.

## What the command verifies

| Phase | Required evidence |
| --- | --- |
| Installed identity | Wheel digest matches the independently retained input; imported noneditable application inventory matches the checkout and remains unchanged through the run. Test-source and harness hashes are retained. Dependencies are not covered by the application digest. |
| Runtime and recovery | Native initialization/shutdown, independent supervision, stale/missing input, restart and signed operator recovery gates. |
| Shared entry | One Degen/Swing owner, governed entry/model costs, exact locks, invalidation and original first-target retirement, including paid races and restart. |
| Observer | Authenticated stored reads, decision/review/order/fill distinctions, uncertainty, escaping and read-only dashboard behavior. |
| Accounting | Independent native A/B/C/D full-session replay, entry and management charges, fees and data/host costs. Complete arithmetic remains economically INCONCLUSIVE. |
| Dashboard files | Eight clearly labeled synthetic display states, each at desktop and mobile widths, using the installed templates. Generation is not visual acceptance. |

A zero process exit alone is insufficient. Each selected phase needs completed
JUnit evidence with nonzero tests and no failures, errors or skipped tests.
Excluded legacy full-session policy variants are intentional; the v3 full replay
runs separately. A missing summary, interruption, timeout, changed input or failed
phase cannot produce `PASSED_OFFLINE_FIXTURES`. Failures retain evidence and exit 2;
no automatic retry, repair or overwrite is performed. Ctrl-C requests bounded
fixture-process cleanup. A hard kill can leave a RUNNING receipt, never a pass;
inspect remaining local processes before starting a fresh run.

## Your first hands-on review

After the command succeeds, use `Trade-Bot-UI-Review.zip` for portable visual
review: extract the entire ZIP, then open its `index.html` locally in your desktop
browser. No Python installation, login or test rerun is needed on the review
computer. The pack contains only the 24 fixed display HTML files, review index,
README and limited build/test summary with page hashes. It excludes fixture
databases, credentials, source copies and logs. Keep the original private results
directory separately for engineering diagnostics. Alternatively, open the full
run's `index.html` on the test machine. It is a local file review;
this procedure starts no HTTP server and changes no deployed route.

1. Open populated and HOLD views at both widths. Confirm proposal, review, order,
   fills and cost are easy to distinguish.
2. Open stale, halted and unknown views. Confirm missing values look unavailable,
   and that nothing implies a healthy worker, free model call or guaranteed fill.
3. Open empty/unavailable and long-text views. Check clipping, labels, layout and
   escaped text. Expand decision/protection details and navigate with Tab/Enter.
4. Save desktop/mobile screenshots and a short list of confusing or broken items.
   Record the source commit and wheel digest alongside them.

These static files support layout, disclosure and section navigation. Family
filters, pagination and API links require the authenticated observer; they are
not simulated by the files. The automated observer tests exercise those routes,
but actual authenticated browser interaction remains a separate acceptance step.
Visual/keyboard/contrast acceptance remains PENDING until reviewed. The previous
cloud-browser file-URL rejection remains unresolved; no alternate access workaround
is introduced by this command.

## Moving from fixtures to authentic PAPER evidence

The next external dependency is actual bounded market responses using the already
implemented [private read capture procedure](OPTIONS_READ_CAPTURE.md). The six-tool
schema pin has been verified; actual samples are still missing. Use only separate,
exclusively managed authorization, never the frozen deployment's active OAuth file.
Keep raw captures private and outside Git. Review exact symbols/contracts, source
clocks, entitlement, latency and completeness before implementing/accepting their
normalization into the runtime feed. Do not translate absent fields into defaults.

After that, authentic model latency/cost and continuous data must be accepted,
followed by the existing [isolated-host requirements](SOURCE_OF_TRUTH.md) for owner
lifecycle, independent alerts and off-host recovery. These are required steps, not
closed by this kit. Broader strategy work can continue independently; Scope,
overnight Swing and mixed stock/options are not enabled by this test run.

## Scope execution/loss integration

The separate [native Scope procedure](OPTIONS_SCOPE_EXECUTION.md) now covers explicit
new-cohort enrollment, CALL/PUT native entry/fills, targets and runner deadlines,
full-cost loss controls, signed reviewed resets and portable accounting. Its focused
fixtures are `test_option_scope_execution.py` and `test_option_scope_execution_replay.py`.
Use the same isolated installed-wheel discipline as above; this does not change the
deployed experiment or the final authentic-data/visual acceptance gates.

## Overnight Swing evidence

The separate [carry preflight procedure](OPTIONS_SWING_CARRY.md) includes a complete
synthetic request and create-only installed CLI. `test_option_swing_carry.py` covers
actual session/expiry/catalyst boundaries, current fee-inclusive admission, portable
verification and the unchanged native same-day exit. READY describes supplied
evidence only; it never enables overnight trading. Separate [native carry tests](OPTIONS_SWING_EXECUTION.md)
are `test_option_swing_execution.py` and `test_option_swing_carry_replay.py`. Run them
with the calendar suite and entry/management/evaluation regressions in an isolated
noneditable install. Full-period fixture cash arithmetic is not economic acceptance.

## Shared Scope selection

The [shared deterministic procedure](OPTIONS_SCOPE_ARBITRATION.md) adds
`test_option_scope_arbitration.py` to the installed Scope/shared-entry, loss,
attribution and observer checks. Its fixtures select CALL/PUT Scope, Degen and
Swing in one native owner, retain separate research accounts, exercise restart/
tamper/atomicity and reconstruct full-cost portable accounting. No new dependency
or provider call is required. Paid shared Scope AI is covered below. Continuous
Scope runtime watch ingestion and common A/B/C/D tapes remain separate work.

## Shared Scope entry AI fixtures

The separately enrolled [shared Scope entry path](OPTIONS_SCOPE_AI.md) now includes
paid selection, fresh post-cost native approval and full-cost trade attribution.
Run `test_option_scope_ai.py` with the installed wheel procedure above and the
entry reasoning/worker/coordination, shared strategy, Scope native/reapproval,
lineage/outcome, family/model loss-admission and observer regressions. Keep distinct
pytest base directories for every retained run. The worker fixtures mock provider
transport; they do not authorize an authenticated call, deployment or LIVE mode.
Run `test_option_scope_position.py` with position reasoning/worker/coordination,
Scope entry, native outcome, lineage and observer regressions for the separately
enrolled [Scope management path](OPTIONS_SCOPE_POSITION.md). Common A/B/C/D
Scope tapes use the separate [comparison contract](OPTIONS_SCOPE_COMPARISON.md).

## Common Scope observation fixtures

Run `test_option_scope_market_tape.py` against an isolated noneditable wheel with
copied tests outside the checkout, Python `-I` and warnings as errors. Include
market-tape, replay, series, shared/managed replay and native-export regressions.
The [Scope tape contract](OPTIONS_SCOPE_MARKET_TAPE.md) covers enrollment, source
clocks, completed bars, session deadlines, exact instruments, visible prefixes,
blocked-data diagnostics, old hashes and explicit unsupported-consumer rejection.
It establishes no Scope A/B/C/D performance or native replay acceptance.


## Combined native Scope/Swing carry

Run `test_option_scope_carry.py` using the isolated wheel/copy/`-I`/warnings-as-errors
procedure above. [Combined enrollment](OPTIONS_SCOPE_CARRY.md) exercises all three
entry families, both rights, full-plan schema/SDK mock transport, per-position
management, original horizons, paid rejection, full-cost export, runtime restart
and independent deadline/watch expiry. Include the existing entry/position
reasoning and worker, native Swing carry, Scope entry/management/runtime and frozen
comparison regressions. Native workers run serially. Record exact wheel digests and
distinct completed test IDs; diagnostic passes and overlapping reruns are not extra checks.
No dependency changes, deployment, authenticated provider/model calls or LIVE
permission are part of this procedure. Mixed integration now has its separate
[complete contract](MIXED_REPLAY.md); UI and authentic PAPER acceptance remain open.

## Continuous Scope session comparison

Run `test_option_scope_series.py` and `test_option_scope_series_unresolved.py` using
the isolated installed-wheel procedure above.
The [series contract](OPTIONS_SCOPE_SERIES.md) covers independent continuous native
accounts, explicit settlement, original protection, paid entry/management, cumulative
loss controls, unknown costs, saved boundaries, portable tamper rejection and known-only
SPY endpoints. Include single-session Scope comparison/model/shortlist, native carry,
legacy series and tape-boundary regressions. Run native workers serially; retain
wheel-specific completed case IDs and count overlaps once. The separate mixed
plumbing is connected; UI/authentic PAPER acceptance remains open.

## Native repeated-entry attribution

Run `test_option_native_entry_attribution.py` and
`test_option_native_entry_enrollment.py`, plus `test_option_outcome_snapshot.py`,
against an isolated noneditable wheel.
They cover separately frozen [native cost linkage](OPTIONS_NATIVE_ENTRY_ATTRIBUTION.md),
pending and unknown costs, repeated Scope admission, both directions, combined
carry, loss continuity, delivered runtime refresh, immutable reopen and tamper rejection.
Include native outcome/loss, shared Scope AI, runtime and carry compatibility.
Keep native runs serial and retain exact distinct case IDs; failed diagnostics
and overlapping focused reruns are not extra proof. Stored series exports can
also be reconstructed on the new wheel as separate artifact compatibility checks.


## Combined Scope/Swing carry series

`tests/test_option_scope_carry_series.py` exercises the separately enrolled four-arm
series with actual native fills, overnight holdings, fixed Scope same-session exits,
original deadlines, paid management, explicit gap allocations and portable export.
Missed intraday and bounded-carry closes retain original ownership/deadlines;
a later quote cannot clear an expired-order review halt or invent a protective fill.
Unknown usage, unknown gap costs, unfilled final closes and changed retained inputs
must remain incomplete or fail verification. `tests/test_option_scope_carry_replay_contract.py`
checks exact adapter/script enrollment and B's separate geometry-free carry marker.
`tests/test_option_scope_carry_series_reentry.py` verifies a subsequent paid Scope
entry preserves the prior closed loss and cumulative per-account charges/locks.
Legacy Scope, native carry, entry/usage and series behavior remain compatibility gates.
Use noneditable installed wheels, copied tests, Python `-I`, warnings as errors and
serial native execution. Count only distinct successful cases on the final wheel;
retain diagnostic failures separately. No authentic provider/model/broker call,
dependency update or deployment is part of this procedure.

## Derived Swing seed plumbing

[Original Swing targets](OPTIONS_SWING_TARGETS.md) have dedicated installed checks
in `test_option_swing_target_derivation.py` and `test_option_swing_target_replay.py`.
They cover both directions, isolated decimal arithmetic, original source/session
gates, native proof binding, runtime retirement, paid fresh rejection/unknown usage,
actual fills/protection, restart and independent carry replay/export with full costs.
Run with the same copied-test, noneditable-wheel, Python `-I`, warnings-as-errors
procedure above. Native tests remain serial. Counts and diagnostic history are in
[Slice 2 status](SLICE2_STATUS.md); repeated case IDs are counted once per final wheel.

## Native daily-base family

`test_option_swing_base.py` checks original rule geometry, actual daily/hourly calendar
coverage, invalid/missing inputs, CALL/PUT native and paid entries, actual fills,
original-stop/T1 retirement, restart and runtime delivery.
`test_option_swing_base_replay.py` checks frozen tape enrollment and four independent
carry accounts, all charges/fees/allocations and rehashed detached export tampering.
Use the same isolated installed-wheel procedure; counts and diagnostics remain in
[status](SLICE2_STATUS.md). [Family contract](OPTIONS_SWING_BASE.md).

## Daily MA pullback plumbing

`test_option_swing_ma.py` covers all three [MA variants](OPTIONS_SWING_MA.md),
independent rational-average/stop checks, source rule blockers, enrollment/clocks,
CALL/PUT native fills, paid fresh rejections, unknown costs, runtime and restart.
`test_option_swing_ma_replay.py` checks common-tape rejection and independent
A/B/C/D carry/export for each variant, including stored evidence substitution.
Run alongside base, original-target, shared-family and frozen-model-contract
regressions using the noneditable installed-wheel procedure above.

## Higher-timeframe level plumbing

`test_option_swing_levels.py` covers [higher-timeframe levels](OPTIONS_SWING_LEVELS.md),
complete actual source periods, holiday/DST/year boundaries, source rule blockers,
original targets, native CALL/PUT fills, paid rejection/unknown costs and runtime/restart.
`test_option_swing_level_replay.py` verifies independent A/B/C/D carry/export for
every level/direction variant, all charges/fees/allocations and rehashed evidence
substitution. Preserve the installed-wheel isolation and frozen-cohort regressions.


## Concurrent Swing-family batches

`test_option_swing_batch.py` covers complete original enumeration, whole-batch source
rejection, immutable roots/children, exact same-contract family selection, unique
quote reads, native CALL/PUT fills and exits, paid rejection, unknown usage, runtime,
restart and stored observer bounds. `test_option_swing_batch_replay.py` covers common
tape boundaries, prefix diagnostics, independent A/B/C/D carry and full-cost export
with rehashed original-source/child/policy/selection tampering. Preserve serial
native execution, isolated noneditable wheels, copied tests, Python `-I` and warnings
as errors. Count distinct completed cases only on the final wheel.

## Mixed cash and admission boundary

Run `test_mixed_accounting.py` and `test_mixed_admission.py` against the isolated
installed wheel with copied tests. The [mixed contract](MIXED_CASH_HISTORY.md) covers
one original balance, exact share/option fills, immutable original terms, unknown
costs, reservations and order-free admission. Its actual native Scope/Swing
projection tests preserve the original option positions. Run native option
execution/admission/fill/settlement/Scope/carry regressions alongside it. These
checks do not establish mixed native execution, runtime or four-arm replay.


## Shared mixed fixture transport

Run `test_mixed_venue.py` on the same installed wheel as the mixed accounting and
admission checks and native option/Scope/Swing regressions above. It exercises
the actual bounded fixed child, a common stock/options lock and balance, partial
fills, explicit settlement, immutable original intent, fractional fees, source
liquidity, uncertainty and legacy enrollment rejection. Four separate fixture
accounts also retain separate cash/attempts; that is not A/B/C/D strategy replay.

Compare prior/current serialized fixtures and verify source/wheel/installed bytes.
Count completed final-wheel cases once; exclude overlapping diagnostics. The
[fixture contract](MIXED_VENUE.md) grants no native mixed owner, runtime, model or
broker acceptance. See the newest status entry for the retained final receipt.


## Native mixed owner checks

`test_mixed_native_owner.py` exercises the [explicit common owner](MIXED_NATIVE_OWNER.md)
with installed fixed children: original admission binding and fresh dispatch,
stock/option cash continuity, independent protection, partial supersession,
unknown attempts, full operating costs, global/family losses, signed recovery and
original Scope/Swing terms. Run serially with common accounting/venue tests and
native option execution, loss, observer/operator/runtime and Scope/Swing regressions.
Keep final-wheel case IDs distinct from overlapping diagnostic runs. Option-only
runtime, paid adapters and comparison exports must still reject mixed enrollment.
These checks do not establish stock source selection, paid mixed contracts,
continuous mixed runtime, independent mixed replay or authentic PAPER acceptance.

## Persistent desk installed-wheel check (2026-10-23)

See [HUD proof](DASHBOARD_HUD_PROOF.json) for 129 deduplicated Python passes and
seven separate JavaScript unit cases. Run `tests/test_options_desk.cjs` with
`node --test` and `DESK_SCRIPT` set to the installed wheel's
`app/web/templates/options_desk_script.html`; it exercises presentation logic with
a small DOM fixture, not a browser. The four Python suites are dashboard,
observer, comparison view and Scope observer. Tests are copied outside the
checkout; the wheel is noneditable, Python isolated, warnings errors, plugin
autoload disabled and anyio explicit. Native tests run serially. Five obsolete
heading/navigation assertions were resolved with a focused rerun on the same
wheel. Browser and screenshot acceptance remains pending; no native or authentic
acceptance can be inferred from presentation tests.

## Explicit mixed dashboard verification

Add `test_mixed_observer.py` to the four existing observer/dashboard suites, using
the same isolated noneditable installed-wheel procedure and copied tests. Keep
native execution serial and never reinstall during a run. Coverage includes
stock partial fills, option/Scope original terms, stale/unknown accounting, costs
during incomplete reconciliation, missing current/historical coverage, native exit
latches, rail units/collisions and authenticated GET-only reads.

The [mixed desk proof](MIXED_DASHBOARD_PROOF.json) retains wheel-specific runs and
deduplicates overlaps; earlier wheel passes are not added to final-wheel totals.
Run `mixed_dashboard_examples.py` from the copied test directory after native tests
finish, with that directory on the harness import path and the application still
loaded from the installed wheel under Python `-I`. Nine offline display states
include desktop/mobile wrappers. Static rendering and JS unit checks do not close
browser acceptance. See the [deployment handoff](MIXED_DASHBOARD.md) for current
access/schema blockers and the newly authorized read-only dashboard deployment.
