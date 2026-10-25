# Retained first capture failure

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

## Next operator diagnostic

Inspect with one schema-only discovery, not another four-market-read capture.
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
