#!/usr/bin/env bash
# Bounded context, exact-strike contracts and three quote samples; no owner mounts.
set -euo pipefail
[[ "$EUID" == 0 && "$#" == 1 ]] || { echo 'Usage (root): bash scripts/paper-contract-capture-host.sh YYYY-MM-DD' >&2; exit 2; }
capture_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$capture_root"
[[ -z "$(git status --porcelain)" ]] || { echo 'Clean release checkout required.' >&2; exit 2; }
capture_release=$(git rev-parse HEAD)
capture_image="trade-bot-dashboard:$capture_release"
docker image inspect "$capture_image" >/dev/null
umask 077
capture_output=$(mktemp -d /root/trade-bot-options-proof-XXXXXX)
echo "Evidence directory: $capture_output"
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 1g --pids-limit 128 --tmpfs /tmp:size=128m,mode=1777 \
  -e TRADER_LIVE_ENABLED=false \
  --mount type=bind,src=/var/lib/trade-bot-read-auth,dst=/auth \
  --mount type=bind,src=/var/lib/trade-bot-read-auth/discovery.json,dst=/auth/discovery.json,readonly \
  --mount "type=bind,src=$capture_output,dst=/out" \
  "$capture_image" python -I -W error -m app.mixed.session_capture \
  --target-session "$1" --directory /out --schemas /auth/discovery.json \
  --oauth-file /auth/robinhood-oauth.json
echo "Evidence directory: $capture_output"
