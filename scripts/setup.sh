#!/usr/bin/env bash
# One-time setup on Linux/macOS (Windows: see AGENTS.md "Windows").   bash scripts/setup.sh
# Creates .venv, installs PyTorch (CUDA 12.1 if an NVIDIA GPU is present, else CPU), the backend, the models, the web
# build, starts Postgres + MediaMTX in Docker and applies the database migrations.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="${PYTHON:-python3.12}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "MISSING: $1 ($2)"; exit 1; }; }
need "$PY" "Python 3.12"
need node "Node.js 20.x"
need npm "npm 10.x"
need docker "Docker 24+ with the compose plugin"
need ffmpeg "ffmpeg 6+ with libx264"

[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example - put your OPENAI_API_KEY in it"; }

echo "== Python venv + PyTorch"
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip wheel >/dev/null
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
else
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi
pip install -e "backend[dev]"

echo "== models (YuNet, YOLO11, YOLOE, SigLIP 2)"
python scripts/download_models.py

echo "== Postgres (pgvector) + MediaMTX"
docker compose -f infra/docker-compose.yml up -d
for i in $(seq 1 60); do
  docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U nazar >/dev/null 2>&1 && break
  sleep 2
done
(cd backend && python -m nazar.core.migrate)

echo "== web (static build)"
API_URL="$(grep -E '^API_BASE_URL=' .env | cut -d= -f2- | tr -d '[:space:]')"
(cd web && npm ci && NEXT_PUBLIC_API_BASE_URL="${API_URL:-http://localhost:8000}" npm run build)

echo "== demo footage"
if [ ! -f samples/clip1.mp4 ]; then python scripts/fetch_samples.py --no-extras; fi
ls samples/*.mp4

echo
echo "Setup done. Next:  bash scripts/start_all.sh   then   python scripts/demo_setup.py   (seeds the demo cameras)"
