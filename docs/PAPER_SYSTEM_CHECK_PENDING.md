# Recovered offline system checkpoint

November 14 loaded-journal follow-up: branch implementation `0d79a3a` completed
the previously failing 73 MB simulation twice with verified flat accounting.
The separate loaded protection case met its five-second exit bound. The host
runs the earlier deployed `39d8e48`. Full-duration and connected observation
remain pending. The final installed system suite passed 524 tests. One cross-UID
reader case skipped because the test namespace lacks UID 10001. All five
integrated scenarios recorded two completed round trips and settled model usage.
[Timing and protection proof](PAPER_LOADED_HANDOFF_20261114_PROOF.json).

November 14 update: the operator deployed `ab9b090` on November 13. The next
schema compatibility implementation `aae1dff` has passed 526 installed tests.
[Host and test evidence](PAPER_SCHEMA_REVISION_20261114_PROOF.json).

November 13 continuation: schema-compatibility repair `194563c` is published and
passes 502 installed tests. It addresses the operator-observed November 12
pre-launch rejection, with no host deployment or account changes. See
[PAPER_SCHEMA_REVISION_20261112.md](PAPER_SCHEMA_REVISION_20261112.md).

Duration/capacity continuation: `39181c995844f4f1823366cbb6d10260a601ac1c`.
The new real-time harness passes its small-journal lifecycle, but its 73 MB
admission/dispatch gate still fails. Full duration and host acceptance remain
open; see [PAPER_DURATION_CAPACITY.md](PAPER_DURATION_CAPACITY.md).

Recovered and published 2026-11-11 UTC as
`29ef510748ea4fe0b18592d8483c7dcf836b15bb`. All saved source, wheel,
installation, JUnit and scenario hashes matched; 401 passing cases were retained
without repeating unchanged application tests. The case-list artifact was reduced
from 16,849,322 to 72,436 bytes, keeping a full-name SHA256 for the long parameter.
Newer deployment notes were preserved. Subsequent A2/A4 implementation is
`aad4e08`; see [PAPER_TIMING_PROTECTION.md](PAPER_TIMING_PROTECTION.md) and the
current delivery checklist. Further history/report contention and timing-coverage
work is published as `c787281` with [retained proof](PAPER_CONTENTION_PROOF.json).
This is an offline code checkpoint, not a new host deployment or connected acceptance. A1 is checked in DELIVERY_PLAN.md.

The original recovery instructions below are retained as historical evidence.

Recorded 2026-11-11 UTC. This was a recovery record, **not a deployable release**.
The implementation below was tested locally but was not published before the
workspace command service disconnected. The working branch's application code
still has the d2046f6 implementation. The operator has now confirmed deployment
of d2046f6, the dashboard reader update and reviewed schedule resume; see
[PAPER_HOST_DEPLOYMENT_20261111.json](PAPER_HOST_DEPLOYMENT_20261111.json). The local
system-check implementation described here remains unpublished.

## Verified local result

The installed-package system kit passed 279 tests in 296.85 seconds. Another 122
related regressions passed in 81.09 seconds: **401 passing cases, zero failures and
zero skips in these two groups**. The earlier cross-UID/browser acceptance gaps
are still open; these counts do not close them.

All 329 application files matched source, wheel and installation, and all 60
runtime dependency pins matched. Python was 3.12.14. Wheel SHA256:
`61659afb2920cd76a5ace2421648068a8a1b4bdadc6ff2f99d867fd478af7188`.
Application manifest SHA256:
`3de36a5dc1204a861ce04c4b864f0bec74d6bb07e7e1f371d2fb91de7d0f3015`.

| Synthetic scenario | Capture attempts | Delivered / failed | Native process calls | Entry / exit fills | Round trips |
| --- | --- | --- | --- | --- | --- |
| Normal | 35 | 35 / 0 | 35 | 2 / 2 | 2 |
| Injected capture timeout | 35 | 34 / 1 | 37 | 2 / 2 | 2 |

Both scenarios run the actual collector/runtime loops, scanner, local simulator,
native subprocesses, journals, publisher and authenticated HTTP reader. They stop
after closing SPY, restart the same fixture owner with QQQ held, and close QQQ
without another entry model request. Final accounting is verified and flat.
The actual daily controller consumes the resulting report against an exact
simulated Docker worker identity. It marks the deliberately short session FAILED;
the independent operating page displays the early stop.

Synthetic provider/model responses and paced synthetic session time remain
explicit boundaries. Process deadlines and loop waits use real monotonic time.
These runs are accelerated integration evidence, not a full-session soak,
Robinhood latency measurements, actual Docker/systemd proof, browser screenshots
or connected trade evidence. Fixture model costs are synthetic; there were no
external model/provider calls or connected account changes.

