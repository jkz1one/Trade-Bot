# Start testing the options PAPER build

The current Degen/shared-Swing implementation can be tested offline now. Completing
every planned Swing/Scope family is not a prerequisite for this first test pass.
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
`report.json` and `index.html`. Do not reuse fixture journals as a live population.
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

After the command succeeds, open `trade-bot-testing-results/index.html` locally in
your desktop browser. If the run was on a separate machine, securely copy that
private results directory to your computer first. It is a local file review;
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
