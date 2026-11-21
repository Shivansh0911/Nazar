# Nazar — build progress

Spec: `BUILD_PROMPT.md` (source of truth). Resume by reading this file, then continue from **Exact next step**.

## Current status
- **Current milestone:** M1 (core library + unit tests)
- **Exact next step:** see the last milestone entry below.

## Environment notes (discovered, do not re-discover)
- ffmpeg 9.1 lives at `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_...\ffmpeg-9.1-full_build\bin` and may be
  missing from a stale shell PATH. `nazar.core.config.ffmpeg_bin()` resolves it from the registry PATH; `FFMPEG_DIR`
  in `.env` overrides.
- Docker Desktop is at `%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe` (not Program Files).
- Another local project (SETU) already uses host port 5432 → **Nazar Postgres runs on host port 5433**
  (`DATABASE_URL=postgresql://nazar:nazar@localhost:5433/nazar`). Don't stop the SETU containers.
- openai SDK 3.57 (Responses API: `responses.parse(text_format=...)`, `output_parsed`,
  `usage.input_tokens_details.cached_tokens`). ultralytics 8.4.216, torch 2.5.1+cu121 (CUDA OK on RTX 4050).
- Pexels pages occasionally return 403 to scripted requests; `fetch_samples.py` prints the pages to fetch manually.

## Commands
```powershell
docker compose -f infra/docker-compose.yml up -d        # postgres (5433) + mediamtx
.\.venv\Scripts\Activate.ps1
python -m nazar.core.migrate                             # run from backend/ or with the package installed
python scripts/check_env.py
python scripts/fetch_samples.py                          # re-download + normalize demo clips
python scripts/download_models.py
```

## Needs the user's env to verify
- `python scripts/check_models.py` (needs `OPENAI_API_KEY`).

---

## M0 — Bootstrap ✅ (2026-11-21)
**Built:** repo layout, `backend/pyproject.toml` + requirements (torch cu121 first), `.env`/`.env.example`
(secrets empty), `web/.env.local`, `.claude/settings.json` (`includeCoAuthoredBy: false`), core config/logging/db
pool/migration runner, `001_init.sql` (spec §5) + `002_root_tracks.sql` (enrich_attempts, job_id, `root_tracks`
view), dev compose (pgvector pg16 on 5433, MediaMTX 8554/1935/8890udp), `mediamtx.yml`, `check_env.py`,
`check_models.py`, `download_models.py`, `fetch_samples.py`, `samples/sources.yaml`, `SOURCES.md`,
`demo_manifest.yaml`. Core modules already written for M1: geometry, timeutil, eventizer, levels, appearance, rules,
prices, usage, storage, media, schemas, openai_client.
**Footage:** clip1 veg-stall counter, clip2 Mumbai street, clip3 road with bikes/autos, clip4 mall lobby,
clip5 night fruit stall (Pexels), clip6_bag CAVIAR LeftBag_PickedUp; extras for upload tests (mall, LeftBox,
portrait 540×960, 4K). All normalized and visually checked (`data/inspect/all_clips.png`).
**Verified:** migrations applied; `check_env.py` 31/31 OK (OpenAI key ⚠️ empty).
**Not verified:** `check_models.py` — no key yet.
**Next:** M1 unit tests for the core library.
