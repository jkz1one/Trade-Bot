# PAPER engineering review — November 27

## Static host result and measured report-storage repair

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

## Updated publisher evidence and bounded next action

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

## Earlier assessment of terminal evidence

## Terminal host evidence, supplied later on November 27

The retained test ended after about 4h 49m with a publisher component failure,
exit 1, no restart and no OOM kill. Its cgroup peak reached 1 GiB and recorded
603,798 max-boundary events. It completed 4,529 native snapshot reads without
failure but never recovered its rejected fixture entry. Final low current memory
is post-exit evidence, not the running working set. The concrete publisher error
has not been supplied; cumulative memory counters do not establish its cause.
[Exact receipt](PAPER_SOAK_20261127_HOST.json).

The evidence path now retains primary and shutdown causes together and can read
the old stopped journal's publication event without a rebuild. This closes a
reporting gap, not the publisher incident or capacity gate. Read that durable
cause before another host trial; keep the next application qualification short.
[Evidence-path verification](PAPER_SOAK_TERMINAL_20261127_PROOF.json).

## Earlier assessment at the 66-minute observation

More RAM is not the demonstrated remedy for the first-entry failure. The earlier
`20923e2` test did die from OOM; the current `d2e78bf` test rejected its intended
entry before reservation while continuing to run. These are different failures.
Keep the existing deployment, resource limits, account and review hold unchanged.

At the latest operator observation, the current test has run about 66 minutes
with zero restarts/OOM and 1,435 native snapshot reads without failure. Current
cgroup memory is 703.3 MiB; peak is 949.0 MiB against 1,024 MiB. Approximately
75 MiB of peak headroom is not comfortable capacity qualification. Usage has grown
since the 17-minute observation, but two samples cannot distinguish eventual
cache stabilization from continued growth. A full-duration result is still needed.
[Exact host evidence](PAPER_SOAK_20261127_HOST.json).

## The measured critical path

The quote source time was `14:00:19.848382Z` in the synthetic session. The original
ten-second quote limit set `valid_until=14:00:29.848382Z`. The account was captured
at `14:00:24.014596Z` with a twenty-second limit; account freshness did not shorten
this plan. No timestamp or deadline should be extended to make the test pass.

| Checkpoint | Original quote age |
| --- | ---: |
| Received | 1.000 s |
| Strategy cycle starts | 5.613 s |
| Plan assembled | 7.615 s |
| Synthetic model replies | 9.664 s |
| Entry review | 10.623 s — expired |

The fixture model itself took only 0.003779 seconds. It had 0.335549 seconds left
when it returned; durable settlement took 0.934584 seconds. Protection wait took
0.000120 seconds. The cycle's claim, stock scan, request admission and settlement
spans total about 4.69 seconds without double-counting their nested spans. A
faster model or more RAM does not remove this recorded bookkeeping delay. The
provided evidence does not measure host CPU throttling or disk wait, so it does
not establish how much a CPU upgrade would help.

## Architectural concern

`ExecutionJournal.write` calls `restore.begin_fenced_write` before mutation and
`restore.advance` before commit. Both perform a full canonical journal digest.
The implementation reuses bounded JSON encodings, but each scan still reads and
fingerprints current rows. Thus repeated write transactions remain sensitive to
the size of retained history. The entry/protection path invokes several of them.

This is a concrete design constraint, not evidence that every host millisecond
was hashing: the saved host spans include lock, SQL and commit time. A prior local
loaded profile measured 4.84 of 6.54 seconds from quote source to reservation with
a digest running. A fresh read-only profile on the 112-MiB diagnostic owner found
five warm digests taking 0.843 seconds total, including row reads, typed-batch
fingerprinting and encoding-cache lookup. Neither local timing substitutes for
host CPU/I/O measurement.

The implementation decision needs to cover the whole critical path. Prefer
removing proven redundant transactions and work before considering changes to
restore verification. Any deeper change must preserve independent rollback
detection, current-row/schema checks, durable paid charges and protective latches,
and commit-before-native-handoff. A cache, an old snapshot or a background task
is not by itself evidence that these guarantees survive. Do not weaken a deadline,
discard history or move safety work out of the path without proving the replacement.

