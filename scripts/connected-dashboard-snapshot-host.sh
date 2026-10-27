#!/usr/bin/env bash
# Publish a stored dashboard mirror only. No credentials, runtime or port changes.
set -euo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run on the Trade-Bot server as root.' >&2; exit 1; }
snapshot_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$snapshot_root"
snapshot_action="${1:-}"
snapshot_owner="${2:-}"
snapshot_seconds="${3:-}"
case "$snapshot_action" in
  prepare|publish|check) [[ -z "$snapshot_seconds" ]] || exit 2 ;;
  run) [[ "$snapshot_seconds" =~ ^[1-9][0-9]{0,4}$ ]] && ((snapshot_seconds <= 86400)) || exit 2 ;;
  *) echo 'Usage: connected-dashboard-snapshot-host.sh prepare|publish|check|run /absolute/existing-owner [run-seconds]' >&2; exit 2 ;;
esac
[[ "$snapshot_owner" == /* && "$snapshot_owner" != *','* && "$snapshot_owner" != *$'\n'* ]]
[[ -d "$snapshot_owner" && ! -L "$snapshot_owner" && "$(realpath -- "$snapshot_owner")" == "$snapshot_owner" ]]
[[ "$(stat -c '%u:%g:%a' "$snapshot_owner")" == 0:0:700 ]]
[[ -f "$snapshot_owner/options.db" && -f "$snapshot_owner/runtime.json" && -f "$snapshot_owner/venue.db" ]]
[[ -z "$(git status --porcelain)" ]] || { echo 'Clean release checkout required.' >&2; exit 1; }
snapshot_release="$(git rev-parse HEAD)"
snapshot_image="trade-bot-dashboard:$snapshot_release"
snapshot_parent=/var/lib/trade-bot-dashboard-publish
snapshot_name=connected-v1
if [[ "$snapshot_action" == prepare ]]; then
  [[ ! -e "$snapshot_parent/$snapshot_name" && ! -L "$snapshot_parent/$snapshot_name" ]] || {
    echo 'Snapshot destination exists. Preserve it; do not rerun preparation.' >&2; exit 1;
  }
  if [[ ! -e "$snapshot_parent" ]]; then
    mkdir -m 700 -- "$snapshot_parent"
  fi
  [[ -d "$snapshot_parent" && ! -L "$snapshot_parent" && "$(stat -c '%u:%g:%a' "$snapshot_parent")" == 0:0:700 ]]
  docker build -f Dockerfile.shadow --build-arg "TRADE_BOT_RELEASE=$snapshot_release" -t "$snapshot_image" .
  snapshot_operation=create
else
  [[ -d "$snapshot_parent" && ! -L "$snapshot_parent" && "$(stat -c '%u:%g:%a' "$snapshot_parent")" == 0:0:700 ]]
  [[ -d "$snapshot_parent/$snapshot_name" && ! -L "$snapshot_parent/$snapshot_name" ]]
  docker image inspect "$snapshot_image" >/dev/null
  snapshot_operation="$snapshot_action"
fi
snapshot_args=()
[[ "$snapshot_action" != run ]] || snapshot_args=(--seconds "$snapshot_seconds" --interval 5)
snapshot_mount="type=bind,src=$snapshot_parent,dst=/exports"
[[ "$snapshot_action" != check ]] || snapshot_mount+=,readonly
# CHOWN applies only to the new mirror. DAC_READ_SEARCH lets this root publisher
# validate its prior 0600 mirror owned by reader 10001. No password/auth is mounted.
docker run --rm --network none --init --read-only --user 0:0 \
  --cap-drop ALL --cap-add CHOWN --cap-add DAC_READ_SEARCH \
  --security-opt no-new-privileges:true --memory 512m --cpus 0.5 --pids-limit 32 \
  --tmpfs /tmp:size=32m,mode=1777 \
  --mount "type=bind,src=$snapshot_owner,dst=/source,readonly" \
  --mount "$snapshot_mount" \
  -e TRADER_LIVE_ENABLED=false "$snapshot_image" \
  python -I -W error -m app.mixed.dashboard_snapshot "$snapshot_operation" \
  --owner /source --destination "/exports/$snapshot_name" \
  --reader-uid 10001 --reader-gid 10001 "${snapshot_args[@]}"
echo 'Snapshot operation finished. Existing dashboard, runtime and SHADOW services were not changed.'
