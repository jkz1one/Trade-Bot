# PAPER duration and capacity checkpoint

Offline synthetic measurements from November 12–14, 2026. The operator's
connected capture and scheduler installation are recorded in the separate
[November 14 host receipt](PAPER_HOST_DEPLOYMENT_20261114.json).

## Full-session scan coverage

The full 21,480-second session on `0d79a3a` evaluated 25 of 72 expected
slots (34.72%). A feed halt two hours into the run persisted after the
collector recovered. This comparison allowed zero feed recoveries. Its
original harness reported a pass on the round trip, accounting and native
checks. The native scan records fail the 99% coverage requirement. All 3,270
native snapshot reads succeeded, including p99 at 0.268 seconds. The
dashboard and report each completed 664 reads. The account closed flat,
the native database reached 179.5 MB and peak sampled process-tree RSS was
675.0 MB.

The 135-minute one-CPU repeat on `9710cce` ran beyond the original
two-hour halt and evaluated all 27 scheduled slots, also with zero allowed
recoveries. It completed one entry and one exit and its final account and
restore authority verified. All 263 dashboard/report pairs and 2,983 native
snapshot reads succeeded. Snapshot p99 was 0.209 seconds. The native
database grew to 139.6 MB and peak sampled process-tree RSS was 600.9 MB.
Its initial source was 72.8 MB and its single approved quote was 4.32 seconds
old at reservation. Full-duration acceptance on the newer build is open.
[Originals, run limits and counts](PAPER_CAPACITY_20261114_PROOF.json).

The host's daily controller allows two reviewed flat-feed recoveries.
Two healthy monitor polls previously advanced a test owner's restore
generation from 9 to 11. `77a0118` verifies the authority and checks the
owner and operator vetoes in a read transaction. A pending feed halt repeats
the checks under the writer before recovery. Tampering and a concurrent
operator halt were both rejected. The matched 335-second runs on one CPU
started at 119.6 MB with the two-recovery allowance. Before the change one
native acknowledgement failed, one of two slots was evaluated and the entry
quote was 7.62 seconds old. Afterwards both slots were evaluated, both
acknowledgements succeeded and entry age was 7.02 seconds. Each completed
one round trip and verified flat. Neither consumed a recovery.

In a further 335-second, 120 MB run on `66d8ea4`, the shared selection
after a paid reply took 0.0006 seconds, original Scope receipt validation
took 0.010 seconds, the selection and its journal write took 0.330 seconds,
and reading the executable option book took 0.008 seconds. This opening
quote was 6.72 seconds old at reservation. Both expected slots were evaluated
and the account closed flat. These component timings come from that single
opening. The original expired plan in the separate calendar fixture predates
the instrumentation.

## Month-grown dashboard and independent protection

The denser fixture completed all 22 exchange sessions, including the early
close, with 1,738 original packets on one account. The first 335-second
real-time follow-up on `5cf21d1` introduced the 65th paid attempt. Its
dashboard could no longer verify the projection within its two-second budget.
The 23rd session evaluated one of two slots. Its opening reservation used a
9.67-second-old quote, dispatch rejected the entry and no fills occurred.
Read-only inspection after shutdown verified the native restore authority
and flat accounting. The rejected display was preserved.

On that exact display, the previous verifier returned unavailable on three of
five consecutive reads. `8199a43` retained more original charge proofs within
a 32 MiB process cache, reused the portfolio reconstruction within a candidate
packet, and reused the installed plan schema. Changed source, cost or account
evidence must validate again. All five reads verified. The first took 1.44
seconds and subsequent reads took 0.18–0.23 seconds. The display deadline and
original accounting checks apply to every read.

The 22-session replay on `8199a43` then ran another 335 seconds on that
account. The worker received 31 new packets, evaluated both slots, published
its terminal dashboard and verified the account flat. There were zero
native acceptance, runtime or publication failures. The expected round trip
still failed. The original ENTER response arrived with 0.674 seconds left
on its plan. The final review recorded `ORIGINAL_PLAN_DEADLINE_EXPIRED`
and never reserved an order. The next synthetic response was HOLD.
The entering packet was already 4.65 seconds old when its cycle began.

