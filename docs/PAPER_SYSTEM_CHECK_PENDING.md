# Recovered offline system checkpoint

November 28: duration failed at its first entry; return to repeated short qualification.

The new `9c8161e` duration attempt exited during its first minute with native
acceptance UNKNOWN. Only 1.309 seconds remained at spawn; response read timed out.
Peak memory was 652.48 MiB with zero limit/OOM events. This run reached no endurance
qualification. Preserve the earlier one-round-trip short pass, but it did not
establish reliable opening margin. [Supplied failure](PAPER_DURATION_ENTRY_FAILURE_20261128.json).

The candidate verifies all committed rows at the start of every fenced write,
then reuses verified timing rows inside the same SQLite write lock while rereading
all changed ids and all other tables. The canonical v1 hash, atomic authority,
rollback checks, original deadlines, limits and protection remain unchanged.
Local alternating measurements reduce large-history transaction medians about
14–17%. [Mechanism, primary-source research and limits](PAPER_RESTORE_TRANSACTION_20261128.md).

Next host qualification is `entry-repeat`: three fresh 335-second lifecycles in
one pinned image, stopping on the first failed lifecycle or inadequate acceptance
margin. Require terminal `ENTRY_SERIES_PASSED`, no limit/OOM events, flat accounting
and at least twice the measured transport duration remaining at each spawn.
This is a test threshold, not a relaxed runtime deadline. One pass no longer
advances to duration. [Host procedure](PAPER_NEXT_SESSION.md).

Preserve installed `2d538b7`, connected account, limits, timer, review hold and old
evidence. No deploy/resume, capacity change or full-duration retry. Long-lived
repeated entries, sustained memory/publication and provider CONNECT health remain
open; a full connected PAPER day remains unverified.

### Previous native startup checkpoint

November 27: startup repair verified locally; short host entry gate remains required.

The host follow-up records `UNKNOWN` and `FixtureProcessTimeout`, with
`IMPORTS` as the last observed child stage. Its original five-second plan deadline
bound acceptance before the ten-second quote-age ceiling. At spawn only 1.228
seconds remained. Missing later telemetry is not proof that no order was accepted;
unknown-attempt recovery remains unchanged.
[Host evidence](PAPER_ENTRY_HOST_20261127.json).

The acceptance child now imports its frozen protocol, base contract and cost policy
without loading the parent transport, legacy fixture/domain models or economics
queries. Eight moved definitions retain identical syntax trees, old import-path
aliases and four wire-schema fingerprints. No request validation, parent ownership,
venue checks, cash/position rules, journal checks, original deadlines or resource
limits were removed or widened.

450 distinct installed tests pass, including real-child dependency denial,
expired leases, lost acknowledgments, recovery and loaded stock/option protection.
The 112-MiB-seeded 90-second lifecycle passed with one entry, one exit, verified flat
accounting and 50 successful snapshot reads. Both old and new builds passed 16
fresh-child acceptance trials each on one pinned CPU; median response time fell
from 265 ms to 226 ms (14.5%). This is a local overhead reduction, not a reproduced
host repair. Local cgroup memory enforcement was unavailable.
[Verification and limits](PAPER_NATIVE_STARTUP_20261127_PROOF.json).

Next: the isolated 335-second host `entry` profile on this candidate, retaining
one CPU, 1 GiB, no network/credentials and all original deadlines. Require the
terminal `ENTRY_GATE_PASSED` receipt before advancing. Preserve installed `2d538b7`,
the connected account, timer, review hold and old evidence. No connected deployment,
resume, resource increase or full-duration launch. Sustained memory/publication,
restore-scan latency, provider CONNECT health and a full PAPER day remain open.

### Previous report-storage checkpoint

November 27: static host publication passed; short lifecycle qualification is next.

