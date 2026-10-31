#!/usr/bin/env bash
# Separate offline UI fixture only. Never start or reconfigure the SHADOW worker.
set -euo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run on the Trade-Bot server as root.' >&2; exit 1; }
review_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$review_root"
source "$review_root/scripts/dashboard-readiness.sh"
[[ -z "$(git status --porcelain)" ]] || { echo 'Clean release checkout required.' >&2; exit 1; }
review_release="$(git rev-parse HEAD)"
review_image="trade-bot-dashboard:$review_release"
review_data=/var/lib/trade-bot-dashboard
review_backup=trade-bot-dashboard-before-review
review_name="${2:-ui-review-v1}"
case "$review_name" in
  ui-review-v1|ui-review-v2|ui-review-v3) ;;
  *) echo 'Review name must be ui-review-v1, ui-review-v2 or ui-review-v3.' >&2; exit 2 ;;
esac
review_preserved_mount=()
if [[ "$review_name" == ui-review-v2 || "$review_name" == ui-review-v3 ]]; then
  [[ -d "$review_data/ui-review-v1" && ! -L "$review_data/ui-review-v1" ]] || exit 1
  # The failed first fixture remains inaccessible for writes, even during prepare.
  review_preserved_mount=(--mount "type=bind,src=$review_data/ui-review-v1,dst=/data/ui-review-v1,readonly")
fi
[[ -d "$review_data" && ! -L "$review_data" ]] || exit 1
[[ "$(stat -c '%u:%g:%a' "$review_data")" == 10001:10001:700 ]] || exit 1

if [[ "$review_name" == ui-review-v3 ]]; then
  [[ -d "$review_data/ui-review-v2" && ! -L "$review_data/ui-review-v2" ]] || exit 1
  review_preserved_mount+=(--mount "type=bind,src=$review_data/ui-review-v2,dst=/data/ui-review-v2,readonly")
fi
review_script=mixed-dashboard-review.py
review_seed=mixed-dashboard-review.json
review_action="${1:-}"
review_previous_image=trade-bot-dashboard:cc990cf
if [[ "$review_name" == ui-review-v3 ]]; then
  review_previous_image=trade-bot-dashboard:d2092f16cc99a3749be04fb2bd5a5d26fa0e30bc
  review_backup=trade-bot-dashboard-before-two-play
  review_script=portfolio-dashboard-review.py
  review_seed=portfolio-dashboard-review.json
fi
if [[ "$review_action" == refresh ]]; then
  [[ "$review_name" == ui-review-v2 || "$review_name" == ui-review-v3 ]] || exit 1
  if [[ "$review_name" == ui-review-v3 ]]; then
    review_previous_image=trade-bot-dashboard:acabf4a816ef5cc674fe36d687d29351d273e469
    review_backup=trade-bot-dashboard-before-price-format
  else
    review_previous_image=trade-bot-dashboard:d2092f16cc99a3749be04fb2bd5a5d26fa0e30bc
    review_backup=trade-bot-dashboard-before-panel-height
  fi
  [[ "$(docker inspect --format '{{.Config.Image}}' trade-bot-dashboard)" == "$review_previous_image" ]] || {
    echo 'Unexpected dashboard release; inspect before refresh.' >&2; exit 1;
  }
  if docker container inspect "$review_backup" >/dev/null 2>&1; then
    echo 'Refresh rollback container already exists; inspect before refresh.' >&2; exit 1
  fi
  [[ -f "$review_data/$review_name/review.json" ]] || exit 1
  docker build -f Dockerfile.shadow --build-arg "TRADE_BOT_RELEASE=$review_release" \
    -t "$review_image" .
  review_action=activate
fi

case "$review_action" in
  prepare)
    [[ ! -e "$review_data/$review_name" ]] || {
      echo 'Review directory already exists. Do not overwrite or rerun it.' >&2; exit 1;
    }
    docker build -f Dockerfile.shadow --build-arg "TRADE_BOT_RELEASE=$review_release" \
      -t "$review_image" .
    docker run --rm --network none --init --read-only --user 10001:10001 \
      --cap-drop ALL --security-opt no-new-privileges:true --memory 512m --pids-limit 64 \
      --tmpfs /tmp:size=64m,mode=1777 \
      --mount "type=bind,src=$review_data,dst=/data" \
      "${review_preserved_mount[@]}" \
      --mount "type=bind,src=$review_root,dst=/review-source,readonly" \
      -e TRADER_LIVE_ENABLED=false "$review_image" \
      python -I -W error "/review-source/scripts/$review_script" \
      --output "/data/$review_name"
    ;;
  activate)
    [[ -f "$review_data/$review_name/review.json" ]] || {
      echo 'Prepare must complete before activation.' >&2; exit 1;
    }
    # Verify installed application identity, native evidence and password locally.
    # This one-shot process has no network, provider/model credentials or writable data.
    docker run --rm -i --network none --read-only --user 10001:10001 \
      --cap-drop ALL --security-opt no-new-privileges:true \
      --tmpfs /tmp:size=32m,mode=1777 \
      --mount "type=bind,src=$review_data,dst=/data,readonly" \
      --mount "type=bind,src=$review_root,dst=/review-source,readonly" \
      --mount type=bind,src=/etc/trade-bot/dashboard_password,dst=/run/secrets/dashboard_password,readonly \
      -e "REVIEW_NAME=$review_name" -e "REVIEW_SEED=$review_seed" "$review_image" python -I -W error - <<'PY'
import hashlib, json, os
from datetime import datetime
from pathlib import Path
import app
from app.mixed.observer import MixedObserver
from app.web.options import create_options_app
source = Path('/review-source/app')
installed = Path(app.__file__).parent
count = 0
for path in source.rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts:
        assert path.read_bytes() == (installed / path.relative_to(source)).read_bytes(), path.name
        count += 1
