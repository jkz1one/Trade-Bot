# Same-transaction restore verification and repeated entry qualification

## Failure being addressed

The November 28 duration attempt failed during its first opening, after about
58 seconds of container life and 37 seconds of runtime observation. Its native
acceptance had 1.309 seconds remaining and timed out in response read. The quote's
original source time plus the unchanged ten-second age limit bound this attempt.
Peak cgroup memory was 652.48 MiB, with zero limit/OOM events. This is not evidence
of the earlier multi-hour publisher or memory failure. The prior short pass is
retained, but its larger opening margin was not reliable across attempts.
[Selected supplied evidence](PAPER_DURATION_ENTRY_FAILURE_20261128.json).

Fourteen digest calls consumed 4.689 seconds of owner-thread CPU before review in
the supplied trace. Each fenced write verified the complete retained journal,
then scanned it again to commit the new independent restore authority. The large
timing-history table dominates the seeded fixture. Native startup improvements
alone did not eliminate the preceding owner work.

## Documented mechanism and limits

SQLite [permits only one writer](https://www.sqlite.org/lang_transaction.html).
The existing `BEGIN IMMEDIATE` transaction already excludes another SQLite writer
while the old state is verified and the new state is committed. The implementation
reuses the exact canonical bytes of verified timing rows only inside that lock.
Connection-local [TEMP row triggers](https://www.sqlite.org/lang_createtrigger.html)
record changed rowids at execution time. The second digest rereads every changed
rowid and all other execution tables, and hashes the original sorted v1 stream.
Every subsequent transaction and every verified read still scans all committed
rows. No persistent cache, new database format or trusted hash supplied by a
caller is introduced.

The [authorizer callback](https://www.sqlite.org/c3ref/set_authorizer.html) runs at
statement preparation, not execution. It is used only to invalidate reuse on
unsupported operations, never to infer which rows changed. Cached statements,
`executemany`, indirect triggers, foreign-key cascades and savepoint rollbacks
are covered by row tracking and regression tests. Extra dirty ids are safe: they
are reread from the final transaction state, including deleted or rolled-back rows.

SQLite [REPLACE can omit delete triggers](https://www.sqlite.org/lang_conflict.html).
Reuse therefore applies only to the existing three-column timing schema whose
sole unique key is the INTEGER rowid alias. INSERT/UPDATE record both relevant
ids; any unique secondary index or actual schema change forces a full scan.
Incremental [BLOB writes](https://www.sqlite.org/c3ref/blob_write.html), callback
replacement, extension APIs, explicit transaction ends and other bypasses also
invalidate reuse. This relies on SQLite transaction locking, not protection
against hostile raw filesystem writes or arbitrary replacement of application code.

The original DELETE journals, FULL synchronization and attached authority commit
are retained. SQLite's [multi-file atomic commit](https://www.sqlite.org/atomiccommit.html)
requirements are why WAL is not a drop-in performance change here. The restore
hash, generation, rollback behavior, expiry decisions, unknown-attempt recovery,
position protection and execution/resource limits are unchanged.

The snapshot is bounded to 160 MiB including counted mapping overhead, 40,000
original rows and 4,096 changed ids. Overflow or unsupported schemas use the full
scan. It usually references the existing encoded-row cache, but concurrent cache
eviction can retain additional bytes until commit/rollback. Local short tests do
not qualify multi-hour memory headroom, especially after the table exceeds this
bound. The optimization targets opening latency; it does not close endurance.

## Measurement and next qualification

On one pinned local CPU, four alternating blocks on the same 112-MiB synthetic
history measured warm median writes of 356/362 ms with full scans and 308/301 ms
with transaction reuse (about 14–17% lower). Each write changed control state and
inserted/updated timing rows. Both policies matched the independent legacy v1
hash and verified the authority. This is a local transaction comparison, not an
attribution of host speed or a complete reproduction of its timeout.

The noneditable installed package passed 382 focused regression tests. Three
fresh 90-second lifecycles on one pinned local CPU each completed one entry and
one protective exit, verified flat accounting and 51 successful native snapshots.
Acceptance budget at spawn was 3.668–3.817 seconds; transport was 0.468–0.529
seconds. Peak sampled process-tree RSS was 449,708,032 bytes across these trials.
This environment cannot enforce the host cgroup; the local runs are also shorter
than the host profile. Neither result is a host qualification.

The next host profile is `entry-repeat`: three fresh 335-second lifecycles in
separate processes and disposable accounts, sequentially using one immutable
image/container. Each retains its own source, report, diagnostics and outcome.
It stops on a failed lifecycle or insufficient measured acceptance margin. The
status checker requires all three complete lifecycles, flat accounting, original
OPEN diagnostics, matching application identities, no memory-limit events, zero
restarts/OOM and at least twice the observed transport duration remaining at
spawn. That ratio is a qualification threshold, not a runtime deadline change or
a statistical reliability claim. Any failed trial blocks advancement; do not
repeat until a new measurable hypothesis/repair is available.

The host test remains one CPU, 1 GiB, no extra swap, no network or credentials.
Fresh progress, feed/heartbeat at report cutoff, actual decisions/fills and
terminal results are all distinct from a running container. Zero fills alone
are legitimate in ordinary PAPER sessions; this explicitly synthetic fixture
requires a known entry and protective exit. Three passing starts still do not
qualify repeated entries within one long-lived account, sustained publication,
provider CONNECT health or an entire connected PAPER day.

[Local verification record](PAPER_RESTORE_TRANSACTION_20261128_PROOF.json).