The operator's 8:37 p.m. New York replay used the old `d2e78bf` image and
unchanged one-CPU/1-GiB limits. Its stopped 208.7-MiB source published a 5.16-MiB
display in 0.964 seconds, with original source hashes/mtimes unchanged. The
64-MiB display cap was not reached. This static pass does not reproduce or clear
the original concurrent failure. [Host result](PAPER_PUBLISHER_HOST_20261127.json).

The offline test was placing each full report copy in its container's RAM-backed
`/tmp`. A synthetic copy matching the failed run's recorded database size
allocated 208.7 MiB there. The soak now explicitly places those disposable copies
under its disk-backed evidence directory, retaining identical report contents,
snapshot consistency, limits and cleanup. This removes that tmpfs allocation;
it does not prove an equal cgroup peak reduction or identify the old failure cause.
No global temporary-directory setting or connected report default changes.

Known SQLite error codes now survive application, session-report and retained-soak
diagnostics. Messages, SQL text, private paths and arbitrary attributes remain
excluded. Entry/protection behavior is unchanged from the verified `9bad805`
repair. [Changes, tests and limits](PAPER_REPORT_STORAGE_20261127_PROOF.json).

Next host action: the detached 335-second `entry` profile, with early failure on
its required fixture entry rejection. The short local lifecycle and loaded
protection checks pass, but no host lifecycle pass is implied. Preserve installed
`2d538b7`, connected account, limits, timer, review hold and all older evidence.
Repeated active lifecycles, stable duration memory/publication and provider
CONNECT health remain open. No deploy, resume, resize or long-soak launch.

### Earlier publisher investigation

November 27: isolate the saved publisher failure with one short replay.

The operator's 8:09 p.m. New York output locates the old publisher failure at
`dashboard_snapshot.py:235`, the display-table `INSERT SELECT`, with
`OperationalError`. The old event did not retain SQLite's error code or the table.
Its last saved report precedes that incident: 58 complete decisions, 1,617 delivered
collections and fresh feed/heartbeat at its cutoff. The original missed entry and
later publisher failure still fail qualification.

Two local reproductions reach that exact line: the unchanged 64-MiB display cap
returns `SQLITE_FULL`; a forced progress-handler cancellation returns
`SQLITE_INTERRUPT`. This establishes ambiguity, not either cause on the server.
The recorded 1-GiB lifetime peak and 603,798 max events remain pressure evidence,
not failure-phase attribution. [Supplied evidence](PAPER_SOAK_20261127_HOST.json).

`scripts/paper-publisher-replay.py` runs one publication using the stopped offline
test's original image and source mounted read-only. It retains the SQLite code,
stage, table and phase times in new evidence. No build, connected-owner access,
trading runtime, timer operation, halt clearing or deployment is involved. The
one-CPU/1-GiB/no-swap/PID128 constraints, five-second publication deadline and
64-MiB display cap are unchanged. A 45-second outer deadline stops only the new
diagnostic container. The old failed worker and its files are preserved.

175 focused checks pass, with one existing cross-UID skip. A local stopped
123-MiB source published a 2.43-MiB display in 0.413 seconds with source hashes and
mtimes unchanged. Application bytes did not change. Neither that control nor a
later host static pass proves the original load-related cause or qualifies a
trading day. [Verification and limits](PAPER_PUBLISHER_REPLAY_20261127_PROOF.json).

Next action: one short publisher replay against the retained failed fixture,
then review its complete result. Preserve installed `2d538b7`, connected account,
limits, timer and review hold. The locally verified entry repair's 335-second
host gate, repeated active lifecycles, sustained memory and provider CONNECT
checks remain open. Do not repeat the old full-duration launch.

### Earlier terminal evidence checkpoint

November 27: the retained host duration failed; inspect its durable cause.

The operator supplied the old `d2e78bf` soak's terminal receipt at 7:15 p.m.
New York time. It exited at 6:54 p.m. after about 4h 49m with
`CONNECTED_COMPONENT_STOPPED:PUBLISHER`, exit 1, no restart and no OOM kill.
All 4,529 native snapshot reads succeeded. That does not override the earlier
original-quote entry rejection or the later publisher failure.

