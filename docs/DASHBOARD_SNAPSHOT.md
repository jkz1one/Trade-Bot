# Native dashboard snapshot publisher

The connected simulator keeps one native virtual-money owner. This publisher makes
an atomic, read-only display copy of its journal for the existing dashboard. It
creates no brokerage account, execution owner, second bankroll, venue or worker.
It does not run the simulator, resume entry or submit orders.

## Host integration gap

The successful read capture ran as root and accepted the existing root-owned OAuth
files. The existing dashboard runs as UID/GID 10001, with private owned-file checks.
Directly pointing that reader at a root-owned journal fails those checks. Moving
credentials or changing the native journal's ownership is unnecessary.

The publisher reads the original journal, validates a complete SQLite backup with
the native mixed-account observer, then atomically replaces the display copy. Only
the newly created copy is assigned to UID/GID 10001. Original timestamps, account
state, two-play identities, fills and accounting remain intact. The source owner
may keep its execution lease while a separate publisher lease prevents two writers
to the display directory. Readers already holding the old database see a complete
old snapshot; new requests see the replacement.

Publication is bounded by a 64 MiB database limit and a five-second backup/validation
budget. Native observer validation retains its own bounded reads. A publication
started before shutdown may finish before the publisher exits. This is a display
cadence, not a trading or quote-freshness guarantee. Stopped publication can leave a
stale display; check the publication receipt and original feed clocks separately.

## Frozen binding and failures

Creation binds canonical source/destination paths, population, native configuration
hash, publisher UID and reader UID/GID. Later publications require that same binding.
Revision, runtime generation, feed sequence and publication clock cannot move
backwards. A mirror cannot be selected as another publisher's execution source.
The display copy contains its own publication receipt; no receipt is written into
the native journal. Checks are read-only and report snapshot age and source revision.

Preparation is create-only. Existing output, failed `.pending.db` files, altered
bindings, public files, symlinks, accounting failures and regressed checkpoints are
rejected. Failed copies remain for inspection and the last completed display copy
is retained. Do not delete evidence or rerun preparation to bypass a failure.
If replacement succeeded but the subsequent directory sync failed, inspection can
find the new complete snapshot even though the command returned an error.

## Host helper, not activation

`scripts/connected-dashboard-snapshot-host.sh` accepts:

```text
prepare /absolute/existing-owner
publish /absolute/existing-owner
check /absolute/existing-owner
run /absolute/existing-owner SECONDS
```

The owner must already be enrolled, root-owned and private, with native runtime,
journal and venue files. Do not use the frozen UI review fixture. The helper requires
a clean release checkout and root. Preparation builds the pinned local image and
creates `/var/lib/trade-bot-dashboard-publish/connected-v1`. Other operations reuse
that release image. Duration is explicitly 1..86400 seconds; cadence is five seconds.
All operations use the same `/source` and `/exports/connected-v1` container paths;
do not mix these bindings with differently mapped direct CLI invocations.

The container has no network, credential/password mounts, exposed ports or service
management. Its root filesystem and native source mount are read-only. Only the
publisher output mount is writable, and `check` mounts that read-only as well.
Capabilities are limited to CHOWN for the newly created copy and DAC_READ_SEARCH
for inspecting the previous reader-owned private copy. Permissions are set before
ownership transfer, so FOWNER is not required. The output parent remains root 0700;
the display directory is root 0711, allowing reader traversal through a future
Docker directory bind. Database files are reader-owned 0600. Binding and lease
files stay root-owned 0600. No credentials are copied into this directory.

The [reviewed dashboard switch](CONNECTED_DASHBOARD_HOST.md) mounts the **directory**, not the single database
file, read-only at its data path; a file bind would pin the replaced inode. It
retains user 10001, the existing login and disabled operator controls. The mirror
has no operator-command delivery channel. Writable operator transport requires its
own native guarded integration. This helper does not switch Caddy, containers,
ports or passwords, and does not start or stop the runtime or collector.

## Validation and remaining work

See `DASHBOARD_SNAPSHOT_PROOF.json`. Installed-wheel tests cover native empty and
two-held-play state, committed WAL snapshots, retained accounting, atomic reader
replacement, lease exclusion, checkpoint regression, source immutability and
failed publication. Shell tests execute the actual helper against offline Git and
Docker recorders, including preflight refusal and exact mount/capability arguments.
These are not Docker host acceptance tests.

The workspace maps only UID/GID 0. Its initial real cross-user test failed when the
kernel rejected ownership transfer to unmapped UID/GID 10001. The retained real
cross-user test now explicitly skips in such an environment. No successful host
ownership or dashboard-login acceptance is claimed. Run that test in a suitable
root environment before relying on the cross-user bridge for deployment.

Reviewed host owner settings/enrollment, actual dashboard activation acceptance, writable
operator transport, eligible catalyst/Scope data, complete contract/data eligibility
and connected market acceptance remain unfinished. The accepted regular-session
quote proof remains valid as capture evidence; recollection is not needed to keep
coding. The server remains on the frozen a653cc7 review with no connected runtime.
This is a slice end, not a missing-feed stop. LIVE remains disabled.