## Implementation awaiting publication

- `app/mixed/feed_timing.py` and `app/mixed/continuous_feed.py`: additive
  per-attempt monotonic phase measurements, including failed/interrupted attempts,
  stored outside market packets.
- `app/options/read_capture.py` and `app/options/read_worker.py`: bounded
  parent/child progress timing with existing process deadlines and cleanup.
- `scripts/paper-session-report.py`: p50/p95/p99/max, status denominators,
  missing/invalid/omitted measurements and observed child-stage intervals.
- `scripts/paper-system-check.py`: one-command installed-package offline kit.
- `tests/test_connected_system.py`, `tests/test_feed_timing.py` and additions
  to `tests/test_option_read_capture.py`: coordinated lifecycle/restart,
  timeout/cancellation, original packet preservation and timing regressions.
- Local `docs/PAPER_SYSTEM_CHECK.md`, `docs/PAPER_SYSTEM_CHECK_PROOF.json` and
  synthetic evidence files contain reproduction instructions and exact results.

The connected population, enrollment, balances, positions, journals, halts, eight
catalog slots, $1,000 initial capital, two-play limit, $1/day and $5 total model
budgets remain unchanged. Quote validation and source timestamps are unchanged.
LIVE remains disabled. No host build or market-hours run is requested.

## Exact recovery checkpoint

Local checkout: `/workspace/scratch/c5c1f1db535d/trade-bot`.
Local source parent: `0608547f3a702263dd63bfc4a5a8463171a3140d`.
Staged tree before packaging review:
`793a931543e67429094abfb51d05dfcc0b5589b8`.
This is a local Git tree, not a published commit. Preserve the working tree and
index. Do not reset them to this documentation-only remote update.

Installed interpreter:
`/workspace/scratch/c5c1f1db535d/test-env/bin/python`.

Evidence directories:

- `/workspace/scratch/c5c1f1db535d/proof/system-kit-1`: passing kit summary,
  original JUnit/log, both system reports and disposable native fixture journals.
- `/workspace/scratch/c5c1f1db535d/proof/system-kit-regressions.xml` and matching
  `.log`: the additional 122 passing cases.
- `/workspace/scratch/c5c1f1db535d/proof/system-loop-aptyg5d8`: candidate wheel,
  source staging, installation identity and development logs. Earlier failed
  harness revisions are not final production failures.

The kit JUnit SHA256 is
`b83d8773b9c87f79385f7f9aea6e20bb520e09f258fdb550a3aea86bffd12955`;
the related-regressions JUnit SHA256 is
`1bcf377c96576524fbc205b3c51d9282235864b06c40ee20d30481949a64286e`.
Normal system report SHA256:
`cb5c580e024945fe77002a8578b815886b03d73931c2b5b6b6baf0ea539d8dcd`.
Timeout system report SHA256:
`4ffd9eb1b76409cd8545ef92eff8cc1c7cd428a5bd7ed853d1968384d8347e30`.

Before publication, inspect evidence byte sizes. Raw JUnit is about 16.8 MB;
the derived case-list artifact copied raw parameterized case names and must be
bounded before publication. Retain short case labels plus hashes for long
parameter text. Limit packaging read concurrency; the attempted unbounded read
batch exceeded the workspace command server's pending-request capacity and the
transport disconnected. No repository ref was changed by that failed batch.
Do not publish the pre-review staged tree blindly.

When workspace access returns: preserve staged changes, bound the evidence
artifact, verify candidate identity against the saved proof, fetch the latest
remote and overlay only the intended files. Publish using the exact-head lease;
verify main/event branch preservation and PR #1 draft status. Replace only the
first PR paragraph if editing its body. Record the implementation commit in the
delivery checklist. Existing passing tests need not be repeated unless application
changes, environment changes or new concerns justify them.

## Resume the work order

A1's local integration result is demonstrated, but its checklist remains open
until the tested code is published and linked. A2 remains partial: collector/read
timing exists locally; production packet/cycle/native/scan/model/admission
correlation remains to finish. Next address measured bottlenecks and A4's
publisher-failure coupling, which still stops trading components. The complete
failure matrix and full-duration resource-profile soak remain open.

Tuesday's exact delayed native-process stage remains unresolved. Scope still
needs valid original SPX history and exact reviewed contract/session bindings;
Swing originals/target validation remain independent. Connected fills and a
complete connected lifecycle remain unverified.