Peak cgroup memory reached the full 1-GiB limit; `memory.events.max` was 603,798,
with zero `oom` and `oom_kill` events. The low final current-memory value was
observed after exit. This establishes limit pressure, not the cause of the
publisher failure. Its concrete exception is still missing.
[Original supplied terminal evidence](PAPER_SOAK_20261127_HOST.json).

The offline harness now preserves the first observation error and any component
failure encountered while draining. The standalone checker can read the latest
publication incident from the stopped disposable journal when its final report
was never saved. It verifies the retained container identity/isolation and rejects
live, foreign, symlinked or WAL/sidecar-bearing journals; reads are bounded and
immutable, with no account verification or execution authority.

174 distinct focused checks pass. An injected publisher timeout retained both
the first dashboard failure and underlying component cause, with children reaped;
its last progress sample was 35.22 seconds. This is evidence-path verification,
not a reproduction or repair of the unknown host publisher cause. Application
bytes remain those of the previously verified entry repair.
[Verification and limits](PAPER_SOAK_TERMINAL_20261127_PROOF.json).

Next operator action: inspect the stopped test with the pinned standalone reader,
without building or switching the installed checkout. Review the concrete
publisher cause before another host trial. Preserve installed `2d538b7`, account,
limits, timer, review hold and failed evidence. No deployment, resume or resize.

### Earlier local entry repair checkpoint

November 27: the combined entry transaction has local verification.

The local quick gate passed in 130.77 seconds: the 112-MiB stock and option
protection cases took 2.72 and 2.67 seconds against the unchanged five-second
target, followed by an entry/exit round trip and verified flat accounting.
The installed suite and supplemental boundary checks cover all 1,165
cases in the expanded gate: 1,164 distinct passes and 1 existing reader-UID
environment skip. The 335-second loaded check finished in
335.95 seconds with both scheduled evaluations, one round trip, no native
snapshot failure, verified flat accounting and reaped children.

In sequential local 90-second comparisons with the same 112-MiB synthetic
history, original quote age at reservation fell from 4.029 to 3.392 seconds.
Quote source through completed entry cycle fell from 6.416 to 5.764 seconds;
this includes acknowledged native entry and durable owner completion and is an
upper bound for native acceptance, not the exact child commit timestamp.
Reply-to-review time fell from 0.387 to 0.166 seconds. These are single samples,
not a percentile or Docker/server qualification. The eligible path removes one
fenced transaction and two full-journal digests.

[Exact comparison, failed intermediate check and limits](PAPER_ENTRY_TRANSACTION_20261127_PROOF.json).

This is a measured application improvement, not closure of the host incident.
It does not prove that the host's previously observed 0.335-second remaining lease
can reach native acceptance. Same-server short qualification, repeated active
lifecycles, stable full-duration memory, provider CONNECT health and connected
PAPER operation remain open. Preserve installed `2d538b7`, the connected account,
limits, timer, review hold and retained test; no deploy, resume or resize follows
from local results.

### Earlier short qualification checkpoint

November 27 continuation: the short deployment-profile test and failure bundle
are implemented, with a deterministic reproduction of the reported deadline
margins. `--profile entry` retains the original constraints and requires a full
335-second lifecycle/decision window; `ENTRY_GATE_PASSED` is distinct from full
duration. The bundle includes failed pre-reservation clocks, cycle timing,
digest cost and CPU/I/O/memory observations with explicit coverage limits.
[Exact verification](PAPER_SHORT_HOST_GATE_20261127_PROOF.json).

Application bytes are unchanged. The measured entry latency repair is still the
next application task. No new host command or full-duration trial follows from
this harness checkpoint; preserve installed state and the existing test.

Current priority: [engineering review](PAPER_ENGINEERING_REVIEW_20261127.md).
The original ten-second quote deadline is confirmed; the account's twenty-second
limit was not limiting. At 66 minutes the host test still had no restart/OOM but
its cgroup peak was 949 MiB of 1 GiB. Retain the lifecycle failure and keep full
resource qualification open. No new application patch was made for this review.
The next implementation must address the complete source-to-native-entry path
and prove it in a short test under the deployment constraints before a long run.

