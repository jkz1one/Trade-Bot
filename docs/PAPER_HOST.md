# Isolated PAPER host service layout

The three long-running services in `deploy/paper/` provide separate runtime, native TLS operator
control and alert lifecycles on a Linux systemd host. They are a reviewable deployment
layout for the isolated fixture engine, not an upgrade of the running SHADOW worker
or `virtual-v1`. No unit has a broker write adapter or LIVE promotion path.

## Paths and prior provisioning

Use a dedicated `tradebot-paper` user/group. The existing private execution journal,
independently retained authority, local fixture venue and quote feed belong to that
same user with mode 600, in a mode-700 population directory. The services use the
same UID because the current-owner journal/credential checks are part of their
contract. Namespace restrictions limit peer credential access; these are not
protection against that UID outside the service sandbox or the host owner.

| Resource | Fixed location |
| --- | --- |
| Installed Python environment | `/opt/trade-bot-paper/venv` |
| Runtime population | `/var/lib/trade-bot-paper/population` |
| Optional bounded local checkpoint catalog | `/var/lib/trade-bot-paper/checkpoints` |
| Signing/read credentials and native TLS pair | `/etc/trade-bot-paper/operator` |
| Dedicated alert token and optional CA | `/etc/trade-bot-paper/alerts` |
| Optional private model key | `/etc/trade-bot-paper/model` |
| Optional exclusively managed market OAuth | `/etc/trade-bot-paper/market` |

Install a verified wheel and its pinned dependencies into the dedicated Python 3.12
environment. Keep code/environment root-owned and read-only to the service user;
do not run from a writable checkout. The units use Python isolated mode (`-I`), so
PYTHONPATH, user-site imports and Python environment overrides cannot select code.
No service executes `git pull`, installs packages or creates an experiment at startup.

That interpreter isolation also applies to every fixed execution child: fixture venue,
model judgment, market reads, alert delivery and checkpoint archive transfer launch
the same interpreter with `-I -m` and exclude `PYTHONPATH` from their environment.
A parent's `-I` flag is not inherited by a newly launched interpreter. Without the
child flag, a writable working directory could select another `app` package before
request validation; retained `PYTHONPATH` could also select modules/startup hooks.
Each child now uses the selected environment's installed package instead. Install
the application and dependencies into that interpreter before running the engine;
an absent installation fails closed instead of falling back to checkout imports.
Trusted installed site packages and their installation hooks still remain trusted.
This is an import boundary, not an OS sandbox or protection against modification of
the installed environment, arbitrary same-UID processes or the host owner.

Before installing/enabling units, explicitly initialize a new population under the
service UID using the installed `app.execution.runtime_cli init`. Match the fixed
population directory and credential paths. Enroll the operator signing credential
with `--operator-key-file /etc/trade-bot-paper/operator/signing.hex`. Enroll the
separately provisioned exact HTTPS sink with `--alert-origin` and
`--alert-token-file /etc/trade-bot-paper/alerts/sink.hex`; optional `--alert-ca-file`
must be within that alerts directory. The sink must implement the exact ID/hash
receipt contract. Do not place a secret value in unit files, environment or arguments.

The operator unit also requires independent `operator/read.hex`, `operator/chain.pem`
and mode-600 `operator/tls.key`, current-owner regular files. Signing/read tokens
must differ. The certificate must cover literal IP 127.0.0.1, and clients must verify
its chain with their trusted CA. Native TLS remains on loopback port 8788. Remote
operator access needs a separately verified authenticated tunnel/access arrangement;
these units add no public route, firewall rule, Caddy rule or DNS change.

Default runtime initialization uses stub HOLD and manual fixture quotes. Optional
model opt-in must freeze `--key-file /etc/trade-bot-paper/model/openai.key` and explicit
budgets. Optional market opt-in must freeze the dedicated OAuth file inside
`/etc/trade-bot-paper/market` and `--continuous-market`. Runtime-only OAuth refresh
writes are allowed in that directory; model credentials remain read-only. Market
quotes still feed fake venue execution, not broker fills or the separate next-quote
synthetic portfolio. Do not copy concurrent refresh ownership from deployed OAuth.

Existing populations are not migrated, re-enrolled, moved or reset by these units.
Frozen paths must match the service filesystem. The units condition startup on
existing journal/authority files (and venue/feed for runtime); a skipped condition
is not healthy service evidence. Native startup additionally validates enrollment,
configuration, private credentials and retained authority. Provisioning may leave
an incomplete exclusive directory after a failure, requiring inspection rather than
silent reuse.

## Independent lifecycles and bounds