Earlier long-run failures had different evidence. The run on `23b0669` recorded
a report source-copy deadline and a publisher timeout. All 1,109 native
snapshot calls succeeded, and the originals showed one round trip and a flat
account. `fa47f34` allows a source copy restarted by continuous commits to
finish against a consistent view for up to 0.5 seconds inside its five-second
budget. Its repeat stopped on a dashboard read after 188 seconds. The old
harness did not retain the HTTP reason. `9710cce` reproduced and repaired a
valid file replacement during a dashboard read and started retaining the exact
HTTP status and safe error code. Damaged replacements still fail verification.

At 120 MB, stock and option protection on `f99a0ff` acknowledged the stops in
2.40 and 2.54 seconds. In a repeat, the option acknowledgement took 3.95
seconds and the complete test took 5.53 seconds, missing its five-second
bound. Both assets finished flat in both trials. The instrumented run on
`98f0b0d` measured a further 1.23 seconds between each acknowledgement and
tick completion. From the delivered stop book through completion, the stock
took 3.71 seconds and the option took 4.11. History and advice were still
blocked when the subsequent executable packet filled each exit.
`5761f48` verifies an already-matching publication halt without advancing
its native restore generation every tick. A changed halt still persists and
journal tampering still stops the read. In its 120 MB run, the stock and
option received acknowledgements at 2.39 and 2.80 seconds and completed
at 3.78 and 4.21 seconds, respectively. Both filled and reconciled flat.
In a later 73 MB option case sharing a CPU with another system suite, the
acknowledgement took 4.51 seconds from the delivered breach, completion
took 5.99 seconds from the breach, and the complete case took 6.58 seconds
including setup. The exit filled and the account verified flat.
On the final timed build `66d8ea4`, the 73 MB stock and option cases
acknowledged at 1.64 and 2.22 seconds and finished 2.53 and 2.97 seconds
after the breach. Both filled on the following executable packet.

The new runtime timing on `e87ae5b` measured a 5.59-second original opening
age at 120 MB on one CPU, two evaluated slots and one completed round trip.
Starting a durable timing record took 0.46 seconds at p95 across 138 samples.
Checking a repeated receipt took 0.39 seconds at p95 and 1.68 at the maximum.
On `8199a43` the matched one- and two-CPU repetitions opened at 6.12 and
6.44 seconds, respectively, and averaged 0.730 and 0.743 busy cores. Each
covered two of two slots, closed its position and verified the account flat.
Inside paid admission, `875af6b` reduced five reads of original charge history
to one within the same transaction. Its one-CPU repeat completed a round trip
with a 6.68-second opening age and 0.739 busy cores. All 172 related checks and
550 installed system cases passed, with one unmapped-UID system skip.
[Per-run results and test counts](PAPER_CAPACITY_20261114_PROOF.json).

## November 14 comparable CPU runs

The offline worker uses synthetic quotes and model responses, a real SQLite owner,
the local native venue subprocess and the authenticated dashboard reader. These
short runs start with 119,635,968 bytes, including labeled diagnostic padding.

| Implementation and run | Logical CPUs | Approved entry source age | Native acceptance | Final fills |
| --- | ---: | ---: | --- | --- |
| `293e68e`, 90 seconds | 1 | Unmeasured | No entry reached the model | 0 entry, 0 exit |
| `293e68e`, 90 seconds | 2 | Unmeasured | No entry reached the model | 0 entry, 0 exit |
| `5f5f96c`, 90 seconds | 1 | 6.55 s | Within deadline | 1 entry, 1 exit |
| `5f5f96c`, 90 seconds | 2 | 6.30 s | Within deadline | 1 entry, 1 exit |
| `5f5f96c`, first 335 seconds | 1 | 6.55 s | Within deadline | 1 entry, 1 exit |
| `5f5f96c`, repeated 335 seconds | 1 | 6.21 s | Acknowledgement timed out, recovered during reconciliation | 1 entry, 1 exit |
| `42648c6`, two 90-second runs | 1 | 6.84 s, 6.75 s | Within both deadlines | Each 1 entry, 1 exit |
| `42648c6`, one 90-second run | 2 | 6.76 s | Within deadline | 1 entry, 1 exit |
| `42648c6`, two 335-second runs | 1 | 6.01 s, 6.40 s | Within both deadlines | Each 1 entry, 1 exit |