November 27: the operator's running `d2e78bf` soak has failed its lifecycle gate.
The one-shot fixture ENTER received a timely model reply but expired before
reservation (`ORIGINAL_PLAN_DEADLINE_EXPIRED`). Its later model calls return HOLD;
this run cannot complete the required round trip. Fresh synthetic feed, completed
decisions and resource measurements remain useful but do not override failure.
The saved phase trace shows settlement using 0.935 seconds after a reply with
only 0.336 seconds left. Protection wait was 0.000120 seconds. Review was 0.623
seconds past the original deadline; the entry path remains unrepaired.
[Host observations](PAPER_SOAK_20261127_HOST.json).

The harness now fails on a completed rejection of its exact required fixture
entry, preserving the original decision and failure evidence. It permits pending
entries, unrelated HOLDs and zero fills without a known terminal fixture failure.
Application bytes, deadlines, account authority and limits are unchanged.

The 100 focused checks pass. An injected original-deadline rejection stops in
37.16 seconds and preserves its settled model charge and failed receipt; the
112-MiB short control still completes a round trip with verified flat accounting.
[Guard verification](PAPER_ENTRY_GATE_20261127_PROOF.json).

The local 22-session sampled replay and 335-second paced follow-up completed:
1,738 prior packets, 64 prior model calls, both due paced decisions evaluated,
one simulated round trip, no runtime/publication failure and verified flat
accounting. This local result is not full-cadence month or Docker qualification
and does not override the host rejection. [Proof](PAPER_CALENDAR_20261127_PROOF.json).

Preserve the installed connected owner and review hold. Repair and briefly
reproduce the first entry delay before a new host run; do not redeploy or resume.
The read-only interim reporting patch's earlier 91 checks remain documented in
[PAPER_PROGRESS_20261127_PROOF.json].

November 24 current checkpoint: the blocking local protection and lifecycle gates pass.

The new fast gate passed in 2m 38s: 112-MiB stock and option protection completed in 4.35 and 4.38 seconds against the unchanged five-second target, followed by a 90-second simulated round trip and verified flat accounting. The matching installed suite passed 1,065 tests with one unmapped-reader-UID skip.

The longer loaded check also passed after 336.44 seconds: 153 native snapshots, zero native snapshot failures, both scheduled decision slots evaluated, one entry/exit round trip and verified flat accounting. Peak sampled process-tree RSS was 461,508,608 bytes; cgroup counters remain unavailable locally. [Exact verification, failed intermediate checks and limits](PAPER_ITERATION_20261124_PROOF.json).

Run `scripts/paper-system-check.py --quick` after each application edit. Only a passing quick gate proceeds to broad regressions, longer loaded coverage and resource qualification. The first unchanged application failure was reported in 32.58 seconds; the later native acceptance failure ended the entire quick gate in 105.35 seconds. Both failed receipts remain in the proof. A favorable protection sample does not override a later failure.

The local launchers now reject a PID namespace whose `/proc` view does not match. Use `unshare --mount-proc` with the documented developer command. Earlier local aggregate process-tree RSS did not record this coherence and is not accepted as resource qualification; direct self-RSS cache benchmarks and the operator-reported Docker OOM remain separate evidence.

These are local synthetic results. The earlier host OOM remains a failed duration result; full Docker duration under one CPU/1 GiB, sustained month growth, real-provider CONNECT health and connected R4 remain open. The installed `2d538b7` owner and existing `SESSION_STOPPED_REVIEW_REQUIRED` hold remain unchanged. These local results alone do not qualify deployment or resume.

### Earlier memory-repair qualification

