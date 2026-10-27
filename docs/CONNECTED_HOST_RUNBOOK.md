# Connected simulation host runbook

The host launcher is implemented. Its native offline integration test packages
configuration, enrolls one owner/collector, publishes a snapshot, consumes captured
feed packets, serves authenticated current dashboard data, shuts down and restarts
the same account. Existing two-held-play restart tests run alongside it.

This is not a deployment receipt. The server is still on frozen a653cc7, and no
connected worker has been started there. Actual Docker, UID/GID 10001, login,
latency and current-feed acceptance must run on the host.

## Required inputs, with no hidden policy defaults

The launcher accepts a complete native `RuntimeSettings` JSON and `FeedPolicy`
JSON. These must be reviewed operational inputs for the intended population,
capital, strategies, risk/cost limits and candidate catalog. No concrete production
settings for the user's complete strategy selection have been supplied or approved
in this slice. The stored UI fixture is not a deployment configuration; the helper
rejects its `ui-review-` identity. Tests use synthetic policies and are not approvals
of those policies for the server.

Packaging changes only the deployment paths: feed delivery, broker OAuth path,
and optional model/operator secret mount paths. It preserves every other setting,
including family selection, capital, costs, risk, contract metadata, entitlement
and carry intent. Missing strategies are not silently added; existing strategies
are not silently removed. No test credentials, prices, stock sizes, contracts or
catalyst CLEAR flags are copied into production configuration. The review prints
capital, play limit, families, configured model/operator flags and entry blockers.

Existing server inputs:

- Broker read auth directory: `/var/lib/trade-bot-read-auth`.
- Exported schemas: `discovery.json` within that directory.
- OAuth file: `robinhood-oauth.json` within that directory.
- Optional model/operator keys: existing paths explicitly named in the supplied
  runtime settings. They must be private root-owned files for the native root
  owner. The helper does not create, move, copy, print or change their permissions.

Source JSON must be canonical absolute root-owned 0600 files. Prepared state and
parent directories are private root-owned 0700. Do not share auth files.

## Fixed layout

| Host path | Container path | Purpose |
|---|---|---|
| `/var/lib/trade-bot-connected` | `/state` | One native owner, collector and frozen config |
| `/var/lib/trade-bot-connected/owner` | `/source` | Same owner's journal alias for existing publisher binding |
| `/var/lib/trade-bot-connected/config` | `/state/config` | Read-only configuration, including during a run |
| `/var/lib/trade-bot-dashboard-publish` | `/exports` | Existing dashboard publisher layout |
| `/var/lib/trade-bot-read-auth` | `/auth` | Existing read-only broker capability; token refresh/read leases need directory writes |
| Explicit existing key file | `/run/secrets/model` or `/run/secrets/operator` | Optional read-only native key mount |

The `/source` alias points at the same owner directory under `/state`; it is not
a copied ledger. The collector's delivery path is `/state/collector/feed.json`.
The snapshot destination is `/exports/connected-v1`, matching the dashboard switch.
Discovery is mounted read-only inside the writable OAuth directory. No broker
order capability is introduced; the gateway retains its six fixed market-read tools.

## Offline preparation on the host

Use the clean pinned feature checkout under `/opt/trade-bot-dashboard`. Building
may download the existing image/dependencies; it makes no market/model calls.

```bash
cd /opt/trade-bot-dashboard
python3 scripts/connected-session-host.py build
python3 scripts/connected-session-host.py review-config \
  --settings ABSOLUTE_REVIEWED_RUNTIME_JSON --policy ABSOLUTE_REVIEWED_FEED_JSON
```

Review prints the configuration hash. After inspecting those supplied settings,
pass its exact hash to create the frozen bundle:

```text
python3 scripts/connected-session-host.py prepare \
  --settings ABSOLUTE_REVIEWED_RUNTIME_JSON --policy ABSOLUTE_REVIEWED_FEED_JSON \
  --expected-review CONFIG_REVIEW_SHA256
python3 scripts/connected-session-host.py review-enroll
python3 scripts/connected-session-host.py enroll --expected-review ENROLL_REVIEW_SHA256
```

