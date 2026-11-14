# PAPER duration and capacity checkpoint

Recorded 2026-11-12 UTC (November 11 New York session). This is offline,
synthetic evidence; today's connected dashboard has not been reviewed here.

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
Under deliberately shared one-CPU load, the first slot expired before the
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

A short preflight uses `--seconds 90`. The harness refuses existing output/account
paths, checkout output, symlink aliases, network interfaces, editable/source
imports, mismatched installed application bytes, and mismatched dependency pins.
It copies only tests, scripts and examples; market and model responses are labeled
synthetic. It runs the actual collector/runtime loops, native subprocesses,
publisher, report and authenticated HTTP reader. Synthetic session time advances
one-to-one with monotonic elapsed time, without accelerated feed backpressure.

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
