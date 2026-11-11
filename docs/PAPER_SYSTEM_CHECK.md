# Offline PAPER system check

This is the developer check for delivery-plan **A1**, with the first part of
**A2**. The current continuation adds runtime correlation, stock/Scope/management
timing, in-run publication isolation and two damaged-display restart cases; see
[PAPER_TIMING_PROTECTION.md](PAPER_TIMING_PROTECTION.md).
It runs the installed collector, scanner, simulator, native subprocesses,
supervisor, publisher and authenticated dashboard reader together. The resulting
report also passes through the daily controller and independent status page.
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
SOURCE_CLOCK_CHECK and PUBLISH durations for delivered, failed and interrupted
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

**A2 stays open.** The current trace covers packet identity, native reads,
option/stock/Scope scanning, entry/management model waits, refresh, admission and
dispatch. Complete killed-before-record denominators and full-session profiling,
then repair measured bottlenecks under A3. Fixture read timings include deliberate backpressure and are not Robinhood
latency measurements. Native subprocess timings here are workspace observations,
not evidence of Tuesday's exact host timeout cause.

**A4–A6 stay open.** The recovered A1 baseline stopped trading components after
publisher failure. The continuation in PAPER_TIMING_PROTECTION.md isolates an
in-run display failure, fences entries and proves protective exits with held
positions. Startup display failures and the wider stress matrix remain open. The complete failure matrix, accelerated
calendar cases, full-duration resource-limited soak and journal-growth acceptance
remain separate work. Actual Docker/systemd, cross-UID and browser visual acceptance
remain unverified. No connected fill or entry-to-exit lifecycle is claimed.

The original Swing and Scope evidence/binding requirements remain unchanged. The
operator confirmed host deployment of d2046f6; see
[PAPER_HOST_DEPLOYMENT_20261111.json](PAPER_HOST_DEPLOYMENT_20261111.json).
This newer offline kit has not been deployed. Continue development from
[DELIVERY_PLAN.md](DELIVERY_PLAN.md); consolidate the host handoff under D.