November 24 host follow-up: the detached 20923e2 soak was OOM-killed after
37m 19s, with zero restarts. The duration gate FAILED. Its 445 successful native
snapshots are partial evidence, not final lifecycle/accounting acceptance.
The replacement cache avoids retaining obsolete versions of each changing batch.
The reproducible 300-update comparison ended at 528 MiB with the preceding policy
and 368 MiB with the repair, with correct canonical hashes in both cases.
The matching installed suite passed 976 tests with one unmapped-reader-UID skip.
The 112-MiB protection gate FAILED: stock 6.13 seconds, option 7.95 seconds against
the unchanged five-second whole-case target. Both exits completed with verified
flat accounting. The preceding cache policy also failed on this machine. Keep
the installed owner and review hold; another host soak is not yet recommended.
[Exact current proof](PAPER_MEMORY_20261124_PROOF.json).

The final 335-second loaded fixture also FAILED: 101 native snapshots completed
without failure (maximum 0.303 seconds), but native acceptance exhausted its
remaining 1.240-second transport budget. No round trip completed, and only one
of two scheduled decision slots was measured. Sampled process-tree peak was
489,492,480 bytes; cgroup counters are unavailable locally. Reduced memory and
successful snapshot reads do not override the failed lifecycle gate.

### Prior short-lifecycle and detached-runner checkpoints

November 23 follow-up: the 112-MiB varied-history lifecycle now passes on one CPU.
It completed one simulated round trip, evaluated both due slots, ended verified
flat and recorded 152 native snapshot calls without a timeout. Both extended
protection cases now meet five seconds (stock 3.89, option 4.37 seconds), while
history, model advice and a failing display remain independent.

The final matching installed package contains 336 application files and all 60
runtime pins. Its suite passed 925 tests, with one reader-UID mapping skip. The
80 restore/queue/harness checks, 94 admission/execution checks and nine extended
protection cases also passed; these groups overlap and are not an additive total.
The workspace 21,480-second attempt is incomplete: its last progress is 599.77
seconds, its process is absent and there is no final report. Original raw RUNNING
receipts are preserved, not promoted to completion. No host deployment or resume
is proposed. [Exact proof and open gates](PAPER_OWNER_LATENCY_20261123_PROOF.json).

November 24 adds a detached Docker harness for that residual gate, using the same
application and a new synthetic account with no credentials/network. Tests cover
guarded startup, retained failures, resource and identity checks, and refusal to
report success from stale or incomplete evidence. Docker is unavailable in this
workspace. The operator later confirmed its image build and launch, followed by
the OOM failure recorded above. The earlier 925-test installed result belongs to
the preceding application checkpoint, not a successful Docker duration test. [Runner results and limitations](PAPER_SOAK_HOST_20261124_PROOF.json).

### Earlier November 23 cache-only checkpoint

November 23 varied-history checkpoint: the requested 637 host timing records locate
expensive local writes. The bounded encoding-cache candidate reduces synthetic
journal-update CPU time by about 48%, preserves canonical v1 hashes and resets its
cache across independent restore authorities. Capacity fixtures now use distinct
records. The old repeated-payload fixture concealed encoding-cache churn.

The final installed suite passed 904 checks with one unmapped-reader-UID skip.
Both varied 68-MiB held-position exits met five seconds (3.67 and 3.91 seconds).
The stronger 112-MiB fixture rejects the candidate: intended entry plans expire
or contract inventory ages out before admission. The separate extended protection
cases also miss the five-second whole-case target. These are failed offline gates,
not a deployment recommendation. Keep the existing host release and review hold.
[Complete measurements and regression results](PAPER_RESTORE_SCAN_20261123_PROOF.json).


November 23 host acceptance failed on the installed `2d538b7`: zero decisions,
341 failed collections and a native snapshot timeout. The published test counts
below remain offline evidence. They do not establish a healthy connected day.
The diagnostic patch exposes the omitted saved failure/timing fields and labels
SDK loading, OAuth setup and MCP initialization separately; runtime behavior and
deadlines are unchanged. A native-process regression reproduces SPAWN/NOT_OBSERVED
with a successfully completed child while the parent loop is delayed, establishing
why that signature alone cannot identify the host root cause.
All 268 focused checks passed in the root-mapped, network-isolated test environment;
the matching noneditable application was rebuilt for real child-process tests.
This is diagnostic verification, not a full installed-system run or runtime repair.
[Current incident, verification and remaining gate](PAPER_SESSION_20261123_PROOF.json).

