# Reviewed switch from frozen review to the native snapshot dashboard

The existing login and localhost port can now serve the display copy of the same
native virtual-money owner. The switch does not create an account, start a
collector/runtime/model worker, enable LIVE, configure trading inputs or change
Caddy. This is implemented and tested offline; it has not been run on the server.

## Prerequisites

The native root-owned owner and collector still need reviewed operational settings
and enrollment. The [snapshot publisher](DASHBOARD_SNAPSHOT.md) must already be
running against that owner using the same release image. The display directory is
`/var/lib/trade-bot-dashboard-publish/connected-v1`. Do not substitute the frozen
UI fixture, copy credentials or change native journal ownership.

The host helper expects the currently deployed dashboard image exactly:
`trade-bot-dashboard:a653cc7e79d178c5ab2de6afb3311829282a7544`, with the existing
private login, UID/GID 10001, read-only mounts and localhost 8790 listener. It also
checks that the two original SHADOW container identities/configurations remain
unchanged. A different host state requires inspection; no bypass flag is provided.

The current clean checkout's image must have been built by snapshot preparation.
The image's release marker, immutable Docker image ID and installed application
identity are checked. A one-shot reader runs as UID/GID 10001 with no network,
read-only mounts and no capabilities. It verifies the snapshot, native accounting,
reader ownership and existing password. This is also the outstanding cross-user
host acceptance gate that cannot run in the current ID-0-only development sandbox.

## Review and activation

Once those prerequisites have been completed, the server operator runs:

```bash
cd /opt/trade-bot-dashboard
python3 scripts/connected-dashboard-host.py review
```

Review prints a plan and `review_sha256`. It checks the existing authenticated
frozen page/API and the new reader before any dashboard container changes. The
plan binds the release/image, current container identity/configuration, snapshot
binding and untouched SHADOW identities. Snapshot publication time/revision can
advance without invalidating the plan, but each preflight still requires a fresh
copy. No trading credentials are mounted or read. Review acquires a private local
operation lock; that lock file is its only persistent host-side write.

After reviewing that concrete plan, activation takes its exact hash:

```text
python3 scripts/connected-dashboard-host.py activate --review-sha256 HASH_FROM_REVIEW
```

The helper repeats the complete review and freshness check before switching.
It retains the old container as `trade-bot-dashboard-before-connected-v1`, stops
that retained reader and starts the new reader under the original active name.
It pins the new process to the reviewed immutable image ID, mounts the snapshot
**directory** read-only and retains the existing password mount, user and
127.0.0.1:8790 listener. No trading credentials or operator key are mounted.

Startup acceptance checks anonymous denial, authenticated HTML/API, verified
native accounting, absence of frozen-review mode and disabled admin/LIVE/execution
authority. Polling is bounded and fails if the new reader stops, restarts or runs
out of memory. The original SHADOW identities must still match after the switch.
The URL and existing login remain unchanged; the helper does not assert that the
simulation is running or that market inputs are eligible.

## Failed starts and rollback

On a failed activation, the helper tries to restore the exact previous container
ID. An allocated failed reader is stopped and retained as
`trade-bot-dashboard-connected-failed-v1`, including its Docker logs. It is never
removed. A Docker error after a successful rename is handled by inspecting actual
container identities. An unrelated active container is never stopped or renamed.

If restoration itself fails or another actor changed the host, the helper exits
nonzero and requires inspection. Do not delete retained containers or repeatedly
rerun activation. Reserved-name collisions deliberately block retries. The helper
serializes its own operations with a private root-owned lock; it cannot prevent
an administrator or other software from changing Docker concurrently.

For an intentional rollback after successful activation:

```bash
python3 scripts/connected-dashboard-host.py review-rollback
```

Then use that review's exact hash:

```text
python3 scripts/connected-dashboard-host.py rollback --review-sha256 HASH_FROM_ROLLBACK_REVIEW
```

Rollback also works when the connected dashboard has stopped or the publisher
is stale. It does not require a fresh snapshot. It verifies the retained frozen
container and its linkage to the connected reader, stops and retains the connected
reader as `trade-bot-dashboard-connected-retired-v1`, restores the original ID and
checks the authenticated frozen view. The publisher/runtime keep their independent
state; rollback of the display does not stop simulated trading.

## Freshness and authority

The new reader has no write/operator routes. It requires a matching snapshot
receipt, native configuration/population and original checkpoint. Each authenticated
request rechecks that copy. A missing, altered, future-dated or more-than-30-second-old
publication returns HTTP 503 instead of serving it as a current response. Anonymous
requests still receive 401. The generic `/healthz` remains process health only;
activation acceptance uses authenticated data, not that endpoint alone.

A fresh publication does not make underlying quotes fresh, establish entitlement
or clear native entry blockers. Original quote timestamps and native stale/unknown
states remain visible. Publication failure preserves the last complete file on
disk, but serving it is still subject to the 30-second freshness gate. The
existing UI polling behavior and per-play selection are unchanged.

## Validation and remaining work

`CONNECTED_DASHBOARD_HOST_PROOF.json` records installed-wheel tests. Native reader
tests cover zero/two plays, authentication, immutable accounting, per-request
freshness/corruption refusal, recovery and absent operator routes. A stateful offline
Docker harness executes the actual host coordinator's review/switch/rollback logic,
including late rename failures, retained failed starts, mismatched isolation,
concurrent-operation exclusion and changed review hashes. These are not actual
Docker, cross-user, browser or server acceptance tests.

The [first-owner and coordinated-publisher interface](CONNECTED_FIRST_OWNER.md) is
now implemented, including the [reviewed host launcher](CONNECTED_HOST_RUNBOOK.md).
Concrete reviewed host inputs and actual host acceptance still remain. Eligible catalyst/Scope inputs, complete contract
and data eligibility, operator-command transport and connected market acceptance
also remain. The server is unchanged on frozen a653cc7; no connected simulation
was started. This publication ends a coding slice, not a missing-feed stop.
