# Persistent SHADOW worker on a Linux droplet

The server runs the OpenAI SHADOW scheduler independently of the Mac or SSH session.
The application remains Robinhood READ plus approved order review only. LIVE and
broker placements/cancellations remain disabled. A separate private observer reads
stored history through a localhost-only port. SignalFlow's services are unchanged.

## Layout and requirements

Use a separate checkout at `/opt/trade-bot`, Compose project `trade-bot-shadow`, and
these persistent host paths:

| Path | Contents |
| --- | --- |
| `/var/lib/trade-bot/data` | SQLite history, schedule claims, service state, backups |
| `/var/lib/trade-bot/oauth` | Robinhood OAuth client/tokens, writable for refresh |
| `/etc/trade-bot/openai_api_key` | Private OpenAI key file |
| `/etc/trade-bot/dashboard_password` | Independent observer password |

Directories are mode 700 and credential/data files mode 600, owned by container
UID/GID 10001. The non-root container has a read-only application filesystem, a
temporary `/tmp`, rotated logs, and a 512 MiB worker memory limit. The observer has
a separate 256 MiB limit, read-only data mount, and no API key or OAuth mount. The host needs Docker
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

`start` launches the worker and observer detached. Check `status` after the first heartbeat; during a closed
session logs should show MARKET_CLOSED without broker/model calls. Ensure the host's
Docker daemon starts at boot. Once startup and restart are verified, closing SSH or
shutting down the Mac does not stop the worker. Keep the private transfer bundle only
as long as needed for migration verification; manage its deletion separately.

## Private dashboard

`prepare` generates a 64-character random observer password in its own mode-600
file without printing it or replacing an existing password/key. If updating an
existing server, run `prepare` once before building the observer release.

On the Mac, forward the server's localhost-only observer port:

```bash
ssh -N -L 127.0.0.1:8787:127.0.0.1:8787 root@DROPLET_IP
```

Open `http://127.0.0.1:8787` in your browser. The username is `trader`. Read the
password only in your private SSH terminal with `sudo cat /etc/trade-bot/dashboard_password`;
do not paste it into chat. Replace the SSH user/address with the confirmed host's
existing access. Closing the tunnel stops browser access; the worker continues.
There is no public HTTP port or domain configuration. Do not expose this Basic-auth
HTTP endpoint publicly; the supported transport is encrypted SSH forwarding.

The observer is a separate `app.web.shadow:create_shadow_app` FastAPI factory. It
requires SHADOW mode, LIVE disabled and a password file of at least 24 characters.
Routes are authenticated `GET /` and `GET /api/shadow`, plus public process-only
`GET /healthz` on the same private listener. API documentation and all mutation
routes are absent. Responses prohibit caching/framing and load no external scripts,
fonts or assets. Model text is escaped. Access logging is disabled.

The app opens the SQLite file with `mode=ro` and `query_only=ON`, never initializes
or repairs it, and reads each report inside one committed transaction. It does not
import a broker adapter or model client. Missing history shows a waiting state;
an incomplete/unreadable schema returns a sanitized unavailable state. A corrupt
record cannot silently become a trading result. Password errors fail closed.
The observer's ready health endpoint does not assert worker/data/model health.

Views show heartbeat/release/halt and active slot, latest saved account/position and
its age, proposal/risk/reconciliation, review completion, prompt/model/usage, paged
decision history, and 15/60-minute quote outcomes versus SPY. The full latest snapshot
stays visible when browsing older history. Pages are bounded to 100 decisions, with
matching source outcome cohorts. The first page refreshes every 30 seconds; pause
refresh for inspection, and older pages never automatically refresh.
Raw broker review/account identifiers, working orders, claim-owner tokens and
credential paths are omitted. There are no start, trade, halt or resume controls.
Usage gaps are unknown and quote marks remain separate from portfolio P&L.

To inspect a halted worker without starting it:

```bash
./scripts/shadow-server.sh observer
./scripts/shadow-server.sh observer-logs
```

