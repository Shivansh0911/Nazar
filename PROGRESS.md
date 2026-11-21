# Nazar — build progress

Spec: `BUILD_PROMPT.md` (source of truth). Resume by reading this file, then continue from **Exact next step**.

## Current status
- **Current milestone:** M6 (web app) — M5 code written, live AI calls need the key
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
- **DATA_DIR is outside OneDrive** on this machine (`C:/Users/ssojh/AppData/Local/Nazar/data`, set in `.env`) so
  footage doesn't sync to the cloud. `data/inspect/` in the repo is only used for self-review images.
- **OpenCV must be < 5**: OpenCV 5.1's DNN engine runs YuNet ~5x slower (99 ms vs 20 ms at 640 px).
- **Memory:** this laptop has 8 GB and other apps (SETU containers, VS Code, browsers) leave little free. The Docker
  VM page cache can be dropped safely: `wsl -d docker-desktop -u root sh -c "sync; echo 3 > /proc/sys/vm/drop_caches"`.
  Under pressure an edge needs ~30-40 s to load; two edges at once slow to a crawl.
- pgvector 0.5 returns `Vector` objects → use `nazar.core.appearance.as_list()`.
- ultralytics 8.4 deprecates `half=True` → use `quantize=16`.
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

## M1 — Core library + unit tests ✅ (2026-11-21)
**Built:** tests for geometry, appearance (76-d, deterministic), eventizer (hysteresis, boundary jitter, enter/exit/dwell
incl. ongoing), rules (all triggers, object_removed with/without actor, count_over cooldown, midnight windows), levels
table, timeutil, stitcher pure merge logic (`nazar/worker/stitcher.py::find_merges`), OpenAI plumbing with the
test-only fake client (`tests/fakes.py`): request building, cost rows, vision fallback, retries, 401 handling.
**Run:** `cd backend; ..\.venv\Scripts\python -m pytest -q` → 55 passed.
**Next:** M2 edge (`nazar/edge/*`), run on samples/clip1.mp4 with --preview, visual self-review.

## M2 — Edge pipeline on a file ✅ (2026-11-21)
**Built:** `nazar/edge/` — source (file time = start + POS_MSEC, simulate-live, loop, live reconnect with backoff,
×2 upscale for < 720p sources), detector (YOLO11n + ByteTrack yaml, fp16 on CUDA, warm-up, OpenVINO/ONNX on CPU),
motion gate, tracker_state (5 Hz paths, majority class, 1 s batch upserts, finalize with 3 blurred crops +
76-d appearance, < 3 obs dropped, revived ByteTrack ids get a new generation, 60 s DB-down buffer), faceblur (YuNet
@512 + top-18 % person fallback), segments (10 s ffmpeg H.264, gap-filling to keep exact timing), snapshot,
heartbeat (+ job progress), `--preview`.
**Measured:** clip1 (1280×720): detect 24.6 fps on RTX 4050 (fp16, imgsz 640), whole pipeline 1.22× real time;
clip6 (720×480 upscaled ×2, imgsz 960): detect 19.6 fps.
**Self-review:** preview/segment/crop frames in `data/inspect/` (`preview_sheet.png`, `crops_sheet.png`,
`segment_frame.png`): boxes on the right objects, vendor keeps `person#2` across the clip, faces blurred everywhere,
timestamps 22:30 IST as requested, segments contiguous 0–32.1 s.
**Footage change:** CAVIAR's top-down fisheye bag (~20 px) is never detected by COCO YOLO → clip6 is now ABODA
video10 (bag put on a desk, detected as suitcase in every sample) + its tail reversed (pickup). On real tracks the
`object_removed` rule fires once with the correct actor (person track beside the desk). CAVIAR kept as an extra.
**Next:** M3 worker (eventize loop, rules loop, alerts, enricher, retention) + `demo_setup.py`.

## M3 — Worker ✅ (2026-11-21)
**Built:** `nazar/worker/` eventize loop (cursor + overlap, re-eventize a camera's 7 days when its zones hash changes),
rules loop (per-track evaluation + 1 s count_over tick, only hits after `activated_at`), alerts (message in the rule's
language, snapshot, optional vision confirm → suppressed, pg_notify, TTS), stitcher, enricher (3 crops → TrackCaption →
batched embeddings, daily cap, 3 attempts), retention, jobs → ready, liveness marker. Shared `core/replay.py`.
Migration 003 (rules.language/activated_at, alerts.camera_id/meta). `scripts/demo_setup.py` builds the dataset.
**Verified:** demo_setup: 13 clip runs → 6 cameras, 602 tracks, events for all default zones; shrinking a zone
re-eventized (64 → 48 counter events) and restoring gave 64; stitcher merged 3 real tracks; an active
object_removed rule produced alert #1 "Desk 14 se bag uthaya gaya — raat 9:51" with actor track + snapshot.
Edge finalize moved to a writer thread: crowded clip2 0.49× → 1.27× real time.
**Needs the key:** enrichment (captions/embeddings), alert TTS audio, vision confirm.

## M4 — API ✅ (2026-11-21)
**Built:** FastAPI app (`nazar/api/`): passcode → HMAC token (header or `?token=`), cameras CRUD with SSRF-safe source
validation (`core/security.py`, `ALLOW_LAN_CAMERAS`), snapshot, MJPEG, suggest-zones, timeline, gaps (from stored
segments), upload (probe, ≤ 2 GB / ≤ 60 min, downscale > 1280 px, rotation), progress, edge manager (MAX_EDGES queue,
restart live edges with backoff, logs), search/count debug, tracks, find-again (appearance pgvector), clips (concat +
cache + path for canvas overlay), rules, alerts, WS (LISTEN thread + status pusher), metrics, /media.
**Verified:** `pytest tests/test_api_smoke.py` 8 passed against demo data (auth, timeline sum = value, count = SQL,
structural search = confirmed, crops served, clip mp4 served, snapshot, metrics, 503 without key, source validation);
live: uploaded `extra_mall.mp4` → ready in ~40 s with 43 tracks; 4K upload normalized to 1280 px (0 tracks:
top-down stairs); portrait 540×960 → 27 tracks; start/stop edge via API; MJPEG 14 frames / 4 s.
**Next:** M6 web app (M5 agent/voice/compiler code + fake-client tests already done; live calls need the key).
