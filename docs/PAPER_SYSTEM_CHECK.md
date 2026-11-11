# Offline PAPER system check

This is the developer check for delivery-plan **A1**, with the first part of
**A2**. The current continuation adds runtime correlation, stock/Scope/management
timing, native commitment coverage, history/display/report isolation and two
damaged-display restart cases; see
[PAPER_TIMING_PROTECTION.md](PAPER_TIMING_PROTECTION.md).
It runs the installed collector, scanner, simulator, native subprocesses,
supervisor, publisher and authenticated dashboard reader together. The resulting
report also passes through the daily controller and independent status page.
A separate contention case holds history, advice and display work while a report
snapshot stays open and the original owner completes a protective exit.
External provider/model responses and Docker inspection are explicit fixtures.

The check creates a new `offline-system-acceptance` population in a new output
directory. It never adopts the connected account or its enrollment, opens host
credentials, schedules a worker, calls Robinhood or enables LIVE. This checkpoint
requires no operator build, new capture, account reset or market-hours test.

## Reproduce

Use Python 3.12 with the candidate wheel installed noneditably, the exact
`requirements-runtime.lock` dependencies, pytest and anyio. Source application
files must match that installation. The script refuses a source-only import or
an existing output directory. Run from the candidate checkout:

```bash
/absolute/path/to/installed-python -I -W error scripts/paper-system-check.py \
  --output /absolute/path/to/new-offline-proof
```

Host-script tests expect root-owned fixture files. Our verification used Linux
`unshare --user --map-root-user` before the command, mapping only the current user
to root in an isolated namespace. This does not reproduce Docker restrictions or
map the separate dashboard UID 10001. A system that cannot provide the required
test environment must report that gap; it must not skip it and claim host acceptance.

The runner copies tests, scripts and examples outside the source checkout, clears
the inherited environment except locale/PATH, explicitly loads the anyio pytest
plugin and runs the installed application with isolated Python and warnings as
errors. Its overall limit is thirty minutes; each integrated scenario has bounded
progress and subprocess deadlines. Timeout or interruption drains the test process
group and records failure. The accelerated scenarios run in minutes; they are not a full-session soak.

Output contains `summary.json`, `tests.log`, `tests.xml`, five synthetic system
reports and disposable fixture state. `summary.json` distinguishes test success
from unverified host/market acceptance and a wall-clock soak that has not run.
Do not mount or copy these fixture journals into any connected owner directory.

## Demonstrated behavior

Both the normal and injected-read-timeout scenarios:

1. Start a previously stopped fixture owner through the real connected supervisor.
2. Collect and normalize original fixture responses, scan and request deterministic
   model decisions through the existing production entry path.
3. Admit two plays, fill on later executable fixture quotes and protect them with
   actual local venue subprocesses and native SQLite accounting.
4. Close SPY, stop with QQQ held, reopen the same owner and close QQQ without another
   model entry request or duplicate fill.
5. Publish and authenticate the account view while the loops run. Reconcile two
   entry fills, two exit fills, two round trips and a flat final account.
6. Pass that report and an exact simulated worker identity through the daily
   controller. The intentionally short session is correctly failed rather than
   accepted as a full daily run; the status page displays the early stop.

One scenario injects a capture timeout. The original valid delivery remains
available, the failed attempt remains in the report, and the subsequent lifecycle
completes. Separate installed tests stall actual read children, retain their last
phase, enforce the existing deadline and verify cleanup. Cancellation, malformed
timing records and old journals retain explicit missing-evidence counts.

The production loops and native subprocesses run concurrently with real monotonic
deadlines. Synthetic session time advances at capture boundaries. The fixture
waits for the previous feed acceptance, protection and pending entry work before
advancing that clock. This establishes integration and persistence; it does not
stress independent collector/model cadences or establish sustained latency under
the host resource profile.

## Timing added to the production collector

An additive `attempt_timings` table binds measurements to the existing attempt
sequence. It records PREPARE, CAPTURE, PERSIST_CAPTURE, SOURCE_BINDING, NORMALIZE,
SOURCE_CLOCK_CHECK, HISTORY_PLAN, HISTORY_VALIDATE, HISTORY_BINDING and PUBLISH
durations for delivered, failed and interrupted
attempts. Read children emit bounded monotonic progress markers. The parent retains
its response/failure phase, elapsed time and matching markers, including when a
read times out. The CAPTURE measurement includes the caller's entire read wait;
the parent diagnostic itself is taken before final child cleanup.

Reports summarize the latest at most 20,000 attempts in the requested window.
They show median, p95, p99, maximum, status counts, missing/invalid measurements and
omitted records. Child-stage intervals are calculated only between observed valid
markers; the unobserved tail of a stalled stage is not invented. These diagnostics
contain fixed phase names and numbers, not provider payloads or credentials.

Old captures omit the new optional fields and remain readable. Old journals without
timings report unavailable evidence. A process killed before committing its timing
is counted as missing. A recovered attempt whose final status differs from the
recorded measurement is also counted as missing/invalid. No market packet, original
quote timestamp, admission rule, process deadline or recovery allowance changes.

## Evidence and next gates

[PAPER_SYSTEM_CHECK_PROOF.json](PAPER_SYSTEM_CHECK_PROOF.json) records the installed
identity, test counts, source hashes and two retained synthetic reports. The kit
passed 279 tests; another 122 installed regressions covered portfolio/Scope feeds,
combined sessions, Swing binding, rollover, schemas, native read imports and the
previous lifecycle path. All 329 application files matched source, wheel and
installation; all 60 runtime dependency pins matched.

The current continuation in [PAPER_CONTENTION_PROOF.json](PAPER_CONTENTION_PROOF.json)
retains 521 distinct installed passes and one known cross-UID environment skip,
three failing pre-repair cases, five completed lifecycle scenarios and the combined
one-CPU contention case. All 331 application files match source/wheel/installation.
The broader run staged the report before its independent lock repair; the complete
report, contention and timing suites passed afterward on the unchanged app wheel.
Actual abrupt-process exits separately verify missing timing denominators.

**A2 stays open for full-session profiling.** Committed native slot/model coverage,
overflow counts and scheduler-delay distributions are implemented. Work before any
commitment is explicitly unobservable. Fixture timings are workspace observations,
not Robinhood latency measurements or Tuesday's exact native timeout cause.

**A4–A6 acceptance stays open.** Startup and in-run display failure isolation and
combined history/model/display/report contention now have installed evidence. The
full failure matrix, accelerated calendar cases and full configured-duration
wall-clock soak under measured host memory limits remain. The existing >64 MiB
journal test passes; projected-month sustained growth is not established. Actual
Docker/systemd, cross-UID, browser and connected lifecycle acceptance remain
unverified. The short one-CPU test is not a full-duration soak.

The original Swing and Scope evidence/binding requirements remain unchanged. The
operator confirmed host deployment of d2046f6; see
[PAPER_HOST_DEPLOYMENT_20261111.json](PAPER_HOST_DEPLOYMENT_20261111.json).
This newer offline kit has not been deployed. Continue development from
[DELIVERY_PLAN.md](DELIVERY_PLAN.md); consolidate the host handoff under D.
