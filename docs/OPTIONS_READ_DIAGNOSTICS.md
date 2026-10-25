# Read authorization blocker

**Resolved for the observed capture:** the operator reported login exit 0, then
supplied successful headless schema discovery and four completed market reads.
[Current sample acceptance and next step](ROBINHOOD_SAMPLE_ACCEPTANCE.md). Keep
these prior failures; do not rerun the login/diagnostic commands below automatically.

## Schema-only diagnostic result

The operator supplied diagnostic `81dcba97bca8427c8cce5b555dfe1020`, exit 1,
collected October 24 at 23:46:22 EDT. Its failure phase is `CONNECT`, with
`ExceptionGroup → ReadAuthorizationRequired` plus cancellation/stream context
(`CancelledError`, `WouldBlock`). There are no schemas or market observations.
The installed reader raises this named exception only from the interactive
authorization handlers: establishing the connection requested operator login,
which the headless path intentionally refused. The result does not retain an HTTP
status or OAuth error code and does not prove expired/revoked tokens or the reason
reauthorization was requested. Nor does it retroactively prove the original
undifferentiated failure had the same cause. [Retained artifact hashes and receipt](OPTIONS_READ_AUTH_REQUIRED_PROOF.json).

Do not repeat the headless diagnostic or four-read batch until authorization has
been restored. No engine/dependency change, deadline increase or guard bypass is
needed for this observed blocker. The existing interactive discovery CLI can
restore the separate credential and call `list_tools` only. It never invokes
market, account, broker order or model tools in this command. The human login
wait is separate from the unchanged 30-second headless capture budget.

## Operator login and schema discovery

Run this in the host terminal. It reuses the already-built diagnostic image; no
fetch, rebuild or dashboard refresh is necessary. A new private output directory
preserves the previous credential locally before login. The existing validated
OAuth lease excludes concurrent captures. The old discovery is mounted read-only;
prior attempts, frozen SHADOW services and UI fixture databases remain untouched.

Open the printed Robinhood authorization URL in your own browser and complete
login/approval. If the final localhost callback page cannot load, copy its full
address from the browser address bar into the waiting **server terminal** prompt.
Do not paste it into chat. The local callback is parsed for code/state; this flow
does not require publishing a callback port. Keep the authorization URL, callback
URL and both credential files private. Share only the final schema-count summary
and exit code. Do not upload the login directory.

```bash
bash <<'BASH'
set -euo pipefail
umask 077
login_dir=$(mktemp -d /root/trade-bot-read-login-XXXXXX)
login_status=0
docker run --rm -it --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --env TRADER_LIVE_ENABLED=false \
  --env TRADER_ROBINHOOD_INTERACTIVE_AUTH=true \
  --env TRADER_ROBINHOOD_OAUTH_STORAGE=/auth/robinhood-oauth.json \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz,dst=/auth \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz/discovery.json,dst=/auth/discovery.json,readonly \
  --mount "type=bind,src=$login_dir,dst=/out" \
  trade-bot-read-diagnostic:30e4eba7591b0c6741a9495ad92b9fdc21fd8fd3 \
  python -I -W error -c '
import os, runpy
from pathlib import Path
from app.execution.market_reads import market_read_lease, private_oauth
os.umask(0o077)
with market_read_lease("/auth/robinhood-oauth.json"):
    private_oauth("/auth/robinhood-oauth.json")
    with Path("/out/oauth-before.json").open("xb") as backup:
        backup.write(Path("/auth/robinhood-oauth.json").read_bytes())
    runpy.run_module("app.robinhood.cli", run_name="__main__")
' discover --output /out/login-schemas.json \
  --required-output /out/login-required-schemas.json \
  </dev/tty || login_status=$?
printf '%s\n' "$login_status" > "$login_dir/exit-code"
printf 'Exit code: %s\nLogin directory: %s\n' "$login_status" "$login_dir"
exit "$login_status"
BASH
```

After successful interactive discovery, verify the fixed options reader can
complete one headless schema-only discovery and compare its schema digest before
resuming the already-authorized market batch. Success here is not connected PAPER
acceptance. Authentication recovery, actual market samples, missing quote sizes /
contract terms / entitlement, feed integration and host acceptance remain open.

