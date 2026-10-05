# Persistent SHADOW worker on a Linux droplet

The server runs the OpenAI SHADOW scheduler independently of the Mac or SSH session.
The application remains Robinhood READ plus approved order review only. LIVE and
broker placements/cancellations remain disabled. This is a worker deployment;
there are no published web ports or changes to SignalFlow's services.

## Layout and requirements

Use a separate checkout at `/opt/trade-bot`, Compose project `trade-bot-shadow`, and
these persistent host paths:

| Path | Contents |
| --- | --- |
| `/var/lib/trade-bot/data` | SQLite history, schedule claims, service state, backups |
| `/var/lib/trade-bot/oauth` | Robinhood OAuth client/tokens, writable for refresh |
| `/etc/trade-bot/openai_api_key` | Private OpenAI key file |

Directories are mode 700 and credential/data files mode 600, owned by container
UID/GID 10001. The non-root container has a read-only application filesystem, a
temporary `/tmp`, rotated logs, and a 512 MiB memory limit. The host needs Docker
Engine with Compose v2+, outbound HTTPS and capacity alongside existing services.
Installing or upgrading Docker and changing other workloads is outside the helper.

Builds are tagged with the checked-out commit SHA; the worker records that SHA.
The helper refuses a build with tracked modifications or untracked files. Runtime state is never
included in the image. PAPER's existing Compose configuration is separate.

## Initial setup and migration

The following root commands run on the target droplet. Use its existing SSH access;
do not paste API keys or OAuth files into chat. If the repository is private, clone
using the server's existing GitHub authentication or a read-only deploy key.

```bash
git clone --branch slice2/robinhood-read-shadow --single-branch \
  https://github.com/jkz1one/Trade-Bot.git /opt/trade-bot
cd /opt/trade-bot
./scripts/shadow-server.sh prepare
./scripts/shadow-server.sh build
```

Stop the Mac's foreground `shadow-run` process with Ctrl-C and let any current cycle
finish. Do not leave another runner connected to this account. On the Mac, pull the
server follow-up, then export a private migration bundle using the already configured
API key and OAuth state. The export uses SQLite's consistent backup API and refuses
an interrupted active claim or a running `shadow-service`.

```bash
git pull --ff-only
python -m app.robinhood.cli shadow-export --output /tmp/trade-bot-bootstrap
scp /tmp/trade-bot-bootstrap/robinhood.db \
  /tmp/trade-bot-bootstrap/robinhood-oauth.json \
  /tmp/trade-bot-bootstrap/openai_api_key \
  root@DROPLET_IP:/root/trade-bot-bootstrap/
```

Replace `DROPLET_IP` with the confirmed server address. If root SSH is disabled,
transfer to a private directory under the existing SSH user and use `sudo` for the
root setup/import commands. Do not run the Mac worker again after the migration.

On the droplet:

```bash
cd /opt/trade-bot
./scripts/shadow-server.sh import /root/trade-bot-bootstrap
./scripts/shadow-server.sh preflight
./scripts/shadow-server.sh probe
./scripts/shadow-server.sh start
./scripts/shadow-server.sh status
./scripts/shadow-server.sh logs
```

`preflight` checks local configuration and stored credentials without network calls.
`probe` verifies Robinhood authentication with safe reads only. Token transfer and
refresh must be verified on this host; do not infer success from the Mac check.
If Robinhood requires authorization again, run `./scripts/shadow-server.sh authorize`.
That explicit interactive command stops the daemon, prints the authorization URL
for your browser and accepts the callback URL over SSH. The unattended worker never
opens a browser or waits for input. Restart with `start` after authorization succeeds.

`start` launches detached. Check `status` after the first heartbeat; during a closed
session logs should show MARKET_CLOSED without broker/model calls. Ensure the host's
Docker daemon starts at boot. Once startup and restart are verified, closing SSH or
shutting down the Mac does not stop the worker. Keep the private transfer bundle only
as long as needed for migration verification; manage its deletion separately.

## Operation and failure recovery

```bash
cd /opt/trade-bot
./scripts/shadow-server.sh status
./scripts/shadow-server.sh audit
./scripts/shadow-server.sh history
./scripts/shadow-server.sh outcomes
./scripts/shadow-server.sh slots
./scripts/shadow-server.sh logs
```

Health checks inspect only local heartbeat and state. They do not prove current
OpenAI billing, remote authentication, or trading signal quality. There is no external
alerting or browser dashboard in this deployment.

Docker restarts an unexpectedly exited container. An application failure instead
latches HALTED in SQLite and keeps an idle worker with an unhealthy check. A restart
does not clear that halt or repeatedly spend credits retrying a failed slot. Missing
credentials, model/review failures, calendar errors, interrupted claims and a
600-second cycle timeout all stop further scheduled attempts.

SIGTERM stops new cycles and allows the active cycle to drain; Docker allows 660
seconds before termination. A hard interruption can leave a CLAIMED slot. It blocks
new work across restarts and is never automatically replayed or expired.

Known limitation from the [SignalFlow review](SIGNALFLOW_REUSE_ASSESSMENT.md): the
600-second deadline cancels the awaiting coroutine, not a synchronous model thread
already executing through `asyncio.to_thread`. That request may continue after HALTED,
and executor shutdown can outlast the normal drain. Docker may ultimately force
termination. Harden/verify the real-call timeout and cleanup boundary before unattended
deployment; existing async timeout tests and the normal SIGTERM smoke do not prove it.

After inspecting logs, audit and slots, stop the worker and fix the reported problem
(for example, update the private key file or replenish API credits). If a CLAIMED
slot is confirmed interrupted, explicitly abandon its exact key before resuming:

```bash
./scripts/shadow-server.sh stop
# Only for a confirmed interrupted CLAIMED slot:
./scripts/shadow-server.sh abandon 'EXACT_SLOT_KEY_FROM_STATUS'
./scripts/shadow-server.sh resume
./scripts/shadow-server.sh start
./scripts/shadow-server.sh status
```

Abandonment records an operator event, preserves the slot as ABANDONED and prevents
replay. `resume` requires a halted service with no active claim and records an event;
the next startup rechecks local credentials. Maintenance refuses to change state
while the daemon holds its lifetime lock. An already attempted failed slot remains
skipped after resume; work waits for the next eligible slot.

## Backups and updates

```bash
./scripts/shadow-server.sh backup
```

This creates an integrity-checked, mode-600 SQLite snapshot under
`/var/lib/trade-bot/data/backups`. Copy selected backups off-host using private SSH
storage. Protect OAuth and key files separately; a database backup does not contain
the credential files. The one-time import refuses to overwrite an existing server DB.

For an application update, keep the same branch and persistent directories:

```bash
cd /opt/trade-bot
git pull --ff-only
./scripts/shadow-server.sh build
./scripts/shadow-server.sh backup
./scripts/shadow-server.sh stop
./scripts/shadow-server.sh start
./scripts/shadow-server.sh status
./scripts/shadow-server.sh logs
```

An existing HALTED state still requires investigation and explicit resume. Never run
an older image against an upgraded database without checking schema compatibility.

## Verification boundary

The offline suite covers service locks, heartbeat, graceful shutdown, timeouts,
persistent failure latching, explicit recovery, private credential reading, consistent
backups and migration bundles. The actual CLI has also been checked locally for
closed-session startup and SIGTERM using synthetic credentials, with no network calls.
Compose configuration is validated. This execution workspace has no Docker daemon or
live credentials, so image build, authenticated server probe, host restart and the
first regular-session model cycle remain target-host checks. Deployment is not complete
until those checks succeed on the confirmed droplet.