There is no Requires/BindsTo/PartOf coupling between the three services. A runtime
failure or explicit runtime stop leaves operator review and alert delivery available.
The runtime has `Restart=no`: process failure does not create an automatic model/order
retry loop. Enabling the unit starts it on boot, so an unclean owner is still reviewed
by existing startup recovery and remains halted; reboot does not RESUME execution.
Ordinary signed recovery/evidence guards still apply. Explicit owner restart preserves
completed slots and never replays an ambiguous order/model attempt.

Control/alerts use `Restart=on-failure`, a 10-second delay and three starts per
five-minute interval. Reattachment does not enroll, recover the trader, resume,
acknowledge or reset alert retry counts. Exhausted deliveries stay exhausted after
process restart. Repeated invalid startup ends in a systemd start-limit failure,
requiring operator review. These are process policies, not remote notification or
archive availability guarantees.

SIGTERM goes to the main process first (`KillMode=mixed`). Each native entry point
retains its lease while it drains/reaps children. Runtime has 240 seconds before the
host's final cgroup kill, allowing its configured maximum cycle/supervision bounds.
Control/alerts have 45 seconds for their bounded current work and cleanup. If those
bounds are exceeded, systemd's final kill cannot fabricate a successful receipt or
release uncertainty in journal evidence. Unclean death is detected on subsequent
owner startup; the alert sender alone cannot infer a missing halt event from SIGKILL.
External dead-process/host-loss monitoring remains a separate requirement.

All units use an owner-private umask, no new privileges, a read-only system tree,
protected home/kernel/device namespaces and separate private temporary directories.
The shared population remains writable for SQLite paired transactions and native
leases. Every role mounts an empty read-only 1MiB tmpfs over `/etc/trade-bot-paper`,
then binds only its permitted credential directories into that view. Runtime binds
model credentials read-only and market OAuth read/write for refresh. Control binds
only operator credentials read-only; alerts bind only alert credentials read-only.
Checkpoint binds no credential directory. The tmpfs root explicitly uses mode 0755
for traversal; bound private directories/files retain their original owner/modes.

