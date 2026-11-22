#!/usr/bin/env bash
# Stop everything started by scripts/start_all.sh (and any edge processes). Docker containers keep their data.
cd "$(dirname "$0")/.."
for f in data/run/*.pid; do
  [ -f "$f" ] || continue
  kill "$(cat "$f")" 2>/dev/null && echo "stopped $(basename "$f" .pid)"
  rm -f "$f"
done
pkill -f "nazar.edge.run" 2>/dev/null || true
docker compose -f infra/docker-compose.yml stop