## Retained first capture failure

The user authorized the prepared one-time SPY/QQQ read capture and supplied its
exit code, plan, summary and sample artifact. Capture
`7318468dc2a74b61b90e64b6ced61234` returned exit 1. The retained plan hash exactly
matches the reviewed four-read plan. The result has no schemas and no observations,
reports `ExceptionGroup`, and records 1.223 seconds in the child. Therefore no
market-read tool was reached; schema discovery did not complete. Connection/session
initialization or discovery may have been attempted. The missing nested exception
prevents identifying authorization, transport, protocol or provider failure.
This is not evidence that OAuth expired or that the 30-second budget was exhausted.
The supplied artifacts remain unchanged and are represented only by hashes and
sanitized metadata in [proof](OPTIONS_READ_DIAGNOSTICS_PROOF.json).

The capture worker now retains its failure phase and a bounded exception tree:
up to 16 class names and depth four, with a truncation flag. For typed HTTP failures,
it retains the numeric status and, when present in a bounded JSON body, one of nine
standard allowlisted OAuth error codes. It never serializes exception messages,
URLs, headers, descriptions, response bodies or credentials. Cause/context cycles
are bounded. An attempted interactive login gets the distinct
`ReadAuthorizationRequired` class and remains blocked. Existing authentication,
refresh, capture timeout, child cleanup and read capabilities are unchanged.
No auto-retry is added. Legacy capture artifacts remain readable with the optional
diagnostics absent. The CLI emits the same safe diagnostics in its private artifact
and console summary, including parent-side failures.

## Prior schema-only diagnostic (already run; retained for reference)

The following schema-only diagnostic has now been run and produced the result above.
Do not blindly repeat it. Its original scope was one discovery, not another market batch.
The operator runs the command after fetching/checking out this published revision.
It builds an isolated diagnostic image, uses the existing separately managed
authorization and normal refresh lock, writes a new private output, and exits.
The original discovery artifact is mounted read-only. Failed capture artifacts,
v1/v2 data, dashboard containers and the frozen SHADOW deployment are untouched.
No trader, collector service, model worker or market-read tool starts. Normal OAuth
discovery/refresh may occur while establishing the authorized connection.

```bash
bash <<'BASH'
set -euo pipefail
umask 077
cd /opt/trade-bot-dashboard
test -z "$(git status --porcelain)"
diagnostic_sha=$(git rev-parse HEAD)
docker build -f Dockerfile.shadow --build-arg "TRADE_BOT_RELEASE=$diagnostic_sha" \
  -t "trade-bot-read-diagnostic:$diagnostic_sha" .
diagnostic_dir=$(mktemp -d /root/trade-bot-read-diagnostic-XXXXXX)
diagnostic_status=0
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz,dst=/auth \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz/discovery.json,dst=/auth/discovery.json,readonly \
  --mount "type=bind,src=$diagnostic_dir,dst=/out" \
  "trade-bot-read-diagnostic:$diagnostic_sha" \
  python -I -W error -m app.options.read_cli discover \
  --oauth-file /auth/robinhood-oauth.json \
  --output /out/discovery.json --timeout-seconds 30 \
  > "$diagnostic_dir/summary.json" 2> "$diagnostic_dir/stderr.log" || diagnostic_status=$?
printf '%s\n' "$diagnostic_status" > "$diagnostic_dir/exit-code"
cat "$diagnostic_dir/summary.json"
printf 'Exit code: %s\nDiagnostic directory: %s\n' "$diagnostic_status" "$diagnostic_dir"
exit "$diagnostic_status"
BASH
```

Do not retry automatically. Inspect the diagnostic summary first. Success establishes
only schema discovery, not market-response mapping or connected PAPER readiness.
No authenticated call was executed from this workspace during the correction.
Installed tests cover nested groups, HTTP/OAuth code filtering, secret-bearing
messages/URLs/bodies, depth/count/cycles, worker phases, a real native child,
headless-login refusal, CLI serialization and old-artifact compatibility.
