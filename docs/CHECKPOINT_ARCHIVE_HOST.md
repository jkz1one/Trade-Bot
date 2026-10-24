# Independent archive host lifecycle

`deploy/archive/trade-bot-archive.service` supplies the missing service lifecycle
for the [native TLS receiver](CHECKPOINT_ARCHIVE.md). It belongs on a separately
provisioned host/storage failure domain, with a dedicated `tradebot-archive` UID.
It is not installed by this change and must not be added to the frozen SHADOW host
or the PAPER service group. A second directory or process on the trader host is
not independent retention.

## Explicit provisioning and reviewed paths

| Resource | Unit path |
| --- | --- |
| Root-owned, service-read-only verified Python 3.12 wheel environment | `/opt/trade-bot-archive/venv` |
| Preexisting private archive store, owned by archive UID | `/var/lib/trade-bot-archive/objects` |
| Archive-only token, native TLS certificate and private key | `/etc/trade-bot-archive/receiver/{archive.token,chain.pem,tls.key}` |
| Reviewed service specification | `/etc/systemd/system/trade-bot-archive.service` |

Provision the user/group, protected parents, filesystem quota, encryption at rest,
DNS, native TLS chain/key, dedicated random token and network access separately.
The unit does not create them. Token/key must be archive-UID-owned mode-600 regular
files; its credential directory must be private and readable by that UID. Keep
unit files, environment and credential parents outside its write authority. Never
put token values in arguments, unit files or environment variables. Do not share
trader/model/market/operator/alert credentials with the archive host or UID.

Initialize exactly once as the archive UID, after reviewing the frozen capacity:

```bash
sudo -u tradebot-archive /opt/trade-bot-archive/venv/bin/python -I -m app.execution.archive_cli init \
  --directory /var/lib/trade-bot-archive/objects --max-objects 90
```

Existing stores are never adopted/reset. Incomplete initialization requires review,
not deletion/retry as an automatic startup action. Provision quota/free space for
the selected capacity; a systemd memory limit is not a disk quota.

The source service has the explicit placeholder `https://archive.invalid:8790`.
Before installation, replace only its hostname with the reviewed independent native
TLS origin, matching the certificate and transfer client configuration. The literal
placeholder is not an endpoint. Record the source release/wheel identity and the
resulting installed unit digest, including this reviewed substitution. The unit
listens on IPv4 `0.0.0.0:8790`; separately restrict network access to intended clients.
No DNS/firewall/proxy/tunnel is configured here. TLS verifies the actual server
identity at the client; no termination proxy, forwarded authority or plaintext
fallback is supported. Origin/listener changes require explicit unit review and
restart; they do not retarget an existing client transfer receipt.

After provisioning/review, use the actual host's `systemd-analyze verify` on the
installed unit before explicitly enabling/starting it. `Type=exec` and an active
manager state only establish process startup, not authenticated archive readiness.
Missing file conditions can skip startup; skips are not healthy evidence. Native
startup rechecks private files, store configuration and exclusive ownership.

## Namespace and lifecycle

The service has no coupling to runtime/control/alerts/checkpoints and executes only
`archive_cli serve` with the installed interpreter's `-I` import isolation. There
is no initialization, upload, report, pruning, authority attachment or recovery
command in startup/shutdown hooks. Only the existing object store is writable under
`ProtectSystem=strict`; home/devices/kernel/control groups and privileges are
restricted. Private temporary storage does not retain objects.

An unconditional empty read-only tmpfs masks `/etc/trade-bot-archive`; only the
receiver credential directory is bound back read-only. Unlisted archive credentials,
including ones created later, remain outside that view. Additional optional blocks
cover PAPER and deployed SHADOW trees, but absent optional paths alone are not
namespace proof. This layout does not protect against arbitrary same-UID processes,
trusted installation hooks or the host owner. Actual UID/mount/access enforcement
must be tested on the archive host, including absent-then-created peer paths.

SIGTERM reaches the main process first. It stops accepting new work after draining
the current connection's original maximum-30-second shared socket budget; the
store lease remains owned until cleanup. The host applies a 45-second cgroup stop
bound. Filesystem stalls remain cooperative application work and can reach that
final kill; termination cannot claim retention or turn an interrupted admission
into a complete object. `Restart=on-failure`, ten-second delay and three starts per
five minutes bound automatic process restart. Explicit stop does not auto-restart.
Restart only listens against the same store: it cannot retry a client upload,
repair/replace incomplete evidence, resume execution or reset capacity.

## Acceptance evidence still required

Native local tests execute the exact unit-derived CLI with only interpreter,
disposable paths, loopback origin/listener and port mapped. The original 30-second
connection deadline is retained. They verify duplicate-owner rejection, complete
object identity, a stalled admitted upload drained by SIGTERM within the 45-second
bound, actual SIGKILL/restart, retained incomplete bytes and later distinct upload.
Missing store/token/key never initializes or adopts state. The native systemd parser
accepts the specification with only local executable/user/group substitutions.
These are process/parser fixtures, not systemd cgroup or mount enforcement.

Actual archive acceptance requires the installed unit identity, dedicated UID,
credential/store access tests, stable independent storage/quota/encryption,
authenticated exact upload receipt, boot/failure/stop behavior, external dead-host
monitoring and later verified retrieval with a separately retained pin after source
host loss. Stop the receiver before its exclusive `archive_cli report`; stopping
it does not revoke earlier remote receipts or prove future retention. The existing
download/stage commands recover evidence into quarantine only. Reports continue
to declare `off_host_protection=UNVERIFIED` and `execution_authority=false`; no
service state or local test can promote them to operational acceptance.
