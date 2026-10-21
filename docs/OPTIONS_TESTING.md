# Offline options development checks

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

Offline fixture checks continue while plumbing is built. Finish the remaining
strategy/engine plumbing before final UI work and authentic PAPER testing.
Real market/model testing still requires authenticated samples and normalization;
the current runtime consumes normalized fixtures. This procedure does not convert
fixture success into provider, host, visual or LIVE acceptance.

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
Scope tapes remain separate work.

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
comparison regressions. Native workers run serially. Count exact distinct test IDs
on the final wheel; diagnostic passes and overlapping reruns are not extra checks.
No dependency changes, deployment, authenticated provider/model calls or LIVE
permission are part of this procedure. Native repeated-entry enrollment, combined
carry replay and remaining family/mixed ownership still precede UI and authentic
PAPER acceptance.

## Continuous Scope session comparison

Run `test_option_scope_series.py` and `test_option_scope_series_unresolved.py` using
the isolated installed-wheel procedure above.
The [series contract](OPTIONS_SCOPE_SERIES.md) covers independent continuous native
accounts, explicit settlement, original protection, paid entry/management, cumulative
loss controls, unknown costs, saved boundaries, portable tamper rejection and known-only
SPY endpoints. Include single-session Scope comparison/model/shortlist, native carry,
legacy series and tape-boundary regressions. Run native workers serially; count only
distinct completed case IDs on the final wheel. Native repeated-entry enrollment,
combined carry replay and remaining family/mixed ownership are still separate
plumbing, before UI/authentic PAPER testing.