The five-second p95 entry-age target remains open. Both `5f5f96c` short entries
spent one second between the source and receipt. Remaining time through admission
was 5.55 and 5.30 seconds respectively. The report reads matching native
reservation and approval records. It counts an opening once, including a
subsequently failed dispatch. Missing originals and zero-entry windows remain
explicit. A completed fill after a timed-out acknowledgement still fails the
latency check. A separate one-CPU contention fixture on 119,623,680 bytes
submitted the held stock exit in 4.53 seconds, then in 4.10 seconds on `42648c6` and
both finished verified flat.

The native child previously imported the full options owner, scheduler and
repository to validate its clock. The repaired child uses the same canonical
clock and fingerprint directly. In a profiled approval with the same original
intent, CPU time between the accept and serialize markers fell from 0.286 seconds
to 0.005 seconds. Whole-child CPU time fell from 0.788 to 0.507 seconds.
During a run sharing one CPU with another fixture, the first slot expired before the
model. The next slot filled an entry 21 seconds before the short fixture
ended. No exit was observed by that cutoff and the round-trip gate failed.

On the same 120,045,568-byte source, three warm full journal digest passes fell
from 0.359–0.422 seconds to 0.147–0.161 seconds with identical authority hashes.
The earlier calendar replay first failed dashboard publication on session 17.
The repaired calendar completed all 22 sessions with eight sampled packets each
on one continuing account, including the November 27 early close. The denser reference run also passed with 1,738
packets, 100,446,208 native bytes and a 47,824,896-byte display before the
Scope display compaction. Full trading cadence over the whole month remains
unmeasured. The real-time duration measurement is tracked in the evidence file.
[Machine-readable measurements and acceptance limits](PAPER_CAPACITY_20261114_PROOF.json).

## Decision coverage and measured CPU

The nominal fixture on `0d79a3a` stopped evaluating new entries after its
two-hour mark. At 16:00:33 on the synthetic clock, the runtime recorded
`OPTION_RUNTIME_FEED_UNAVAILABLE`. The preceding cycle lasted 12.37 seconds,
the next wakeup was 12.34 seconds late, and capture 635 took 25.17 seconds.
The collector subsequently delivered fresh packets and the dashboard continued
publishing. The run had no feed recoveries available. Passing native reads,
dashboard refreshes or a single completed round trip cannot recover missed
decision slots. The delivery plan specifies 99% coverage.

On `4329383`, one and two allocated CPUs averaged 0.73 and 0.75 busy cores
respectively over the same 335-second workload. CPU accounting covers the
worker and reaped children from worker launch through drain. Both runs evaluated
both expected slots, finished flat and recorded one option entry and
one protective exit. Source ages at the opening reservation were 6.75 and
6.18 seconds. The full-duration result and the test of the earlier halt are
tracked independently.

`23b0669` records a model's original reply and its verified charge in one
fenced transaction. An injected write failure rolls back the charge, retains
the original reply through the independent interruption path and halts the
attempt. In two further matched 335-second runs the worker and its children
used 0.718 and 0.732 cores on one and two allocated CPUs. The opening quote
was 6.57 and 6.59 seconds old, respectively. Each run evaluated both
scheduled slots, completed one round trip, reconciled flat and recorded zero
native timeouts. The new coverage check counts completed evaluations with
original scans for both enrolled symbols. A full 21,480-second fixture has 72
scheduled evaluations. The five-second entry target remains open.

