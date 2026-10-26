#!/usr/bin/env bash
# Sourced by the dashboard helper. Does not create, stop or remove containers.
wait_for_dashboard() {
  local container_name="$1" health_url="$2"
  local attempt state body deadline=$((SECONDS + 90))
  for ((attempt=1; attempt<=45 && SECONDS<deadline; attempt++)); do
    state="$(docker inspect --format '{{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}}' "$container_name")" || return 1
    if [[ "$state" != 'true false 0' ]]; then
      echo "Dashboard stopped, restarted or ran out of memory: $state" >&2
      return 1
    fi
    if body="$(curl -fsS --connect-timeout 1 --max-time 2 "$health_url" 2>/dev/null)"; then
      printf '%s\n' "$body"
      return 0
    fi
    sleep 2
  done
  echo 'Dashboard did not become ready within the 90-second startup window.' >&2
  return 1
}

preserve_dashboard_failure() {
  local container_name="$1" diagnostic_dir
  diagnostic_dir="$(umask 077; mktemp -d /root/trade-bot-dashboard-failure-XXXXXX)" || return 1
  docker inspect --format 'status={{.State.Status}} running={{.State.Running}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}} restarts={{.RestartCount}}' \
    "$container_name" > "$diagnostic_dir/state.txt" 2>&1 || true
  docker logs --tail 200 "$container_name" > "$diagnostic_dir/startup.log" 2>&1 || true
  echo "Startup diagnostics preserved: $diagnostic_dir" >&2
  cat "$diagnostic_dir/state.txt" >&2
}