review = Path('/data') / os.environ['REVIEW_NAME']
manifest = json.loads((review / 'review.json').read_text())
journal = review / 'options.db'
assert hashlib.sha256(journal.read_bytes()).hexdigest() == manifest['journal_sha256']
assert hashlib.sha256((Path('/review-source/examples') / os.environ['REVIEW_SEED']).read_bytes()).hexdigest() == manifest['seed_sha256']
portfolio = os.environ['REVIEW_NAME'] == 'ui-review-v3'
assert manifest['population_id'] == ('ui-review-two-play-20261009' if portfolio else 'ui-review-stock-20261009')
assert manifest['as_of'] == ('2026-10-09T14:00:02+00:00' if portfolio else '2026-10-09T15:00:06+00:00')
at = datetime.fromisoformat(manifest['as_of'])
data = MixedObserver(journal, manifest['population_id'], clock=lambda: at).report()
assert data['accounting'] == 'VERIFIED' and data['fill_count'] == (2 if portfolio else 3)
assert len(data.get('positions', [])) == (2 if portfolio else 0)
assert data['cash'] == manifest['cash'] and data['equity'] == manifest['equity_at_fixture_time']
create_options_app(journal, manifest['population_id'], '/run/secrets/dashboard_password', mixed=True, review_at=manifest['as_of'])
print(json.dumps({'installed_files_match': count, 'native_fixture_verified': True}))
PY
    [[ "$(docker inspect --format '{{.Config.Image}}' trade-bot-dashboard)" == "$review_previous_image" ]] || {
      echo 'Unexpected current dashboard release; inspect before replacement.' >&2; exit 1;
    }
    if docker container inspect "$review_backup" >/dev/null 2>&1; then
      echo 'Rollback container already exists; inspect before replacement.' >&2; exit 1
    fi
    review_worker_before="$(docker inspect --format '{{.Id}} {{.Image}} {{.State.StartedAt}}' trade-bot-shadow-shadow-1 trade-bot-shadow-observer-1)"
    docker rename trade-bot-dashboard "$review_backup"
    rollback() {
      trap - ERR INT TERM
      preserve_dashboard_failure trade-bot-dashboard || true
      docker rm -f trade-bot-dashboard >/dev/null 2>&1 || true
      docker rename "$review_backup" trade-bot-dashboard
      docker start trade-bot-dashboard
      echo 'Activation failed; previous dashboard restored. Review data retained.' >&2
      exit 1
    }
    trap rollback ERR INT TERM
    docker stop "$review_backup"
    docker run -d --name trade-bot-dashboard --restart unless-stopped \
      --init --read-only --user 10001:10001 \
      --cap-drop ALL --security-opt no-new-privileges:true \
      --memory 256m --cpus 0.5 --pids-limit 32 \
      --tmpfs /tmp:size=32m,mode=1777 \
      --log-opt max-size=10m --log-opt max-file=3 \
      -p 127.0.0.1:8790:8790 \
      --mount "type=bind,src=$review_data/$review_name,dst=/data,readonly" \
      --mount type=bind,src=/etc/trade-bot/dashboard_password,dst=/run/secrets/dashboard_password,readonly \
      -e TRADER_LIVE_ENABLED=false "$review_image" \
      python -I -c 'import json, uvicorn; from pathlib import Path; from app.web.options import create_options_app; m=json.loads(Path("/data/review.json").read_text()); app=create_options_app("/data/options.db", m["population_id"], "/run/secrets/dashboard_password", mixed=True, review_at=m["as_of"]); uvicorn.run(app, host="0.0.0.0", port=8790, access_log=False, log_level="warning")'
    wait_for_dashboard trade-bot-dashboard http://127.0.0.1:8790/healthz
    [[ "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8790/)" == 401 ]]
    docker exec -i trade-bot-dashboard python -I - <<'PY'
import base64, json, urllib.request
from pathlib import Path
secret = Path('/run/secrets/dashboard_password').read_bytes().removesuffix(b'\n')
header = {'Authorization': 'Basic ' + base64.b64encode(b'trader:' + secret).decode()}
request = urllib.request.Request('http://127.0.0.1:8790/api/mixed', headers=header)
with urllib.request.urlopen(request, timeout=10) as response:
    data = json.load(response)
assert data['status'] == 'OK' and data['accounting'] == 'VERIFIED'
manifest=json.loads(Path('/data/review.json').read_text())
assert data['review']['mode'] == 'FROZEN_OFFLINE_UI_FIXTURE' and data['fill_count'] == manifest['native_fill_receipts']
assert not data['live_enabled'] and not data['execution_authority']
request = urllib.request.Request('http://127.0.0.1:8790/', headers=header)
with urllib.request.urlopen(request, timeout=10) as response:
    assert b'Paused historical simulation' in response.read()
print(json.dumps({'authenticated': True, 'mode': data['review']['mode'], 'native_fill_receipts': data['fill_count']}))
PY
    [[ "$(docker inspect --format '{{.Id}} {{.Image}} {{.State.StartedAt}}' trade-bot-shadow-shadow-1 trade-bot-shadow-observer-1)" == "$review_worker_before" ]]
    trap - ERR INT TERM
    echo 'Review active at https://signalflow.duckdns.org/ with the existing login.'
    echo 'No PAPER runtime, collector or model worker was started for this review.'
    ;;
  *) echo 'Usage: bash scripts/dashboard-review-host.sh prepare|activate|refresh [ui-review-v1|ui-review-v2|ui-review-v3]' >&2; exit 2 ;;
esac
