# Nazar — build progress

Spec: `BUILD_PROMPT_V2.md` (v2, wins on conflicts) on top of `BUILD_PROMPT.md` (v1). Resume by reading this file,
then continue from **Exact next step** in the v2 section at the end.

## Current status
- **v2 build (22 Nov 2026):** W1, W2, W3, W5, W6, W8, W9, W11, W13, W14 done; W4 done (text prompts); W12 partly;
  W10 and W7 not done (see "v2" at the end).
- **Exact next step:** see "v2 — exact next step" at the end of this file.

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
- `cd backend; ..\.venv\Scripts\python -m pytest -m live` (real OpenAI calls).
- Ask by text/voice, rule compile, enrichment, TTS, suggest-zones: `powershell -File scripts\smoke.ps1`.
- **git push**: Git Credential Manager needs an interactive GitHub sign-in on this machine — run `git push origin main`
  once in a terminal; all local commits go up together.

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

## M5 — Agent, voice, rule compiler (code ✅, live calls need the key)
**Built:** `api/agent.py` (Responses API loop, strict function tools search_tracks/count_events/peak_occupancy/
camera_gaps/create_rule, JSON-schema final answer, server-side assembly: levels/clips/counts only from tool results,
Candidates sorted last, TTS in parallel, `queries` row with plan/answer/latency/cost), rule compiler (structured
output → RuleSpec validation → missing-zone question → replay over the last 24 h or data coverage → saved inactive),
`api/voice.py` (extension from content-type, transcription prompt with zone labels, audio seconds for cost).
**Verified with the test-only fake client:** tool loop + function_call_output wiring, strict schemas, stable
instructions first, unknown track ids dropped, model cannot inject levels (`tests/test_agent.py`).
**Needs the key:** real asks (text/voice), compile, TTS.

## M6 — Web app ✅ (2026-11-21)
**Built:** Next.js 15 static export (`web/`), Tailwind 4.1.11 (pinned: newer @tailwindcss/node breaks on Node 20.14),
login, chat (mic recorder with timer + level meter + 30 s cap, text, suggestions, count card with SVG bars, clip
cards with level badges, clip player with canvas box overlay, find-again sheet, rule card with replay + Activate,
alert bubbles via WebSocket, audio unlock + sound toggle + tap-to-play fallback), cameras, add camera (upload with
progress → processing → "Ready — ask about it", phone with Larix URL + QR + LAN IP, RTSP), camera page (MJPEG/
snapshot, zone editor with drag + AI suggest, hourly timeline, gaps, recent tracks), rules, metrics.
**Verified:** `npm run lint` 0 problems, `npm run build` OK; Playwright screenshots (`scripts/screenshots.mjs`) at
390 px and 1280 px reviewed; 0 px horizontal overflow on all routes at 390 px. Fixed after review: empty replay text,
"1 people", clipped tab label, phone URL showing localhost.

## M7 — Live ingest ✅ (2026-11-21)
**Built:** `scripts/live_from_file.ps1`, `scripts/demo_live.ps1` (-Camera office-desk plays the bag clip live on the
Office desk camera), `scripts/process_recordings.py`, `scripts/start_all.ps1`, `scripts/smoke.ps1`; MediaMTX config
with optional raw recording.
**Verified:** `live_from_file.ps1 samples\clip2.mp4 cam1` → camera added via API with `rtsp://localhost:8554/cam1`
(edge auto-started by the edge manager) → zone_enter rule activated → 3 alerts received over the WebSocket
3.3–4.2 s after the event, each with a snapshot. First track 32 s after camera creation (model load under memory
pressure; tracks are upserted every 1 s once detected). `process_recordings.py` parses MediaMTX file names.
**Not verified:** a physical phone via Larix (no phone stream in this session).