Each action is separate from its review; never substitute a guessed hash. The
native enrollment review and host review use different hashes; the launcher
passes the correct native hash internally. Enrollment creates the native owner,
collector and first dashboard copy. It never starts runtime, provider or model
workers. Config/preflight/enrollment containers have no network and no OAuth mount.
Optional configured model/operator files are mounted only for native enrollment
validation, not read-only review. Source JSON is never modified.

Existing state or a changed hash blocks creation. If native enrollment succeeds
but snapshot creation fails, retain everything and inspect the failure. The
explicit `snapshot` operation can create the still-absent first snapshot from the
existing owner; it cannot overwrite or repair an existing failed destination.
Never reenroll to reset a partially created account or delivery history.

## First bounded connected session

Once enrollment and cross-user snapshot creation succeed, review a short session:

```bash
python3 scripts/connected-session-host.py review-run --run-id first-check --seconds 600
```

Inspect its exact configuration/entry blockers, then start that reviewed session:

```text
python3 scripts/connected-session-host.py run \
  --run-id first-check --seconds 600 --expected-review RUN_REVIEW_SHA256
```

**This is the first operation that mounts broker OAuth and permits network reads.**
It can also invoke native model workers if the supplied configuration explicitly
enrolled them; model flags and budgets must be reviewed. Execution remains the
local virtual-money venue and LIVE remains disabled. Unknown eligibility continues
to block entries. A started container is not proof of ongoing health or trades.

The container is detached so terminal disconnect does not end the test. It has
no exposed ports, no restart policy and an explicit 1..86400-second duration.
There is no scheduled or automatic restart after a crash or server reboot. The
native runtime, collector and publisher share graceful shutdown. The launcher
checks that the original SHADOW identities remain unchanged and never starts,
stops or renames those services or the dashboard.

While the bounded session is running and snapshots are current, use the separate
[dashboard review/activation](CONNECTED_DASHBOARD_HOST.md) to switch the existing
login/URL. That helper retains the frozen dashboard for rollback. Switching the
display does not start a runtime, and display rollback does not stop this session.

## Status, stop and restart

```bash
python3 scripts/connected-session-host.py status --run-id first-check
```

To stop early, pass the exact container ID returned by status:

```text
python3 scripts/connected-session-host.py stop \
  --run-id first-check --expected-container EXACT_CONTAINER_ID
```

Stop sends native termination with a 45-second Docker allowance. It does not
remove the container, logs or state. Status/stop do not require a release image
or configuration to still be available. Each completed attempt retains its name;
use a new run ID for a new reviewed session against the same owner. A currently
running labeled session blocks a second launch, and native leases independently
fence duplicate workers. Restart does not automatically clear entry halts.

For diagnosis, inspect the retained named container's exit state and bounded logs.
Do not delete failed evidence or create a new owner to recover. Native operator
commands retain their existing guards; dashboard operator-command transport is
still separate unfinished work.

## Acceptance boundary

`CONNECTED_HOST_LAUNCH_PROOF.json` records offline installed-wheel evidence. The
host coordinator is exercised against a stateful Docker recorder. Native pipeline
integration uses real journals, collector normalization, runtime consumption,
publication and authenticated ASGI reads with synthetic capture, never the broker.
The cross-user publisher test remains skipped because this workspace maps only UID 0.

The requested preparation/launch block is implemented. Next are reviewed real
configuration/catalog inputs and host acceptance, not another missing launcher.
Fresh stock/option quote capture was already demonstrated on October 26; it does
not need repeating to prove that earlier fact. New connected acceptance needs a
current feed. Full contract terms, entitlement, executable stock sizes and eligible
catalyst/Scope sources remain unresolved. No successful simulated entry is promised
until its native eligibility gates pass. Operator transport and other broader
strategy/data work are not declared complete by this runbook.
