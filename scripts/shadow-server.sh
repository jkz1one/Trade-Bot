#!/usr/bin/env bash
set -euo pipefail
trade_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$trade_root"
action="${1:-status}"

if [[ "$action" == prepare ]]; then
  [[ "$EUID" == 0 ]] || { echo 'Run prepare as root on the target server.' >&2; exit 1; }
  install -d -m 700 -o 10001 -g 10001 /var/lib/trade-bot/data /var/lib/trade-bot/oauth /etc/trade-bot
  install -d -m 700 /root/trade-bot-bootstrap
  if [[ ! -e /etc/trade-bot/openai_api_key ]]; then
    install -m 600 -o 10001 -g 10001 /dev/null /etc/trade-bot/openai_api_key
  fi
  if [[ ! -e /etc/trade-bot/dashboard_password ]]; then
    (umask 077; od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > /etc/trade-bot/dashboard_password)
    chown 10001:10001 /etc/trade-bot/dashboard_password
    chmod 600 /etc/trade-bot/dashboard_password
  fi
  if [[ ! -e /etc/trade-bot/worker.env ]]; then
    (umask 077; printf 'TRADE_BOT_EXPERIMENT_ID=\n' > /etc/trade-bot/worker.env)
  fi
  echo 'Private Trade-Bot directories prepared. Credentials must be imported before startup.'
  exit 0
fi

if [[ "$action" == import ]]; then
  [[ "$EUID" == 0 ]] || { echo 'Run import as root on the target server.' >&2; exit 1; }
  bundle="${2:?Pass the private bootstrap directory}"
  [[ ! -e /var/lib/trade-bot/data/robinhood.db ]] || { echo 'Existing server database will not be overwritten.' >&2; exit 1; }
  for file in robinhood.db robinhood-oauth.json openai_api_key; do
    [[ -f "$bundle/$file" ]] || { echo "Missing bootstrap file: $file" >&2; exit 1; }
  done
  install -m 600 -o 10001 -g 10001 "$bundle/robinhood.db" /var/lib/trade-bot/data/robinhood.db
  install -m 600 -o 10001 -g 10001 "$bundle/robinhood-oauth.json" /var/lib/trade-bot/oauth/robinhood-oauth.json
  install -m 600 -o 10001 -g 10001 "$bundle/openai_api_key" /etc/trade-bot/openai_api_key
  echo 'Private bootstrap imported. Run preflight and the safe probe before startup.'
  exit 0
fi

command -v docker >/dev/null || { echo 'Docker Engine with Compose is required on the server.' >&2; exit 1; }
export TRADE_BOT_RELEASE="$(git rev-parse --verify HEAD)"
compose=(docker compose -p trade-bot-shadow -f "$trade_root/compose.shadow.yml")
if [[ -f /etc/trade-bot/worker.env ]]; then
  compose+=(--env-file /etc/trade-bot/worker.env)
fi
case "$action" in
  build)
    [[ -z "$(git status --porcelain)" ]] || { echo 'Build requires a clean checkout.' >&2; exit 1; }
    "${compose[@]}" config --quiet
    "${compose[@]}" build shadow
    ;;
  preflight) "${compose[@]}" run --rm --no-deps shadow python -m app.robinhood.cli shadow-preflight ;;
  probe) "${compose[@]}" run --rm --no-deps shadow python -m app.robinhood.cli probe ;;
  authorize)
    "${compose[@]}" stop shadow
    "${compose[@]}" run --rm --no-deps -e TRADER_ROBINHOOD_INTERACTIVE_AUTH=true shadow python -m app.robinhood.cli probe
    ;;
  start)
    "${compose[@]}" run --rm --no-deps shadow python -m app.robinhood.cli shadow-preflight
    "${compose[@]}" up -d --no-build shadow observer
    "${compose[@]}" ps
    ;;
  stop) "${compose[@]}" stop shadow observer ;;
  observer) "${compose[@]}" up -d --no-build --no-deps --force-recreate observer ;;
  observer-logs) "${compose[@]}" logs --tail 100 observer ;;
  status)
    "${compose[@]}" ps
    "${compose[@]}" exec -T shadow python -m app.robinhood.cli shadow-service-check
    ;;
  logs) "${compose[@]}" logs --tail 100 shadow ;;
  audit) "${compose[@]}" exec -T shadow python -m app.robinhood.cli shadow-audit ;;
  history) "${compose[@]}" exec -T shadow python -m app.robinhood.cli shadow-history --limit 100 ;;
  outcomes) "${compose[@]}" exec -T shadow python -m app.robinhood.cli shadow-outcomes --limit 100 ;;
  slots) "${compose[@]}" exec -T shadow python -m app.robinhood.cli shadow-schedule-status ;;
  synthetic-init) "${compose[@]}" run --rm --no-deps shadow python -m app.robinhood.cli synthetic-init --id "${2:?Pass the new experiment ID}" "${@:3}" ;;
  synthetic-report) "${compose[@]}" exec -T shadow python -m app.robinhood.cli synthetic-report --id "${2:?Pass the experiment ID}" --limit 25 ;;
  backup)
    trade_backup="/data/backups/robinhood-$(date -u +%Y%m%dT%H%M%SZ).db"
    "${compose[@]}" exec -T shadow python -m app.robinhood.cli shadow-backup --output "$trade_backup"
    ;;
  resume) "${compose[@]}" run --rm --no-deps shadow python -m app.robinhood.cli shadow-service-resume ;;
  abandon) "${compose[@]}" run --rm --no-deps shadow python -m app.robinhood.cli shadow-slot-abandon --slot "${2:?Pass the inspected slot key}" ;;
  *) echo 'Use prepare, import, build, preflight, probe, authorize, start, stop, observer, observer-logs, status, logs, audit, history, outcomes, slots, synthetic-init, synthetic-report, backup, resume or abandon.' >&2; exit 2 ;;
esac
