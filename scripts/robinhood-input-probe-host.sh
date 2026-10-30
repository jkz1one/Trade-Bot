#!/usr/bin/env bash
# Up to five pinned market-data calls; no account/order calls or owner mounts.
set -euo pipefail
[[ "$EUID" == 0 && "$#" == 0 ]] || { echo 'Usage (root): bash scripts/robinhood-input-probe-host.sh' >&2; exit 2; }
inventory_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$inventory_root"
[[ -z "$(git status --porcelain)" ]] || { echo 'Clean release checkout required.' >&2; exit 2; }
inventory_release=$(git rev-parse HEAD)
inventory_image="trade-bot-dashboard:$inventory_release"
docker image inspect "$inventory_image" >/dev/null
umask 077
inventory_output=$(mktemp -d /root/trade-bot-input-probe-XXXXXX)
echo "Evidence directory: $inventory_output"
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 1g --pids-limit 128 --tmpfs /tmp:size=128m,mode=1777 \
  -e TRADER_LIVE_ENABLED=false \
  --mount type=bind,src=/var/lib/trade-bot-read-auth,dst=/auth \
  --mount type=bind,src=/var/lib/trade-bot-read-auth/discovery.json,dst=/auth/discovery.json,readonly \
  --mount "type=bind,src=$inventory_output,dst=/out" \
  "$inventory_image" python -I -W error -m app.options.read_cli input-probe \
  --oauth-file /auth/robinhood-oauth.json --output /out/probe.json
echo "Evidence directory: $inventory_output"