The credential-root mask is unconditional. It does not depend on peer directories
existing at startup, unlike optional `InaccessiblePaths=-...` entries, which systemd
ignores when absent. Unlisted host credential content, including directories created
later, is outside the masked view. Optional runtime binds are omitted when their
source is absent and require an explicit role restart after separate provisioning;
there is no enrollment, credential discovery or automatic experiment change.
Existing explicit peer blocks and deployed SHADOW path blocks remain additional
restrictions. This follows the
[Ubuntu 24.04 systemd empty-tree/bind pattern](https://manpages.ubuntu.com/manpages/noble/man5/systemd.exec.5.html).
It does not isolate one role from arbitrary processes using the same host UID or
from a host owner changing mount topology. Actual target-host namespace verification
must test the role view and absent-then-created peer directories;
parser acceptance and local native process tests do not prove kernel enforcement.

## Read-only host snapshot audit

After the separate PAPER installation is running, collect a snapshot using its
trusted installed environment. This command requires root metadata access:

```bash
sudo /opt/trade-bot-paper/venv/bin/python -I -B -m app.execution.host_audit
```

It prints one `paper-host-audit-v1` JSON report. Exit 0 means all three role
snapshots matched; exit 1 means a prerequisite or observation was blocked. Neither
result completes host acceptance: `host_acceptance` always remains `UNVERIFIED`
and `execution_authority` is always false. Preserve the report alongside the
release/wheel identity and separately collected host acceptance evidence.

The audit pins the reviewed unit byte digests, rejects symlinks, writable units,
drop-ins and a manager needing reload, and queries only fixed `systemctl show`
properties with `--all` so empty requested fields such as DropInPaths are retained.
Each query has a five-second deadline, a 64KiB output limit and child
cleanup. It checks active process identity, the exact isolated interpreter command,
dedicated UID/GID and a mount namespace distinct from PID 1. In that process view,
it checks the credential root's read-only tmpfs, allowed bind identities/options,
private directory ownership/modes, nested mounts and absent or empty inaccessible
peer placeholders. Two reads of process/mount/unit/manager identity detect changes
during each role observation; the boot identity must also remain stable. The roles
are observed sequentially, not as one atomic host snapshot.

The command reads only the reviewed unit files, selected `/proc` metadata and
credential directory names/stat metadata. It never opens credential contents,
execution databases, authority files or journals; never installs, starts, stops,
restarts or enables services; and makes no broker/model/archive/alert calls. Raw
manager stderr, command lines, unexpected paths/names and exception messages are
excluded from its public report. Missing root access, a non-systemd PID 1, missing
services or inaccessible metadata fail closed without attempting setup or fallback.
There are no supplied unit/path/proc-root overrides or mutation switches.

This is a structural snapshot, not service-UID access testing, continuous monitoring,
a cgroup/child-bound proof, complete filesystem isolation, a boot/restart/failure
exercise, checkpoint timer verification or an independent host-owner witness.
Absent-then-created peer credentials, deployed SHADOW path exclusion, full namespace
enforcement, authenticated provider operation, external alerts/archives and host-loss
recovery remain separate gates even after all three snapshots match. Local metadata
fixtures and native bounded query tests do not prove DigitalOcean kernel enforcement.
No command in this section has been run against the deployed SHADOW host.

The Linux [mount metadata](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html)
and [process root view](https://man7.org/linux/man-pages/man5/proc_pid_root.5.html)
contracts define the observations; per-mount read-only options are checked separately
from the backing filesystem's superblock options.

## Optional local checkpoint timer

`trade-bot-paper-checkpoint.service` and `.timer` add an independent local-only
oneshot capture at 01:15 UTC. Explicitly initialize the catalog under the service
UID with the installed `checkpoint_cli capture-init`, using the fixed journal and
catalog paths above. The parent must already exist; initialization exclusively
creates the mode-700 catalog. Capture freezes the existing authority UUID, timeout
and admitted-job limit. The unit never initializes an engine or adopts missing evidence.

The service has `Restart=no`, private networking, AF_UNIX only, and masks the entire
`/etc/trade-bot-paper` credential tree with the same read-only tmpfs and no binds,
including when the host tree was absent at startup. It also blocks deployed SHADOW paths. It has no
HTTP archive destination or upload operation. Source population and catalog are
the only writable namespaces: paired SQLite RESERVED locks require opening the
source databases read/write, but capture rolls back those lock transactions without
advancing generation or mutating source state. These filesystem permissions alone
are not protection against arbitrary code running as the owning UID.

The application timeout is cooperative and shared across validation/export, at
most 30 seconds. Systemd bounds startup at 45 seconds, with a 10-second stop allowance;
final termination preserves incomplete admission rather than manufacturing success.
SIGTERM is not a successful capture receipt or graceful partial-export completion.
The timer's `Persistent=true` attempts a missed activation when enabled/booted;
it captures current evidence, not the missed historical state. There is no coupling
to runtime, control, alerts or the deployed cron. Missing path conditions skip the
job, which is not evidence of a successful backup.

Complete and incomplete jobs count toward the frozen capacity (default 30, maximum
90); nothing is automatically deleted. Capacity or space failures need review and
will recur on later timer activations until addressed. Inspect journalctl, timer
state and `capture-report`; no external missed-backup monitor is supplied here.
Keep pins and verified archives independently off-host before treating this as
host-loss protection. See [capture and quarantine semantics](EXECUTION_CHECKPOINTS.md).

After reviewing provisioning, optionally install both checkpoint units alongside
the three role services, verify them on the actual host, then explicitly enable/start
the timer. They are not installed or enabled by this code change. Native tests cover
CLI capture, source-loss reporting/quarantine, SIGKILL during paired copy, retained
incomplete jobs and subsequent distinct capture; parser validation covers both units.
Target-host namespace enforcement, nightly execution and off-host recovery remain gates.

## Validation and deployment boundary

The source units pass the native systemd parser with only the executable/user/group
mapped to the local test environment. Native tests run three independent installed
Python processes with verified local TLS, an explicit held fixture market session,
fake account reads and no remote broker/model calls. They exercise completed HOLD,
read-failure halt, SIGKILL/explicit owner restart, surviving review/alert services,
signed ACK replay, independent companion restart and graceful shutdown. The test-only
clock fixture is not a production clock override or historical replay feature.

Host installation is a later integration step. Once population, dependencies,
credentials, TLS and external sink contracts are verified, copy the reviewed three
unit files to `/etc/systemd/system/`, run `systemd-analyze verify` on the actual files,
and explicitly enable/start the desired roles. Inspect journalctl plus read-only
runtime, operator and alert reports. Confirm namespace credential isolation, startup
conditions, lease exclusivity, process bounds, boot retention, actual alert acceptance
and a verified recovery drill on that host before treating this as operational.
Do not run these steps against the existing `/opt/trade-bot` SHADOW checkout/image.

No unit has been installed or started on the DigitalOcean server by this change.
Authenticated full-universe latency/model billing, external recipient notifications,
independent archive protection and host-failure recovery remain unverified. Default
PAPER and LIVE-disabled authority remain unchanged.
