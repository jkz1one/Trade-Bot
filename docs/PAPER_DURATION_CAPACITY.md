# PAPER duration and capacity checkpoint

Recorded 2026-11-12 UTC (November 11 New York session). This is offline,
synthetic evidence; today's connected dashboard has not been reviewed here.

## November 14 follow-up

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

This documents the duration target, not a request to run a known-failing long test.
A short preflight uses `--seconds 90`. The harness refuses existing output/account
paths, checkout output, symlink aliases, network interfaces, editable/source
imports, mismatched installed application bytes, and mismatched dependency pins.
It copies only tests, scripts and examples; market and model responses are labeled
synthetic. It runs the actual collector/runtime loops, native subprocesses,
publisher, report and authenticated HTTP reader. Synthetic session time advances
one-to-one with monotonic elapsed time, without accelerated feed backpressure.

The worker is pinned to one available CPU. Aggregate descendant RSS is sampled
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
were changed. The last confirmed host remains d2046f6. Main, the event branch, and
PR #1's draft status/title/body are preserved.
