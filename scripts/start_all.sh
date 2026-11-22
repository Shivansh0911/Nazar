#!/usr/bin/env bash
# Start every part of Nazar in the background (Linux/macOS). Logs: data/logs/*.log, PIDs: data/run/*.pid
#   bash scripts/start_all.sh        stop with:  bash scripts/stop_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
# shellcheck disable=SC1091
. .venv/bin/activate
LOGS="$ROOT/data/logs"; RUN="$ROOT/data/run"
mkdir -p "$LOGS" "$RUN"

docker compose -f infra/docker-compose.yml up -d
for i in $(seq 1 60); do
  docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U nazar >/dev/null 2>&1 && break
  sleep 2
done

start() {  # name, workdir, command...
  local name="$1" dir="$2"; shift 2
  if [ -f "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  (cd "$dir" && nohup "$@" >"$LOGS/$name.log" 2>&1 & echo $! >"$RUN/$name.pid")
  echo "started $name (log: data/logs/$name.log)"
}
start vision "$ROOT/backend" python -m nazar.vision.service
start worker "$ROOT/backend" python -m nazar.worker.run
start api    "$ROOT/backend" python -m uvicorn nazar.api.main:app --host 0.0.0.0 --port 8000
start web    "$ROOT/web/out" python -m http.server 3000
if grep -qE '^TELEGRAM_BOT_TOKEN=.+' .env 2>/dev/null; then
  start telegram "$ROOT/backend" python -m nazar.telegram.run
fi

for i in $(seq 1 60); do curl -fs http://localhost:8000/api/health >/dev/null 2>&1 && break; sleep 2; done
echo
echo "Nazar is up:"
echo "  Web app     http://localhost:3000        (passcode: DEMO_PASSCODE in .env, default nazar2026)"
echo "  API         http://localhost:8000/api/health   (docs: http://localhost:8000/docs)"
echo "  Vision      http://localhost:8010/health"
echo "  Postgres    localhost:5433   MediaMTX RTSP :8554, WebRTC :8889, RTMP :1935, SRT :8890/udp"
echo "First time? seed the demo cameras:  python scripts/demo_setup.py"