There is an explicit architecture decision to make: execution cost should not
keep growing with every retained diagnostic and historical record. Review the
integrity boundary and its threat model. A compact current-state journal with
independently authenticated historical checkpoints is one design to evaluate;
it is not implemented or qualified here. If full historical rescanning on every
commit is truly required, its growing CPU/I/O demand must instead be treated as
a capacity constraint. Do not silently replace that guarantee with a cache or
an unverified background audit. Account preservation and a tested migration or
compatibility path are requirements for any eventual storage change.

## Why the development loop has been inefficient

1. **The acceptance unit has been too small.** Correct schema admission, a faster
   snapshot or a healthy publisher is necessary but does not prove a timely
   quote-to-entry-to-exit path. Test counts and process uptime cannot advance
   that gate. Past deployments and local passes were allowed to carry too much
   weight in deciding the next operator action.
2. **The local resource profile is not the server profile.** One pinned local CPU
   does not reproduce Docker CPU quota, shared host scheduling, memory charges
   or disk behavior. Local passes and host failures must remain separate.
3. **Some integration tests deliberately synchronize synthetic clocks.** They
   prove ordering, accounting and recovery, not independent real-time latency.
   The real-time soak is a separate test; it should not first expose a startup
   latency failure after a long operator handoff.
4. **The duration fixture offers one ENTER, then HOLD.** It can measure resource
   growth after that opening, but it does not prove repeated active entry/exit
   latency throughout a day. Its terminal entry rejection previously did not
   fail early; that harness gap is repaired in `7b58149`.
5. **Operator diagnostics have been piecemeal.** A single failure bundle should
   include original clocks, correlated phases, resource counters, failure and
   accounting evidence. Repeated one-field terminal requests are too slow.

## Revised work order

Current application checkpoint: settlement and reservation now share a fenced
commit when protection is complete. One redundant transaction/two digests are
removed; local original quote age at reservation changed from 4.029 to 3.392
seconds, and the complete entry cycle from 6.416 to 5.764 seconds. These are
single local observations, not closure of the host incident.
[Application proof](PAPER_ENTRY_TRANSACTION_20261127_PROOF.json).

Earlier tooling checkpoint: the deterministic original-deadline regression,
335-second host profile and consolidated original-clock/CPU/I/O/memory bundle
are implemented in [this proof](PAPER_SHORT_HOST_GATE_20261127_PROOF.json).
The remaining application latency and repeated-active-lifecycle items below stay
open; local proof does not qualify deployment or a full-duration host trial.

1. **One regression target:** original quote source to committed native acceptance
   under the unchanged ten-second ceiling, followed by protective exit and
   verified accounting. Use the measured aged-quote/settlement failure in a short,
   deterministic reproduction. Retain the existing five-second p95 entry-age
   engineering target; do not claim a percentile from one successful entry.
2. **One constrained baseline:** retain the current exact image, schema, history
   density and limits. Add a short host qualification mode that exercises the
   same application/resource settings as the long test, with automatic failure
   capture and bounded cleanup. It must remain a separate disposable population
   and never deploy or resume the connected owner. Do not launch it over the
   current retained worker.
3. **One hypothesis per implementation change:** report before/after phase cost,
   original quote age at native acceptance, work/transaction count, memory and
   accounting. Measure CPU quota/throttling and I/O counters automatically in the
   host receipt. Change code based on the identified cost; do not repeat unchanged
   tests looking for a favorable sample or use a capacity increase as proof of a
   timing repair.
4. **Short gate, then representative load:** run the targeted regression and
   loaded lifecycle first, then the relevant installed regressions once. Follow
   with repeated eligible decisions, HOLDs, filled entries, held-position exits
   and restart/recovery on original fixture data. A long mostly-flat run is only
   one part of this qualification.
5. **Long soak and connected checks last:** require actual sustained timing,
   memory headroom and verified lifecycle/accounting before deployment. The
   original provider CONNECT problem remains a separate connected gate. A
   synthetic pass cannot close it. Keep Scope/strategy expansion behind reliable
   operation in the development queue without changing current enrollment.

No RAM purchase, CPU increase, deployment, resume, halt clearing or host-worker
change is authorized by this review. A later sizing recommendation should follow
measured stable working-set demand and controlled latency evidence, with the
existing configuration retained as the comparison baseline.