`54d8b93` measures each local step around the paid model. In the 120 MB
one-CPU run, persisting the request took 0.316 seconds, admitting the model
call took 0.289, and settling its reply took 0.311. The scripted model itself
took 0.002 seconds. `5cf21d1` saves the final option review and reservation
in one transaction. If reservation storage fails, the original review and
model cost survive, with zero orders. The matched 335-second runs used 0.719
and 0.739 cores, with 6.79- and 6.31-second opening ages on one and two
allocated CPUs. Each had one approved opening and a verified protective exit.

With an independently held stock or option and the dashboard, advice and
history blocked, the 120 MB one-CPU runs acknowledged stops after 2.92
and 3.64 seconds respectively. The entire tick from contention setup took
4.27 and 5.14 seconds. Both later executable packets filled the exit before
the advice and history returned. A separate 73 MB stock case sharing a CPU
with another fixture took 6.03 seconds for the whole tick. Both breaches of
the five-second test bound are retained in the proof.

The 22-session replay on one fenced owner was repeated with 1,738 packets.
Its final native and collector databases measured 100,388,864 and 106,459,136
bytes. The derived dashboard was 14,753,792 bytes, compared with 47,824,896 in
the reference replay. Each final session report and the retained account
verified. Four warm digest checks on the finished native database took
0.170–0.177 seconds and matched its stored authority hash. The exchange
schedule included the November 27 early close. Sampling omitted the intervening
market ticks. [Measured cases and limitations](PAPER_CAPACITY_20261114_PROOF.json).

## Earlier November 14 preflight

`0d79a3a` passed the 73 MB short preflight and a 335-second two-slot run
on one CPU. Both finished with one entry, one protective exit and verified
flat accounting. The full 21,480-second and month-growth gates remain open.
[Loaded run evidence](PAPER_LOADED_HANDOFF_20261114_PROOF.json).

## November 12 result

The duration harness is implemented. The capacity gate is **not passed**.
A 90-second one-CPU run with a small journal completes one entry and one
protective exit, stops flat with verified accounting, and reaps its children.
With 72,822,784 bytes of initial journal state, the same lifecycle does not
complete. The full 21,480-second worker soak was not started after this failure.

The loaded fixture adds explicitly labeled diagnostic padding through the
original fenced writer. It is neither genuine trading history nor a month-growth
acceptance test. The original authority sidecar, account limits, quote freshness,
approval lifetime, and uncertain-attempt halt are not reset or relaxed.

## Measured repairs and remaining bottleneck

Each restore-fenced write verifies the complete native logical state. Repeated
JSON serialization was expensive at this size. A bounded process-local cache now
reuses canonical row encodings only when every freshly read cell matches exactly.
Every digest still reads every row, includes the schema, sorts the same canonical
rows, and produces the original v1 SHA256. Signed floating-point zero is kept
distinct. Cache keys and values are limited to 192 MiB plus bounded mapping
overhead, with at most 32,768 entries; concurrent callers share one locked cache.
There is no authority migration, file-stat shortcut or cached verification result.

On the same saved 73 MB fixture, warm complete digests fell from approximately
0.20–0.22 seconds to 0.084–0.093 seconds, retaining the exact hash. This is a
serialization improvement, not a complete dispatch-latency repair.

The final loaded run reaches model selection and admission, but quote age is
already 8.86 seconds at admission and 9.24 seconds at dispatch. Native acceptance
takes 2.35 seconds and exceeds the remaining admission lease. The attempt is
unknown and the original uncertain-attempt halt remains. There are zero fills;
fast snapshot calls do not imply successful native acceptance. Peak sampled
aggregate RSS is 473,538,560 bytes. The next repair must address this end-to-end
journal/dispatch budget without extending the original source clocks or leases.

