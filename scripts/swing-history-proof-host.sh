#!/usr/bin/env bash
# One read-only history proof; never starts or mutates the connected account.
set -euo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run on the Trade-Bot host as root.' >&2; exit 1; }
umask 077
proof_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$proof_root"
[[ -z "$(git status --porcelain)" ]] || { echo 'Clean checkout required.' >&2; exit 1; }
# Reuse the installed, host-verified mapper; no image rebuild or deployment.
proof_image=sha256:93b8afad31101507a491df4efefb42322e1b1f019e41a242f0edd4f0cdf1e307
proof_auth=/var/lib/trade-bot-read-auth
proof_policy=/var/lib/trade-bot-connected/config/policy.json
[[ -f "$proof_policy" && -f "$proof_auth/discovery.json" && -f "$proof_auth/robinhood-oauth.json" ]]
docker image inspect "$proof_image" >/dev/null
proof_output=$(mktemp -d /root/trade-bot-swing-history-XXXXXX)
echo "Evidence directory: $proof_output"
proof_status=0
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --mount "type=bind,src=$proof_auth,dst=/auth" \
  --mount "type=bind,src=$proof_auth/discovery.json,dst=/auth/discovery.json,readonly" \
  --mount "type=bind,src=$proof_policy,dst=/input/policy.json,readonly" \
  --mount "type=bind,src=$proof_root/scripts,dst=/scripts,readonly" \
  --mount "type=bind,src=$proof_output,dst=/out" \
  -e TRADER_LIVE_ENABLED=false "$proof_image" \
  python -I -W error /scripts/swing-history-proof.py \
  --directory /out --policy /input/policy.json --schemas /auth/discovery.json \
  --oauth-file /auth/robinhood-oauth.json --run || proof_status=$?
printf 'Exit code: %s\nEvidence directory: %s\n' "$proof_status" "$proof_output"
echo 'Share report.json; preserve capture.json. Do not share auth files.'
exit "$proof_status"