## M8 — Deploy kit (2026-11-21)
**Built:** `infra/Dockerfile.backend` (python 3.12-slim + ffmpeg, CPU torch, OpenVINO), `infra/docker-compose.prod.yml`
(mediamtx SRT/RTMP, api + edge manager with MAX_EDGES=3, worker, caddy HTTPS, optional postgres profile),
`infra/Caddyfile` (sslip.io domain, flush for MJPEG/WS), `infra/DEPLOY.md` (S3 + lifecycle, IAM role, SGs, RDS
pgvector, one c7i.xlarge, Amplify, Larix, guardrails). `.dockerignore`.
**Verified:** `docker compose -f infra/docker-compose.prod.yml config` valid, dev compose valid, `caddy validate`
(caddy:2 image) → "Valid configuration", `web/out` static export built.
**Not verified:** `docker build -f infra/Dockerfile.backend .` — 4 attempts failed only on PyPI read timeouts inside the
Docker Desktop VM on this network (base image + apt + one torch layer succeeded). Re-run on a good connection or on EC2.
**No AWS resources were created.**

## M9 — Eval, docs (2026-11-21)
**Built:** `scripts/eval_counts.py`, `scripts/eval_search.py`, `scripts/eval/questions.yaml`, `scripts/cost_report.py`,
`scripts/screenshots.mjs`, `README.md` (§22), `docs/architecture.md`, `LICENSE`, CLAUDE.md synced, `FINAL_STEPS.md`.
**Measured:** count accuracy 80 % (shop-counter 18:30 window: 6 tracked vs 5 hand-counted), saved to
`data/eval/latest.json`. Cost report runs (no AI spend yet).
**QA:** faces blurred in 5 random crops, a night segment, alert snapshot, MJPEG/snapshots (same blurred frames);
no TODO/FIXME/NotImplementedError; secret scan clean; mobile 390 px no horizontal scroll; demo DB tidied (test
uploads, test rules and today's test footage on office-desk removed → desk rule replays exactly 1 hit at 21:51).

---

# Final status

**What works (verified here):** demo dataset (6 cameras, ~600 tracks, events, stitched tracks), edge on files and
on live RTSP from MediaMTX, worker (eventize, zone re-eventize, rules, alerts with snapshots, stitcher, retention),
API (all routes; 8 smoke tests + 59 unit tests), upload of any video incl. 4K/portrait, edge start/stop from the UI,
MJPEG, clips with box overlay, find-again, rule replay, live alerts over WebSocket in ~4 s, web app (lint/build
clean, reviewed screenshots), deploy kit (compose/caddy validated).

**Needs your env (see FINAL_STEPS.md):** backend Docker image build (network timeouts here); OpenAI key → `check_models.py`, `pytest -m live`, enrichment, ask by
text/voice, compile, TTS, suggest-zones, cost numbers, search eval, chat screenshots; `git push` sign-in; AWS deploy.

**Run the demo in 5 commands:**
```powershell
docker compose -f infra/docker-compose.yml up -d
.\.venv\Scripts\Activate.ps1
python scripts/demo_setup.py --manifest samples/demo_manifest.yaml
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
start http://localhost:3000      # passcode nazar2026
```

**Run instructions (all services):** dev services `docker compose -f infra/docker-compose.yml up -d`; edge on a file
`python -m nazar.edge.run --camera demo --source ..\samples\clip1.mp4 --start-time "yesterday 22:30" --fast`
(from `backend/`); simulate-live `scripts\demo_live.ps1 -Camera office-desk`; RTSP `scripts\live_from_file.ps1
samples\clip2.mp4 cam1` + add camera `rtsp://localhost:8554/cam1`; worker `python -m nazar.worker.run`; API
`uvicorn nazar.api.main:app --port 8000`; web `cd web; npm run dev`; eval `python scripts/eval_counts.py ...`,
`python scripts/eval_search.py`; cost `python scripts/cost_report.py`; deploy `infra/DEPLOY.md`.

## Full test with the real keys (2026-11-21, evening)
- `check_env.py` 31/31, `check_models.py` 5/5 (gpt-6-luna, gpt-6-sol, text-embedding-3-small, gpt-4o-transcribe,
  gpt-4o-mini-tts), `pytest` 72 passed (incl. 6 new `-m live` real-call tests: caption, embeddings, TTS→transcribe
  round trip, rule compile + replay = 1, missing-zone question, Hinglish ask = Confirmed SQL count), web lint/build clean.
- Question battery: 10 text (Hinglish/Hindi/English) + 2 Hindi voice notes (webm + m4a) → 12/12: reply language and
  script match, counts equal the SQL series, Candidates never above Probables, voice reply delivered, 3 am question
  answered "camera offline". `scripts/smoke.ps1` PASS.
- Fixes found by testing: caption output was truncated (raised cap); captions/agent use reasoning effort `none`
  (`VISION_REASONING_EFFORT`, `AGENT_REASONING_EFFORT`) → ~40 % cheaper captions, text answers 7–10 s (was 11–17 s);
  voice reply is synthesized after the text answer and served by `/api/ask/audio/<name>` (waits until ready);
  counting rule: no place named → everyone seen (the same Hindi voice question had given 11 vs 74); passing vehicles
  (< `ENRICH_VEHICLE_MIN_SECONDS`=5 s) are not described; cost per camera-day counts the latest caption per
  described track; Metrics shows ₹ per described object.
- Honest cost result: ₹0.010 per described person/vehicle; on the rush-hour demo footage ₹351/camera-day vs a naive
  ₹449 (crop-priced). A full-frame baseline measurement was NOT run: it would send a full frame to OpenAI, which this
  project forbids.
- Demo video: `scripts/demo_video.mjs --channel chrome` records the full flow incl. a live alert (`demo/`, not committed).


---

# v2 (BUILD_PROMPT_V2.md) — 21/22 Nov 2026, night build

MCP servers added for the next session: `playwright`, `chrome-devtools`, `context7` (`claude mcp list`). They load on
the next session; this build used the Playwright npm package (`scripts/shots_v2.mjs`) and web docs instead.

## Environment notes (v2)
- **transformers must stay < 4.52** (4.52+ needs torch >= 2.6; we keep the cu121 torch 2.5.1). SigLIP 2
  (`google/siglip2-base-patch16-224`) loads with 4.51.3, 768-d, fp16 on CUDA, ~850 MB GPU.
- **Processing speed is CPU/Python-bound, not GPU-bound:** yolo11n/26n/11s/26s all ran ~80 fps through the
  ultralytics predictor; feeding GPU tensors (letterbox in torch) got 100-145 fps. yolo11s chosen (more detections at
  the same speed). Pose models (yolo11n-pose, yolo26n-pose) found almost no small/far people on street footage, so
  head boxes are the top 30 % of each person box + a YuNet pass at egress.
- ffmpeg CUDA decode (`-hwaccel cuda`) was *slower* than CPU decode for 720p at 5 fps sampling (26 s vs 2.4 s for
  62 s of video) - CPU decode is the default, `NAZAR_HWDECODE=1` enables CUDA.
- Windows file names are case-insensitive: `Evidence.tsx` and `evidence.tsx` are the same file.
- Bash heredocs with backticks break in this tool environment - write patch scripts to files instead.
- YOLOE (`yoloe-26s-seg.pt` + `mobileclip2_b.ts`, 242 MB, in `backend/models/`) works with text prompts.
- Python Playwright 1.49.1 matches the Node one and reuses its Chromium (PDF rendering).
- `FERNET_KEY` is generated into `.env` on first use (camera passwords).
- The Telegram bot drops updates sent before it started (`drop_pending_updates`), so pairing needs a fresh `/pair`.

## v2 workstreams
| | Status | Notes |
|---|---|---|
| W14 v1 fixes | ✅ | receipts + readable buckets, people-seen rule, verified search, latency/cost routing, metrics redesign, real-Chrome clips |
| W1 speed | ✅ (partly below target) | ffmpeg sampling + GPU-tensor batches (32) + ordered ByteTrack + batched DB writes; no re-encode; keyframes every 2 s; live analysis view |
| W2 counting | ✅ | people seen = root tracks >= 1.5 s, conf >= 0.6; line counters (cross_in/out); receipts + proof reel + Verify toggle; clips from originals with egress blur, H.264 Main + poster |
| W3 visual index | ✅ | vision service (SigLIP 2) indexes crops + keyframes; search by words/photo; recorded AI verification -> Probable; journey; photo audit; ENRICH_MODE=smart |
| W4 teach | ✅ text prompts | YOLOE; replay on stored keyframes; live edge runs YOLOE ~1.7 fps when a camera has custom objects; rules accept `custom:<name>`. Visual (photo) prompts not done |
| W5 security | ✅ | loitering, abandoned object, object removed, running, fall, crowding, after-hours, possible snatch; Flex AI check -> Probable; anomaly baseline; digest; FIR PDF (Hindi/English) |
| W6 agent v2 | ✅ (latency above target) | 15 tools incl. analytics_query (sqlglot + nazar_ro), luna-first routing, SSE streaming, charts, clarify, 60 s cache |
| W7 realtime voice | ❌ not done | P2, no time |
| W8 Telegram | ✅ code, pairing needs the user | text/voice/photo in; text + OGG voice + clips + chart out; alert push; digest |
| W9 onboarding | ✅ | resumable 8 MB parts, no re-encode, live analysis view, CCTV builder + Test connection, Excel/CSV import, ONVIF discovery, first-run wizard, hackathon clip as "Builders venue" |
| W10 WebRTC live view | ❌ not done | live wall uses the face-blurred MJPEG (v1); WHEP + overlay left for later |
| W11 UI | ✅ | dark-first night-watch design, side rail + bottom tabs, every screen redesigned, screenshots at 390/1440 both themes |
| W12 data/eval | partly | hand counts (3 windows), tracker comparison, agent battery, language round-trip; MOT17/snatch datasets not downloaded (multi-GB) |
| W13 cost truth | ✅ | unit costs measured from `usage`; Flex tier with fallback; projection calculator |
| W15 MCP | ✅ | Higgsfield not added (fabricated video = fake evidence) |

## v2 measured (22 Nov 2026, this laptop) — sources: data/eval/*.json
- Speed (`bench_pipeline.py`, 30 min 1280x720): v1 1.3x -> v2 8.9x real time (dense rush-hour footage, 2,636 tracks);
  venue clip 17.7x; drift 0.13 s. Bottleneck: tracker + Python on CPU, not the GPU.
- Agent battery (`eval_battery.py`, 27 questions, hi/hinglish/en): 27/27 correct; first words p50 7.0 s / p90 10.3 s;
  full p50 8.8 s / p90 12.2 s; agent cost p50 Rs 0.03 (p90 0.05); 26/27 on gpt-6-luna.
- Unit costs (Insights): question incl. voice reply p50 Rs 0.31; verification Rs 0.013/call; report Rs 0.016; caption Rs 0.005.
- Counts vs hand counts (`eval_counts.py`): office desk 2/2, shop counter 4 vs 3 (rider), venue 5 vs 3 (occluded person
  re-detected). BoT-SORT (no ReID) = ByteTrack on these windows.
- Languages round-trip: hi, en, ta, te, bn, gu, kn pass; Hinglish returns Devanagari; Marathi fails (Gurmukhi).
- Live: object-removed alert 3.0 s after the event (snapshot + voice); taught "laptop" (YOLOE) alert 4.6 s.
- Security on demo data: object_removed AI-verified Probable (ABODA); abandoned bag stays Candidate.
- Memory: vision 2.8 GB private (SigLIP loaded), edge 0.5-1.6 GB, API 0.42 GB, worker 0.45 GB; ~0.6 GB free on 8 GB.
- Privacy spot-check (10 served files: 4 crops, 3 keyframes, clip poster, reel poster, live view): faces blurred; one
  seated person's glasses showed under the head band -> head band 20 % -> 30 % + YuNet on 2x-upscaled small crops,
  demo re-processed.

## v2 — exact next step
Feature work is frozen. If resuming: (1) pair Telegram from Settings and verify a voice-note question + an alert
arrive (FINAL_STEPS §4); (2) optional P1 left: WebRTC live view (W10), YOLOE photo prompts, MOT17 eval; (3) deploy per
infra/DEPLOY.md only with the user's explicit yes for every AWS resource.