`observer` starts/recreates only the observer with no worker dependency. `stop` stops both
services; `authorize` stops only the worker so inspection can continue. Rotate the
password by updating the private host file, preserving owner/mode, then run
`./scripts/shadow-server.sh observer` so its bind-mounted secret reads the new file. It rereads the mounted
password on each request. Browser Basic-auth caching may require a new private window.

For a local development check, point the observer explicitly at the SHADOW database
and a private password file, without changing the PAPER default:

```bash
TRADER_MODE=SHADOW TRADER_LIVE_ENABLED=false \
TRADER_ROBINHOOD_DB_URL=sqlite:///./robinhood.db \
TRADER_DASHBOARD_PASSWORD_FILE=/path/to/private/dashboard_password \
uvicorn app.web.shadow:create_shadow_app --factory --host 127.0.0.1 --port 8787 --no-access-log
```

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
OpenAI billing, remote authentication, or trading signal quality. The observer shows
saved status only; there is no external alerting.

Docker restarts an unexpectedly exited container. An application failure instead
latches HALTED in SQLite and keeps an idle worker with an unhealthy check. A restart
does not clear that halt or repeatedly spend credits retrying a failed slot. Missing
credentials, model/review failures, calendar errors, interrupted claims and a
600-second cycle timeout all stop further scheduled attempts.

SIGTERM stops new cycles and allows the active cycle to drain; Docker allows 660
seconds before termination. A hard interruption can leave a CLAIMED slot. It blocks
new work across restarts and is never automatically replayed or expired.

The synchronous-model-thread gap identified in the
[SignalFlow review](SIGNALFLOW_REUSE_ASSESSMENT.md) is fixed for OpenAI SHADOW cycles.
Each decision runs in a separate process with no broker/database handles or model tools.
The request timeout is 60 seconds, SDK retries are zero, and the entire model-process
deadline is 120 seconds including startup. Timeout/cancellation sends SIGTERM to that
child's process group, then SIGKILL after at most two seconds of graceful termination,
and reaps it before returning. The parent has no synchronous model executor to drain.
The outer 600-second cycle deadline also invokes this cleanup.

A model deadline becomes fail-closed HOLD with `agent_error: ModelProcessTimeout`,
no review, exit 8 and a durable service halt. An outer cycle cancellation preserves
the interrupted claim and halts; it never creates a completed cycle or replays work.
SDK tracing is disabled in the child; persisted application evidence remains the audit.
Child diagnostic output is discarded; only validated decision/usage/error-class JSON
crosses the process boundary.

Local process termination closes the client connection; it cannot guarantee that an
already accepted remote API request stops computing or is unbilled. A terminated/failed
call without returned usage remains unknown, not zero-cost evidence. Compare API billing
when accounting for such failures. This subprocess path has offline failure-injection
coverage but still requires authenticated model verification on the target host.

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
./scripts/shadow-server.sh prepare
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

The observer adds authenticated read-only coverage for missing/corrupt/legacy history,
password rotation/failure, escaping/secret projection, bounded pagination/cohort
linkage, stale/future/halted heartbeats and writes rejected by its SQLite connection.
Tests prove one snapshot even when a WAL writer commits during a report, and progress
with concurrent default-journal worker writes and two readers. Password preparation
is tested using temporary paths and mapped test ownership; actual container UID/file
permissions remain a host check. The package wheel includes both web templates.
Actual local Uvicorn startup, authenticated HTML/JSON, denied unauthenticated
history, unchanged database and graceful shutdown are verified with synthetic
stored evidence and no remote API calls.
The updated Compose manifest is checked against the official Compose JSON Schema and
its private mounts/port/secret boundaries. Docker image startup and a visual browser
review remain unverified here: this workspace has no Docker daemon/browser binary,
and browser installation returned a non-archive download. Verify desktop/mobile
rendering through the private tunnel on the target host before considering deployment
complete.
