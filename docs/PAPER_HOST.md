# Isolated PAPER host service layout

The three units in `deploy/paper/` provide separate runtime, native TLS operator
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
| Signing/read credentials and native TLS pair | `/etc/trade-bot-paper/operator` |
| Dedicated alert token and optional CA | `/etc/trade-bot-paper/alerts` |
| Optional private model key | `/etc/trade-bot-paper/model` |
| Optional exclusively managed market OAuth | `/etc/trade-bot-paper/market` |

Install a verified wheel and its pinned dependencies into the dedicated Python 3.12
environment. Keep code/environment root-owned and read-only to the service user;
do not run from a writable checkout. The units use Python isolated mode (`-I`), so
PYTHONPATH, user-site imports and Python environment overrides cannot select code.
No service executes `git pull`, installs packages or creates an experiment at startup.

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
leases. Each role blocks peer credential directories and the deployed SHADOW paths.
Control/alerts do not see model/OAuth secrets. Runtime does not see operator/sink
secrets. These restrictions require actual target-host namespace verification;
parser acceptance and local native process tests do not prove kernel enforcement.

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