A separate soak failure reproduced an immediate SQLite busy error during the
initial snapshot page-count query. Both the dashboard and standalone report now
retry only SQLITE_BUSY/SQLITE_LOCKED within the original five-second copy deadline.
Other errors propagate. Tests hold and release an actual exclusive writer lock,
and separately retain the lock until the deadline. The private copy still releases
native read locks before report/projection work, and the 512 MiB source-copy
storage limit remains unchanged.

## Harness

Run the installed noneditable package with isolated Python, in a network namespace
containing only loopback, against a **new disposable output directory**:

```sh
unshare --user --map-root-user --net /path/to/venv/bin/python -I -W error \
  scripts/paper-soak.py --output /absolute/new/disposable-soak \
  --seconds 21480 --seed-mib 68
```

A short preflight uses `--seconds 90`. Add `--max-feed-recoveries 2` to
exercise the connected daily controller's allowance on a synthetic owner.
The default zero allows a feed halt to remain visible for comparison. The
worker records the configured allowance and the actual recovery count at
shutdown. The harness refuses existing output/account
paths, checkout output, symlink aliases, network interfaces, editable/source
imports, mismatched installed application bytes, and mismatched dependency pins.
It copies only tests, scripts and examples; market and model responses are labeled
synthetic. It runs the actual collector/runtime loops, native subprocesses,
publisher, report and authenticated HTTP reader. Synthetic session time advances
one-to-one with monotonic elapsed time, without accelerated feed backpressure.

The calendar regression can also run the next session at normal speed on the
same account after the denser 22-session replay. The following example starts
from the checkout with an installed test environment and uses a disposable
directory. Select one available logical CPU for `taskset`.

```sh
proof=$(mktemp -d)
TRADE_BOT_CALENDAR_DENSITY=extended TRADE_BOT_CALENDAR_PACED=1 \
TRADE_BOT_OFFLINE_PROOF="$proof" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
taskset -c 0 unshare --user --map-root-user --net /path/to/venv/bin/python -I -W error \
  -c 'import app,os,sys,pytest; sys.path.extend([os.getcwd(),os.getcwd()+"/tests"]); raise SystemExit(pytest.main(sys.argv[1:]))' \
  -q -c /dev/null -p anyio.pytest_plugin --basetemp="$proof/state" tests/test_paper_calendar_growth.py
```

`calendar-growth.json` records the calendar sessions. `calendar-paced.json`
records two decision slots, approval age, fills and accounting during the
335-second follow-up. Both stages retain their original exchange calendar,
catalog rollovers, model charges and restore authority.

The nominal worker is pinned to one available CPU. Pass `--cpus 2` for a comparison run. Aggregate descendant RSS is sampled
against 1 GiB; this is **not kernel cgroup enforcement** or proof of the measured
host profile. The runner bounds elapsed duration, records worker identity, drains
its process group on interruption, and records FAILED unless both child and
lifecycle gates pass. Snapshot timing counters explicitly exclude acceptance.
Reports, progress, logs and final summaries remain in the disposable output.

The short small-journal projection suggests several GiB of growth over 22 nominal
sessions, but linear extrapolation is not measured month history. Journal-growth,
long-lived cache behavior, full-duration protection, real Docker/systemd/cross-UID
restrictions, and connected-session acceptance all remain open.

## Evidence and preservation

Final installed tests: 521 system cases plus 311 restore/checkpoint/new-guard
cases pass, with one known cross-UID environment skip. All five integrated
scenarios pass. All 331 application files and 60 runtime dependency pins match.

See [PAPER_SOAK_CAPACITY_PROOF.json](PAPER_SOAK_CAPACITY_PROOF.json) for identities,
baseline failures, final short checks, timing/resource summaries and test outcomes.
The earlier five-scenario integration evidence remains in
[PAPER_CONTENTION_PROOF.json](PAPER_CONTENTION_PROOF.json).

No connected account, model/provider service, host deployment, schedule or limits
were changed. The November 12 evidence used host release d2046f6. The operator subsequently confirmed 39d8e48. Main, the event branch, and
PR #1's draft status/title/body are preserved.