November 20 follow-up candidate `2d538b7f32afa7b6df09e7af0d3534e9e27f71e5`
reproduces the two empty exact-strike probes and resolves them using complete,
bounded provider strike listings. Native contracts are captured again at the
selected listed strike; the final consumer artifact is an unmodified original
capture. Tests reject incomplete/repeated pagination, incorrect chain/expiration,
wrong option right, untradable rows, duplicate/oversized pages and a subsequently
unavailable selected strike before quoting. Local errors now retain a fixed reason
through host and controller sanitizers. The installed suite explicitly includes
session-capture, contract-catalog and observed-simulation consumers.
The final installed run passed 897 tests in 400.05 seconds; one cross-UID
reader case remains skipped because UID 10001 is not mapped in this environment.
[Current verification and confirmed host state](PAPER_CATALOG_CAPTURE_20261120_PROOF.json).
The operator subsequently supplied `RELEASE_INSTALLED`, stage `reader`, for this
exact candidate, with no reported failure and receipt directory
`/root/trade-bot-release-zk5617xi`. Guarded host qualification and installation
are confirmed; connected acceptance remains open. This receipt update changes
only documentation and evidence; the installed test result above is unchanged.

November 20 candidate `9a140b8d8628c27f9304cd6331bbcee07af7074e` implements R1-R2
and the offline portion of R3. The installed suite now explicitly includes
consumer-schema, diagnostic and release-workflow cases. Its manifest contains
334 application files and all 60 pinned runtime packages. The final installed
run passed 799 tests in 402.17 seconds; one cross-UID case requires reader UID
10001 and remains skipped in this environment. Results and exact artifact hashes are recorded in
[PAPER_RELEASE_20261120_PROOF.json](PAPER_RELEASE_20261120_PROOF.json).
That candidate failed real-host qualification; the corrected follow-up is recorded
above. R4 remains unverified. The current read-only operator check is in
[PAPER_NEXT_SESSION.md](PAPER_NEXT_SESSION.md); older command blocks are history.

The first integrated pass exposed an invalid clock in the new dashboard test:
it attempted to read two seconds before the fixture snapshot was published.
The test now observes the published fixture three seconds after its base time,
as the existing authenticated-reader tests do. No freshness limit was changed.
The final candidate also covers original failure reporting from stderr and
immutable display-receipt reads without claiming accounting was reverified.

