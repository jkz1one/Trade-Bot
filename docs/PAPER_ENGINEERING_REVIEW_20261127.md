# PAPER engineering review — November 27

## Assessment

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
