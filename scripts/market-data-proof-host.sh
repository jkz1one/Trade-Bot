#!/usr/bin/env bash
# Three quote samples only; leaves dashboard and original SHADOW services alone.
set -euo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run on the Trade-Bot server as root.' >&2; exit 1; }
umask 077
proof_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$proof_root"
[[ -z "$(git status --porcelain)" ]] || { echo 'Clean release checkout required.' >&2; exit 1; }
proof_auth=/var/lib/trade-bot-read-auth
[[ -f "$proof_auth/robinhood-oauth.json" && -f "$proof_auth/discovery.json" ]]
# Reuse the already verified installed image. The helper runs from the read-only
# checkout and uses its unchanged capture/mapping interfaces; no rebuild needed.
proof_image=trade-bot-dashboard:acabf4a816ef5cc674fe36d687d29351d273e469
docker image inspect "$proof_image" >/dev/null
proof_output=$(mktemp -d /root/trade-bot-market-proof-XXXXXX)
echo "Evidence directory: $proof_output"
proof_status=0
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --mount "type=bind,src=$proof_auth,dst=/auth" \
  --mount "type=bind,src=$proof_auth/discovery.json,dst=/auth/discovery.json,readonly" \
  --mount "type=bind,src=$proof_root,dst=/review-source,readonly" \
  --mount "type=bind,src=$proof_output,dst=/out" \
  -e TRADER_LIVE_ENABLED=false "$proof_image" \
  python -I -W error /review-source/scripts/market-data-proof.py \
  --directory /out --schemas /auth/discovery.json \
  --oauth-file /auth/robinhood-oauth.json --run || proof_status=$?
printf 'Exit code: %s\nEvidence directory: %s\n' "$proof_status" "$proof_output"
if [[ -f "$proof_output/report.json" ]]; then
  echo 'Share report.json. Keep raw captures for inspection; do not share the auth directory.'
else
  echo 'No completed report. Preserve this directory and share the terminal error.' >&2
fi
exit "$proof_status"