November 20. `c03b628` deployment, reader update, stopped-account publication
and explicit schedule resume are host-confirmed. Today failed preparation three
times on the optional `notice` schema addition, with zero market reads and no
worker. Prior offline passes remain narrow evidence, not connected acceptance.
The active process work order is [R1-R4](DELIVERY_PLAN.md#november-20-work-order-repair-the-delivery-process-first).
No runtime change or new suite run was made for that earlier process audit.
[Incident and audit](PAPER_PROCESS_REVIEW_20261120.json).

November 18. The host completed almost six hours of process uptime but only two
strategy cycles. A publication timeout latched entries off; 653 capture attempts
failed. The repair removes halt alternation and dashboard rendering from the
accounting publication check. Three regressions failed before the repair and pass
after it. Three damaged-account cases still reject publication. Published repair `c03b628` passes installed system
verification: 623 passed, one unmapped reader-UID skip, no provider or model
calls. Provider connection failures remain unresolved; subsequent host deployment
and stopped-account publication are recorded above. Sustained operation remains open.
[Evidence and remaining limits](PAPER_SESSION_REPAIR_20261118_PROOF.json).

November 17. `220da15` replaces metadata-version admission with a reviewed
wire-contract fingerprint that excludes descriptions. The supplied November 17
metadata reconstructs to its exact observed digest. It and an unseen synthetic
description revision reproduce 30 failures against the prior implementation.
All 402 focused checks pass with the repair, including mappings, capture,
collector restart, host diagnostics and malformed or changed data contracts.
The installed application also passed 620 system checks. One cross-UID case
requires mapped reader UID 10001. All eight deployment shell rehearsals passed,
including a failed capture, a dirty checkout and installation rollback. The
deployment block runs as a standalone subshell so Bash stops on failed checks.
At 11:44 p.m. New York time on November 17, the operator captured Wednesday's
catalog on `220da15`: eight provider calls, four candidates and no worker start.
Both `daily-info` checks passed. Installation confirmed the same release and
image for the scheduler, the updated dashboard reader and an active, unpaused
timer. The unchanged owner matches the saved November 10 timeout review.
Wednesday's preparation and worker launch, full-session operation and the
cause of the earlier intermittent `daily-info` errors remain unverified.
[Incident and verification](PAPER_SCHEMA_CONTRACT_20261117_PROOF.json).

The installed `fd7ff01` application passed 613 integrated checks. One
cross-UID test requires a mapped reader UID 10001. Thirteen overlapping
recovery and host cases passed. A separate replay on the deployed
`39d8e48` code reproduced the deadline followed by two refusals. The new
publisher recovered that same display, and the original release accepted
the published receipt. On one CPU a separate 135.9 MB synthetic source
with two held plays recovered in 0.132 seconds after an injected timeout.
The original account files matched byte for byte in both fixtures. At
10:30 p.m. New York time on November 16, the operator also recovered the
connected display from a separate `fd7ff01` checkout. The published receipt
reports owner revision 5453, feed sequence 1432, runtime generation 15,
zero held plays and an unmodified source. The subsequent host receipts
confirmed that the daily scheduler and reader then ran `fd7ff01` and the
timer was active. All 54 daily controller tests passed. A separate offline
check with the reported owner state carried Monday's three review attempts
forward as history and gave Tuesday its first attempt. Changing the owner
revision, feed sequence or runtime generation blocked preparation in each
case. The subsequent Tuesday host run failed in capture before worker launch.
[Recovery evidence](PAPER_SNAPSHOT_RECOVERY_20261116.json).

November 16 UTC. The installed `365791d` application passed 604 system
checks. The single skip requires a mapped reader UID 10001. Another
188 related cases passed, including the seven isolated native handoff
checks. The 48 host tests also passed after the test-only change in
`976b303` checked each read-only mount against its approved source and
destination. These test groups overlap.

The padded account completed its entry and protective exit. On the
month-grown account, two of three runs completed that round trip and
evaluated both scheduled slots. The third recorded an uncertain attempt
with no fills and one missed slot. All three verified their accounting and
finished with zero held positions. The stock and option protective exits
under separate contention both filled while history and advice were
blocked. The five-second opening goal and the full 358-minute run remain
open. At the time of those checks the host ran `39d8e48`.
[Results, baselines and timing traces](PAPER_ENTRY_ACK_20261116_PROOF.json).

November 16 UTC. The installed `2646944` application passed 590 system
checks with one skip for unmapped reader UID 10001. All 15 copy deadline
and writer-interference cases passed. In the separate shared-CPU test,
both the stock and option protective exits filled and the full cases
finished in 4.94 and 4.91 seconds. The competing 124 cases passed.
The preceding `0c46df3` application passed 587 system checks. The text
report in `88c9ba0` passed 111 overlapping report, timing and private-copy
cases. On a saved failure it reports one failed acknowledgement in two
measured calls, one subsequently matched attempt, and a completed round trip.
[Offline tests and timings](PAPER_TIMING_20261116_PROOF.json).

The November 14 installed system run on `e2ced11` passed 565 checks with
one unmapped dashboard reader UID. The reviewed feed-recovery monitor now
verifies the journal in a read-only worker. The native owner rechecks the
operator veto, generation, account and original market clocks before any
resume. A separate regression completed a native snapshot while the
verification read was held open. [Measurements](PAPER_CAPACITY_20261114_PROOF.json).

The final paid-entry trace on `66d8ea4` passed 555 installed system cases
with one unmapped-UID skip. All 211 related timing, Scope, selection, entry
and report tests passed. The sets overlap. Three baseline cases reproduced
missing phase records on `77a0118`. A further 335-second run on the final
build evaluated both slots, completed one round trip and verified flat.
The separate 135-minute run on `9710cce` completed 27 of 27 scheduled
evaluations and verified flat after the worker stopped.

The verified recovery monitor in `77a0118` passed 553 installed system
checks with one unmapped-UID skip. A further 128 recovery, soak, calendar
and report checks passed. The earlier 358-minute baseline evaluated 25
of 72 scheduled slots. The repaired 22-session dashboard repeat evaluated
both follow-up slots, but its original entry plan expired before reservation.
[Duration and capacity results](PAPER_DURATION_CAPACITY.md).

November 14 repository-wide regression on `875af6b` ran 7,186 cases.
There were 7,183 passes, two failures and one unmapped-UID skip. The failing
paid Swing retirement test injected a second writer inside the active
reservation. `14f87e8` now commits the independent retirement just before the
reservation. All four interleavings and all 69 related cases passed.
The archive restart test raced the server's early rejection of an interrupted
upload. `0dc5697` checks the 409 response with the original upload headers
and verifies the exact stored bytes. All 51 archive cases passed.

November 14 offline continuation. The pending implementation was recovered
and published as `29ef510`. The current protection implementation `5761f48`
passed 551 installed system checks with one unmapped-UID skip. Both loaded
protective exits completed while history and advice were blocked. The repository-wide run on `0349f38` completed
7,156 cases. Its first pass had seven failures and one skip. One interrupted
TLS upload passed in isolation. Six test failures traced to two fixture
assumptions about the source of a management order and the name of a host
temporary directory. Each corrected fixture passed with its related tests.
The 65-receipt dashboard reproduction and the held stock and option timings
are recorded in the [November 14 evidence](PAPER_CAPACITY_20261114_PROOF.json).

November 14 paid-entry and protection checkpoint. `54d8b93` passed 539
installed system cases with one cross-UID skip. `5cf21d1` passed 543 with
the same skip and 198 related checks. Both of its 120 MB CPU comparisons
completed a round trip and verified flat, with opening source ages above five
seconds. The saved report on `f27c9eb` reads the in-window native halt and
resume records. The 120 MB stock and option contention cases separately measure
the acknowledgement and the whole tick. The option acknowledgement took
3.64 seconds and the entire case took 5.14 seconds. See the
[measured checkpoints](PAPER_CAPACITY_20261114_PROOF.json).

November 14 decision-coverage update. The long fixture on `0d79a3a`
missed the 99% scan-coverage target after a feed halt two hours in.
`0349f38` and `4329383` repair stale PAPER fill and protection clocks.
Both passed the installed system suite with 532 passes and one unmapped-UID
skip. The held-position repair passed 118 related cases and the loaded
contention fixture. `23b0669` passed 248 related checks and the 532-case
system suite with the same single skip. Its two 120 MB runs evaluated both
expected slots and completed one round trip in each CPU configuration. The
22-session replay finished with 1,738 packets and verified flat accounting.
[Measured cases](PAPER_CAPACITY_20261114_PROOF.json).

November 14 capacity continuation. Branch implementations `1e67fd7`, `5f5f96c`
and `42648c6` are published. The integrated system suite passed 532 cases with one unmapped-UID
skip. The final report revision also passed 89 cases including all five integrated
lifecycles. The final native/portfolio checks passed 282 cases. The suites overlap.
Four ordinary 120 MB one-CPU trials of the latest release finished flat. A shared-CPU
case ended before its late entry could exit. The host remains on `39d8e48`.
[Capacity and timing checkpoint](PAPER_DURATION_CAPACITY.md).

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
