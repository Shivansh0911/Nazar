# NAZAR — Complete Build Specification for Claude Code

> **How to use this spec:** If this text was pasted into chat, FIRST save it verbatim as `BUILD_PROMPT.md` in the repo root (so future sessions can re-read it), then read it and `CLAUDE.md` fully before writing any code. This spec is the source of truth; where it differs from CLAUDE.md, this spec wins. Build milestone by milestone (M0 → M9). After every milestone: run its checks, fix until they pass, append a short entry to `PROGRESS.md` (what was built, how to run it, what's verified, what could not be verified and why, exact next step), and commit + push following §19 (Git rules). Never skip a check. Never fake AI output inside the product. If a secret or external thing is missing, still write complete, correct code for it, verify it as far as possible (§20), make the feature fail with a clear message at runtime, and record it in PROGRESS.md. Ask the user only when truly blocked (a secret, a physical action, or any AWS action that creates/deletes resources). Keep working until §21 (Definition of complete) is fully satisfied.
>
> **You own the whole setup.** Create and maintain `.env` yourself (§1.1), start Docker Desktop yourself when needed, install every dependency, download models and sample videos, run every service and test. The user will only paste secret values into `.env` at the end; until then, build and verify everything that does not need them (§20).
>
> **If you are resuming:** read `PROGRESS.md` first and continue from its "exact next step".

---

## 0. Context

**Event:** Builders 2026 hackathon (OpenAI × Equal AI, Hyderabad). Solo. **Code freeze Sunday 22 Nov 2026, 2:00 PM IST.** Judges score: working end-to-end demo, AI-native, presentation and craft. Track: Build Creative (personal context → everyday AI product; "a working journey from raw input to a useful outcome").

**Product:** **Nazar — ask your CCTV anything, in your own language.**
India's shops, homes, clinics and housing societies already have CCTV, mostly cheap DVR systems. It records 24×7 and nobody watches it. When something happens, the owner scrubs hours of footage. Nazar makes any camera (shop DVR over RTSP, a phone streaming over SRT/RTMP, or a video file) something you can talk to:

1. **Ask:** a voice note in Hindi / English / Hinglish — "Kal raat 2 baje ke baad counter pe kitne log aaye?", "Laal shirt wala banda kab aaya tha?" — returns a spoken + written answer, a count, an hourly chart, and the exact clips, each labelled with an evidence level.
2. **Teach:** "Jab bhi koi desk 14 se bag uthaye, mujhe batana" → compiled into a readable watch rule → **replayed on past footage first** ("would have fired 2 times last night", with clips) → activated → runs live → alert arrives as a voice note within seconds.
3. **Cheap by design:** cheap CV code watches every frame; OpenAI only ever sees 1–3 face-blurred crops per tracked object and the owner's questions. Cost is paise per camera-day, and the app shows the measured number.

**Lineage (use in README):** the author previously built SETU (vehicle search across 80,000 police cameras without readable number plates: edge detection, appearance fingerprints, pgvector, evidence tiers, "replay first"). Nazar is the same discipline shrunk to one shop camera.

**Product principles (enforce everywhere):**
- **Honest evidence.** Every answer item carries a level: **Confirmed** (a tracker fact: an entry, a count, a timestamp), **Probable** (semantic match AND structured attributes agree), **Candidate** (semantic similarity only). Levels are assigned by server code, never by the model, and nothing ever promotes a Candidate. A Candidate is never presented as "the answer". If nothing matches, say so plainly and list hours the camera was offline.
- **Counts come from SQL, never from a model.**
- **Trajectories are the truth; events are derived.** The edge stores each object's path. Zone events are computed from paths by one shared function, so zones can be redrawn and rules replayed retroactively.
- **Privacy by design.** Faces are blurred before any crop, clip, snapshot or live frame is saved or served. No face recognition, ever. Only small crops go to OpenAI. Media is deleted after 7 days.
- **Every OpenAI call is logged with its cost.**

### 0.1 Footage plan (IMPORTANT: no venue camera feed is available)
The demo runs on **downloaded videos**, but the product must stay fully able to connect any real camera (RTSP/SRT/RTMP/phone) — keep all live-ingest code (M7) complete and tested with a local RTSP stand-in.

**Your job in M0 (before the edge work): find and download 6 suitable clips (5 scenes + 1 bag-pickup clip).**
- Use your web search/fetch tools to find **free-license stock videos** (Pexels, Pixabay, Mixkit, Videvo free tier) or **freely downloadable research surveillance datasets** (e.g. CAVIAR shopping-centre corridor clips, VIRAT ground video samples) whose licence allows this use. **Do not download from YouTube or any site whose terms forbid it.** Do not use datasets that were withdrawn for privacy reasons (e.g. Oxford Town Centre).
- Selection criteria (check each before keeping it): **fixed camera** (tripod/CCTV, no panning or handheld shake), **elevated or eye-level view** of an area where people walk in/out, people at small-to-medium size, 30 s – 5 min long, ≥ 720p preferred, daylight or well-lit night. Prefer scenes that look Indian (street shop, market, entrance, parking, office lobby). Variety across the 5: (1) shop / store entrance or counter, (2) street or market with many people, (3) parking area with cars/bikes, (4) corridor or lobby, (5) a night or low-light scene.
- Save as `samples/clip1.mp4` … `samples/clip5.mp4`. Normalize each with ffmpeg: H.264, yuv420p, max 1280 px wide, no audio, trim to ≤ 5 min. Verify each with ffprobe and by extracting 3 frames to `data/inspect/` and looking at them; replace any clip that fails the criteria.
- Write `samples/SOURCES.md`: for each clip — source URL, author, licence, what the scene shows, duration, and which demo camera it maps to. Write `scripts/fetch_samples.py` that re-downloads from `samples/sources.yaml` (URL list) so the setup is reproducible.
- If downloads are blocked or need a login, list the exact pages/URLs and ask the user to download them manually into `samples/`, then continue.
- **Clip 6 — the bag-pickup clip (no user recording).** Find a freely available surveillance clip where an object (bag/box) is left and later picked up or taken away. Best known sources: the **CAVIAR** dataset (INRIA lobby, first set: sequences such as `LeftBag_PickedUp`, `LeftBag`, `LeftBox` — check the official CAVIAR page for availability and terms) or **PETS 2006** abandoned-baggage sequences (research use). Convert to `samples/clip6_bag.mp4`. These are low resolution (e.g. 384×288): for sources under 720p, the edge must upscale ×2 before detection (`DETECT_IMGSZ` 960 for that camera) so small bags are detected; verify the bag is detected in at least most frames while it sits still. If no suitable clip can be downloaded, list the URLs for the user to fetch manually and continue meanwhile with the other clips. This clip powers the `object_removed` rule demo and the live alert demo (via `--simulate-live` and `live_from_file.ps1`). `samples/staged_bag.mp4` stays supported if the user ever adds one, but is not required.
- **Any user or judge video must work too.** The app supports uploading an arbitrary video (§9 upload endpoint, §11 Add camera → Upload). Test it with a clip from `samples/` that is not in the manifest, including a portrait phone video and a 4K file (downscale on ingest).

**Make downloaded clips feel like real overnight CCTV.** `scripts/demo_setup.py` must accept a manifest (`samples/demo_manifest.yaml`) mapping clips to cameras and wall-clock start times, e.g.:
```yaml
cameras:
  - id: shop-counter
    name: "Shop counter"
    clips:
      - {file: samples/clip1.mp4, start: "yesterday 19:40"}
      - {file: samples/clip1.mp4, start: "yesterday 22:10"}   # same clip may be reused at another time
      - {file: samples/clip5.mp4, start: "today 02:05"}
  - id: market-street
    name: "Market street"
    clips: [{file: samples/clip2.mp4, start: "yesterday 20:30"}]
  - id: parking
    name: "Parking"
    clips: [{file: samples/clip3.mp4, start: "yesterday 23:15"}]
  - id: lobby
    name: "Lobby"
    clips: [{file: samples/clip4.mp4, start: "today 08:30"}]
  - id: office-desk
    name: "Office desk"
    clips: [{file: samples/clip6_bag.mp4, start: "yesterday 21:50"}]
```
Times between clips naturally show as **offline gaps** (that is correct and honest). Default zones per camera are created from a suggest-zones call when an API key exists, else simple default boxes; the user can redraw them. After processing, demo_setup prints 8 sample questions that will have real answers on this data (e.g. "Kal raat 10 baje ke baad shop counter pe kitne log aaye?"). Run it so the whole demo dataset is ready by the end of M3.

Also provide `scripts/live_from_file.ps1 <clip> <camera_id>`: streams a clip in a loop into MediaMTX via ffmpeg (`-re -stream_loop -1 ... -f rtsp rtsp://localhost:8554/<camera_id>`) so the **real RTSP live path** is demonstrated end to end without any physical camera.

### 0.2 Sessions
The user runs Claude Code session by session (usage limits), with no other agent. Keep PROGRESS.md precise enough that a fresh session can continue with zero re-discovery: current milestone, what's done, exact next step, commands, known issues. Commit often (at least at every milestone and every ~45 minutes of work).

---

## 1. Environment facts (do not re-discover)

**Dev machine:** Windows 11, PowerShell, 8 GB RAM, Intel i5-13420H, NVIDIA RTX 4050 Laptop 6 GB, driver 546.18 (max CUDA 12.3). Python 3.12.5, Node 20.14, npm 10.7, Docker Desktop 29.7, ffmpeg 9.1 (has libsrt, NVENC), AWS CLI 2.42. Git repo already exists; `CLAUDE.md`, `.gitignore`, `.env`, `.env.example` may already exist — keep and extend them.
- Install PyTorch FIRST with CUDA 12.1 wheels: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121`. Never install a newer CUDA build. Then install ultralytics (it must not replace torch; verify `torch.cuda.is_available()` after).
- Use CUDA for YOLO when available (`device=0`, `half=True`), else CPU.
- Keep RAM low: one YOLO model per process, no large in-memory buffers.
- All commands you give the user must work in PowerShell. Use `python -m ...` entry points. Use `os.replace` for atomic file writes. Use subprocess with list args (no shell strings) for ffmpeg.
- psycopg on Windows: use the **sync** psycopg 3 API with `psycopg_pool.ConnectionPool` (FastAPI sync endpoints run in a threadpool). Do not use psycopg async (Windows Proactor loop incompatibility).

### 1.1 Setup you must do yourself
- **`.env`:** if it does not exist, create it from the full list in §4 with every non-secret value filled (models below, `DATABASE_URL`, `STORAGE_MODE=local`, `AWS_REGION=us-west-2`, `API_BASE_URL`, `WEB_ORIGINS`, `DEMO_PASSCODE`, etc.) and these secrets left **empty**: `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `S3_BUCKET`. If `.env` exists, keep every existing value and only add missing keys. Keep `.env.example` identical in keys with all secrets empty. Never print, log or commit secret values. Also create `web/.env.local` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.
- **Docker:** before anything needs Postgres/MediaMTX, check `docker info`. If Docker is not running, start it: `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`, then poll `docker info` every 5 s for up to 3 minutes. Then `docker compose -f infra/docker-compose.yml up -d` and wait for Postgres to be healthy.
- **Git:** the repo is already cloned with `origin` set and the user's identity configured — verify (§19), don't change it.
- **Python/Node:** create `.venv`, install torch cu121 first, then the backend; `npm install` in `web/`.

**OpenAI** (models verified as available to the key; read ALL names from env, never hardcode):
```
OPENAI_VISION_MODEL=gpt-6-luna          # track captions (cheap). Fallback: gpt-5.4-mini
OPENAI_AGENT_MODEL=gpt-6-sol            # query agent, rule compiler, zone suggestion
OPENAI_EMBED_MODEL=text-embedding-3-small   # 1536 dims
OPENAI_TRANSCRIBE_MODEL=gpt-4o-transcribe
OPENAI_TTS_MODEL=gpt-4o-mini-tts
```
- Use the official `openai` Python SDK (latest). **Before writing OpenAI code, inspect the installed SDK** (`pip show openai`, read its `resources/responses` signatures) and use the Responses API correctly for that version: `client.responses.create(...)` with `tools=[{"type":"function",...}]`, function-call outputs fed back as `{"type":"function_call_output","call_id":...,"output":...}`, and Structured Outputs via `client.responses.parse(..., text_format=PydanticModel)` or `text={"format":{"type":"json_schema",...,"strict":true}}`. Images: `{"type":"input_image","image_url":"data:image/jpeg;base64,...","detail":"low"}`.
- Write `scripts/check_models.py` in M0: one tiny real call per configured model (vision with a 64×64 test image, agent text, embedding, transcribe a 1-second generated WAV/TTS clip, TTS "namaste"), prints OK/FAIL with the error. If the vision model fails with model-not-found or permission errors, print the fallback suggestion `gpt-5.4-mini`.
- Implement a **model fallback**: if `OPENAI_VISION_MODEL` returns a not-found/permission error at runtime, log it once and retry with `OPENAI_VISION_FALLBACK` (default `gpt-5.4-mini`).
- Keep system prompts stable and first in the input (prompt caching).

**Prices** (`nazar/core/prices.py`, USD; all overridable via env `PRICES_JSON`; print a warning for unknown models and count them as 0 with a flag):
```
gpt-6-luna: input 0.10 / 1M tokens, cached 0.01, output 0.50
gpt-6-sol:  input 2.00 / 1M, cached 0.20, output 10.00
gpt-5.4-mini: unknown -> require PRICES_JSON or log as unknown
text-embedding-3-small: 0.02 / 1M tokens
gpt-4o-transcribe: approx 0.006 / audio minute (verify on pricing page)
gpt-4o-mini-tts: approx 0.015 / audio minute (verify on pricing page)
USD_INR default 88 (env)
```
Use the `usage` object returned by each call for token counts. For audio, compute minutes from duration.

**AWS:** account 142093018034, region **us-west-2**, role WSParticipantRole (AdministratorAccess attached). Workshop CLI credentials are **temporary and expire** — on any AWS auth error, tell the user to refresh them from the Workshop page. On EC2, use an **instance profile role** (never workshop keys). Hard limits from organizers: **no GPU instances (g*, p*, inf*, trn*), no Bedrock, exactly ONE EC2 instance, no fleets.** Never run an AWS command that creates, modifies or deletes resources without showing it to the user and getting an explicit yes. Prefer writing console click-steps in `infra/DEPLOY.md`.

---

## 2. Architecture

```
            ┌────────────── always on ───────────────────────────────────────────┐
 camera ──► EDGE (per camera process)                                            │
 (file /    decode → 5 fps sample → motion gate → YOLO11n + ByteTrack            │
  RTSP /    → per-track path (5 Hz, normalized) → upsert active tracks (1 s)      │
  SRT/RTMP  → best crops (face-blurred) on track end → appearance vector (76-d)   │
  via       → 10 s face-blurred MP4 segments → live snapshot JPEG → heartbeat    │
  MediaMTX)                                                                       │
                    │ Postgres (pgvector)                                         │
            WORKER  ▼                                                             │
            eventizer (paths → zone events, hysteresis) → rule engine (live)      │
            stitcher (merge broken tracks) → enricher (OpenAI vision → caption,  │
            attrs → embedding) → alert builder (clip + TTS) → pg_notify           │
            └────────────────────────────────────────────────────────────────────┘
            ┌────────────── on demand ───────────────────────────────────────────┐
 phone ──►  WEB (Next.js static PWA, chat UI) ⇄ API (FastAPI)                     │
 voice note   /ask: transcribe → agent (tools: search, count, timeline, gaps,    │
              create_rule) → server assigns evidence levels → reply + TTS        │
              rules: compile → validate → replay → activate; WS alerts           │
            └────────────────────────────────────────────────────────────────────┘
```

**Processes:** `postgres`, `mediamtx` (docker), `edge` (one per camera), `worker` (one), `api` (one), `web` (Next.js). Communication only through Postgres (+ `LISTEN/NOTIFY` for alerts) and the shared media directory / S3. No queues, no microservices.

---

## 3. Repository layout (create exactly)

```
/
├─ CLAUDE.md  BUILD_PROMPT.md  PROGRESS.md  README.md
├─ .env  .env.example  .gitignore
├─ backend/
│  ├─ pyproject.toml            # package "nazar", python 3.12
│  ├─ requirements.txt          # everything except torch
│  ├─ requirements-gpu.txt      # notes: install torch cu121 first
│  ├─ nazar/
│  │  ├─ __init__.py
│  │  ├─ core/   config.py db.py migrate.py prices.py usage.py storage.py geometry.py
│  │  │          timeutil.py levels.py rules.py eventizer.py appearance.py openai_client.py
│  │  │          schemas.py logging.py
│  │  ├─ edge/   run.py source.py detector.py tracker_state.py crops.py faceblur.py
│  │  │          segments.py snapshot.py heartbeat.py bytetrack_nazar.yaml
│  │  ├─ worker/ run.py eventize_loop.py rules_loop.py stitcher.py enricher.py alerts.py retention.py
│  │  ├─ api/    main.py deps.py auth.py routes_cameras.py routes_ask.py routes_search.py
│  │  │          routes_clips.py routes_rules.py routes_alerts.py routes_metrics.py routes_live.py
│  │  │          agent.py agent_tools.py voice.py clips.py ws.py edge_manager.py routes_upload.py
│  │  └─ sql/    001_init.sql  (+ later numbered files)
│  ├─ models/   (yolo11n.pt, yunet onnx — gitignored, downloaded by script)
│  └─ tests/    test_geometry.py test_eventizer.py test_rules.py test_levels.py
│               test_timeutil.py test_stitcher.py test_api_smoke.py test_agent.py conftest.py fakes.py
├─ web/          Next.js app (static export)
├─ infra/        docker-compose.yml (dev) docker-compose.prod.yml mediamtx.yml Caddyfile
│                Dockerfile.backend DEPLOY.md
├─ scripts/      check_env.py check_models.py download_models.py fetch_samples.py demo_setup.py
│               process_recordings.py eval_counts.py eval_search.py cost_report.py screenshots.mjs
│               smoke.ps1 demo_live.ps1 live_from_file.ps1 eval/questions.yaml
├─ docs/         screenshots/ (generated by scripts/screenshots.mjs), architecture.md
├─ .claude/      settings.json  ({"includeCoAuthoredBy": false})
├─ samples/      clips (gitignored) + SOURCES.md, sources.yaml, demo_manifest.yaml (committed)
└─ data/         media in local mode (gitignored): segments/ crops/ clips/ tts/ live/ recordings/ uploads/ logs/ eval/ inspect/
```

---

## 4. Configuration (`nazar/core/config.py`)

Pydantic Settings loading `.env` from repo root. All fields with sensible defaults:
```
OPENAI_API_KEY, OPENAI_VISION_MODEL, OPENAI_VISION_FALLBACK=gpt-5.4-mini, OPENAI_AGENT_MODEL,
OPENAI_EMBED_MODEL, OPENAI_TRANSCRIBE_MODEL, OPENAI_TTS_MODEL, OPENAI_TTS_VOICE=coral,
DATABASE_URL=postgresql://nazar:nazar@localhost:5432/nazar,
STORAGE_MODE=local, DATA_DIR=<repo>/data, S3_BUCKET, AWS_REGION=us-west-2,
API_BASE_URL=http://localhost:8000, WEB_ORIGINS=http://localhost:3000,
DEMO_PASSCODE=nazar2026, TZ_NAME=Asia/Kolkata, USD_INR=88, PRICES_JSON,
DETECT_FPS=5, SEGMENT_FPS=10, SEGMENT_SECONDS=10, SEGMENT_WIDTH=854, DETECT_IMGSZ=640,
DETECT_CONF=0.30, TRACK_END_S=2.0, ACTIVE_UPSERT_S=1.0, MOTION_THRESH=0.002,
ENRICH_MIN_SECONDS=1.0, ENRICH_CONCURRENCY=4, ENRICH_DAILY_USD_CAP=5.0,
RETENTION_DAYS=7, MAX_EDGES=2, AUTO_START_EDGES=true, UPLOAD_MAX_MB=2048, LEVEL_PROBABLE_SIM=0.35, LEVEL_CANDIDATE_SIM=0.25, MEDIAMTX_HOST=localhost
```
Missing `OPENAI_API_KEY` must not crash startup; AI features return HTTP 503 with `{"error":"OPENAI_API_KEY not set"}`.

---

## 5. Database (`backend/nazar/sql/001_init.sql`)

A tiny migration runner (`python -m nazar.core.migrate`) applies numbered SQL files once, tracked in `schema_migrations`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE cameras (
  id text PRIMARY KEY,                       -- slug, e.g. 'demo', 'hall-1'
  name text NOT NULL,
  source_url text NOT NULL,                  -- file path, rtsp://, srt://, rtmp://
  kind text NOT NULL CHECK (kind IN ('file','rtsp','srt','rtmp','phone')),
  zones jsonb NOT NULL DEFAULT '[]',         -- [{"name":"counter","label":"Counter","polygon":[[x,y],...]}] normalized 0..1
  settings jsonb NOT NULL DEFAULT '{}',      -- per-camera overrides: detect_imgsz, upscale (auto 2 for sources < 720p), detect_conf
  width int, height int,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tracks (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  run_id text NOT NULL,                      -- one per edge run; ByteTrack ids are only unique per run
  local_id int NOT NULL,
  cls text NOT NULL,
  t_start timestamptz NOT NULL,
  t_end timestamptz NOT NULL,
  active boolean NOT NULL DEFAULT true,
  path jsonb NOT NULL DEFAULT '[]',          -- [[t_ms, x1, y1, x2, y2, conf], ...] normalized, 5 Hz
  zone_path text[] NOT NULL DEFAULT '{}',    -- ordered distinct zones visited (derived)
  crop_keys text[] NOT NULL DEFAULT '{}',
  max_conf real,
  appearance vector(76),
  caption text,
  attrs jsonb,
  caption_emb vector(1536),
  enriched boolean NOT NULL DEFAULT false,
  enrich_error text,
  merged_into bigint REFERENCES tracks(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (camera_id, run_id, local_id)
);
CREATE INDEX ON tracks (camera_id, t_start);
CREATE INDEX ON tracks (camera_id, t_end);
CREATE INDEX ON tracks (updated_at);
CREATE INDEX ON tracks USING gin (zone_path);
CREATE INDEX tracks_unenriched ON tracks (t_end) WHERE enriched = false AND active = false;
CREATE INDEX ON tracks USING hnsw (caption_emb vector_cosine_ops);
CREATE INDEX ON tracks USING hnsw (appearance vector_cosine_ops);

CREATE TABLE events (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  track_id bigint NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  type text NOT NULL CHECK (type IN ('enter','exit','dwell')),
  zone text NOT NULL,
  t timestamptz NOT NULL,
  meta jsonb NOT NULL DEFAULT '{}'           -- dwell: {"seconds": 74}
);
CREATE INDEX ON events (camera_id, t);
CREATE INDEX ON events (camera_id, zone, type, t);
CREATE INDEX ON events (track_id);

CREATE TABLE segments (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  t_start timestamptz NOT NULL, t_end timestamptz NOT NULL,
  key text NOT NULL, fps real, width int, height int
);
CREATE INDEX ON segments (camera_id, t_start);

CREATE TABLE camera_status (
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  t timestamptz NOT NULL, ok boolean NOT NULL,
  fps_in real, fps_proc real, active_tracks int, note text
);
CREATE INDEX ON camera_status (camera_id, t);

CREATE TABLE rules (
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  text text NOT NULL,                        -- owner's words
  spec jsonb NOT NULL,                       -- validated RuleSpec
  human text NOT NULL,                       -- readable sentence in owner's language
  active boolean NOT NULL DEFAULT false,
  replay jsonb,                              -- {"window_from","window_to","hits":[{track_id,t}], "count"}
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE alerts (
  id bigserial PRIMARY KEY,
  rule_id bigint NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  track_id bigint NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  t timestamptz NOT NULL,
  message text NOT NULL,
  clip_key text, audio_key text, snapshot_key text,
  vision_confirmed boolean,
  ack boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rule_id, track_id)
);

CREATE TABLE queries (
  id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
  camera_id text, input_kind text, transcript text, language text,
  plan jsonb, answer jsonb, latency_ms int, cost_usd numeric(12,6)
);

CREATE TABLE usage (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL,                        -- caption, embed, agent, compile, transcribe, tts, zones, confirm
  model text NOT NULL, camera_id text, ref text,
  input_tokens int, cached_tokens int, output_tokens int, images int, audio_seconds real,
  cost_usd numeric(12,6) NOT NULL DEFAULT 0, unknown_price boolean NOT NULL DEFAULT false
);
CREATE INDEX ON usage (at);

CREATE TABLE jobs (                          -- uploads and demo processing; drives /progress
  id bigserial PRIMARY KEY,
  camera_id text NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  kind text NOT NULL,                        -- upload | demo | recording
  source text NOT NULL, start_time timestamptz,
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','processing','enriching','ready','error')),
  duration_s real, processed_s real NOT NULL DEFAULT 0, error text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
```
The edge updates `jobs.processed_s` every few seconds when run with `--job <id>`; the worker moves a job to `ready` once all its tracks are eventized and enriched (or immediately after eventizing when no OpenAI key is set, with a note).

`db.py`: a global `ConnectionPool` (min 1, max 10), helpers `fetch_all`, `fetch_one`, `execute`, `executemany`, and pgvector adapter registration (`pgvector.psycopg.register_vector`).

---

## 6. Core library (`nazar/core`) — shared by edge, worker, api

### 6.1 `geometry.py`
- `point_in_polygon(x, y, poly) -> bool` (ray casting, normalized coords).
- `anchor_point(cls, box)`: **feet point** `((x1+x2)/2, y2)` for person/bicycle/car/motorcycle/bus/truck; **center** for objects (backpack, handbag, suitcase, laptop, cell phone, bottle).
- `iou(a, b)`, `box_distance(a, b)` (normalized center distance).

### 6.2 `eventizer.py` — the single source of zone truth
`eventize(track_path, cls, zones, hysteresis=2, dwell_thresholds=None) -> (events, zone_path)`:
- For each zone, walk path points; state flips inside/outside only after `hysteresis` consecutive points agree.
- Emit `enter` at the first point of a confirmed inside run (use that point's time), `exit` at the first point of a confirmed outside run. If the track ends while inside, no exit (it may still be there or have vanished).
- `dwell`: for each completed or ongoing inside run, emit one `dwell` event with `meta.seconds` = run length if ≥ 10 s (store actual seconds; rules decide thresholds).
- Returns ordered distinct `zone_path`.
- Used by: worker eventize loop, rule replay, rule live evaluation, zone re-computation. Unit-test thoroughly (jitter on a boundary must not create flapping events).

### 6.3 `rules.py`
```python
class RuleSpec(BaseModel):
    camera_id: str
    trigger: Literal["zone_enter","zone_exit","dwell_over","count_over","object_removed"]
    cls: Literal["person","car","motorcycle","bicycle","bus","truck","backpack","handbag","suitcase","laptop","cell phone","bottle","any_bag"]
    zone: str                       # must exist on the camera, or "anywhere"
    dwell_s: int | None = None      # required for dwell_over (>= 5)
    count: int | None = None        # required for count_over (>= 1)
    time_window: TimeWindow | None  # {"from":"22:00","to":"07:00"} local TZ; may wrap midnight
    confirm_with_vision: str | None # short English sentence checked on one crop before alerting
    notify: Literal["voice_note"] = "voice_note"
```
`any_bag` expands to backpack/handbag/suitcase. Validators enforce required fields per trigger.

`evaluate_track(spec, track, zones, others_near=None) -> list[Hit]` (pure function, used by replay AND live):
- `zone_enter` / `zone_exit` / `dwell_over`: from `eventize(...)` on that track (dwell_over when an inside run ≥ dwell_s, even if still ongoing → live dwell alerts).
- `object_removed`: for object classes. Hit when (a) the object was **stationary** inside the zone for ≥ 10 s (center moved < 0.03 over that span) AND then (b) either its track ended (`active=false`) while last seen inside the zone, or it exited the zone. Require a person track whose box overlapped/was within 0.1 of the object within ±3 s of the removal time (pass via `others_near`); store that person's track id in the hit as `actor_track_id`. The alert's track is the **person** if found, else the object.
- `count_over`: evaluated per camera, not per track: `evaluate_count(spec, tracks_in_window)` on a 1-second grid — number of distinct tracks of `cls` inside `zone` at the same time > `count`; hit at the first second of each over-run (cooldown 60 s).
- Apply `time_window` to hit times (wrap-around aware).
- `zone == "anywhere"` means the full frame.

`human_sentence(spec, language)` is produced by the compiler model (see agent) but `rules.py` also has a deterministic English fallback.

### 6.4 `levels.py`
```python
def assign_level(*, structural_only: bool, sim: float | None, attr_requested: int, attr_matched: int) -> Literal["confirmed","probable","candidate"] | None
```
- Structural queries (time/zone/class filters only, no description) → `confirmed`.
- With description/attributes: `probable` if `attr_requested > 0 and attr_matched == attr_requested and (sim is None or sim >= LEVEL_PROBABLE_SIM)`; or if `attr_requested == 0 and sim >= LEVEL_PROBABLE_SIM + 0.1`.
- `candidate` if `sim >= LEVEL_CANDIDATE_SIM` or `attr_matched >= 1`.
- else `None` (not returned).
This function is the ONLY place levels are decided. The agent can never set or change a level.

### 6.5 `appearance.py` — 76-d fingerprint (SETU style, free, no API)
From the best crop (BGR), person/vehicle box:
- Upper region = rows 15–50 % of box height; lower = 50–90 %; (vehicles: whole box for both).
- For each region in CIE Lab: L histogram 6 bins + a 12 bins + b 12 bins = 30 → 60 total.
- Whole-box HSV hue histogram 12 bins (pixels with S > 40 and V > 40 only) → 72.
- Sobel edge orientation histogram, 4 bins, magnitude-weighted → 76.
- Each block L1-normalized, then the whole vector L2-normalized. Deterministic; unit-tested.

### 6.6 `timeutil.py`
IST helpers: `now_local()`, `to_local()`, `parse_hhmm`, `in_window(t, window)` (wrap-aware), `fmt_local(t, lang)` → e.g. "2:41 AM" / "रात 2:41".

### 6.7 `storage.py`
`put(local_path, key)`, `url(key)`, `exists(key)`, `local_path(key)`.
- local mode: files under `DATA_DIR/<key>`, URLs `API_BASE_URL/media/<key>`.
- s3 mode: crops/clips/tts/snapshots uploaded with boto3 and served by presigned URLs (1 h). **Segments stay on local disk** (needed by ffmpeg for clip cutting). Key prefixes: `crops/<camera>/<track>_<n>.jpg`, `clips/<camera>/<hash>.mp4`, `tts/<id>.mp3`, `snap/<alert>.jpg`.

### 6.8 `openai_client.py` + `usage.py`
- One client wrapper with: `caption_track(images, cls) -> TrackCaption`, `embed(texts) -> list[vec]`, `agent_step(...)`, `parse(model, input, schema)`, `transcribe(file_path, prompt) -> (text, language_guess, seconds)`, `tts(text, language) -> mp3 path`, `vision_check(image, question) -> bool + reason`.
- Every call records a `usage` row (kind, model, tokens/images/audio seconds, cost via `prices.py`, camera_id, ref).
- Retries: 3 with exponential backoff on 429/5xx/timeouts; clear errors on 401/insufficient_quota ("OpenAI credits/key problem").
- Daily enrichment cap: if today's caption+embed cost ≥ `ENRICH_DAILY_USD_CAP`, the enricher pauses and logs.

### 6.9 `schemas.py`
Pydantic models shared with the API: `TrackCaption`, `ClipItem`, `CountResult`, `SeriesPoint`, `AskResponse`, `RuleDraft`, `AlertOut`, `CameraOut`, `ZoneIn`, `MetricsOut` (see §9).

```python
class TrackCaption(BaseModel):   # Structured Output for vision
    caption: str                 # <= 25 words, English, factual, no guesses about identity/ethnicity/age beyond "child/adult"
    upper_color: Literal[COLORS] ; lower_color: Literal[COLORS]   # COLORS = black, white, grey, red, orange, yellow, green, blue, purple, pink, brown, beige, unknown
    headwear: Literal["none","cap","helmet","turban","scarf","hood","other","unknown"]
    carrying: list[Literal["backpack","handbag","suitcase","box","parcel","bottle","phone","laptop","bag","umbrella","nothing","unknown"]]
    action: Literal["walking","standing","sitting","running","carrying","picking_up","putting_down","riding","driving","parked","other"]
    vehicle_type: Literal["none","car","motorcycle","scooter","bicycle","auto_rickshaw","bus","truck","van","other"]
    vehicle_color: Literal[COLORS]
    notable: str                 # <= 10 words, or ""
    quality: Literal["good","poor"]
```
The vision system prompt forbids identity, ethnicity, religion, caste and age guesses beyond child/adult, and asks for "unknown" when unsure.

---

## 7. Edge (`nazar/edge`) — `python -m nazar.edge.run`

**CLI:** `--camera <id>` (required; source read from DB unless `--source` given; if the camera row does not exist and `--source` is given, create it with kind inferred from the URL and name = id), `--source <path|url>`, `--start-time <ISO local>` (files only; default = file modified time minus duration), `--simulate-live` (pace frames in real time and stamp with **now**, for using a file as a live camera), `--loop` (with simulate-live), `--fast` (files: process as fast as possible), `--max-seconds N`, `--preview` (also write `data/preview_<camera>.mp4` with boxes, ids, zones drawn), `--device auto|cpu|0`, `--job <id>` (report progress to `jobs`).

**source.py:** OpenCV `VideoCapture` with FFMPEG backend. For RTSP set env `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`. Frame timestamps:
- files: `t = start_time + CAP_PROP_POS_MSEC` (never compute time from a declared fps; if POS_MSEC is 0/invalid, fall back to frame_index / measured fps and log a warning);
- live / simulate-live: wall clock at read.
- Reconnect with backoff (1, 2, 4 … 30 s) on read failures; heartbeat `ok=false` with a note while down.

**Main loop:**
1. Read frames; output at `SEGMENT_FPS` (drop frames by timestamp), and run detection on every frame whose timestamp is ≥ 1/`DETECT_FPS` after the last detection.
2. **Motion gate:** 160-px-wide grayscale diff vs. the last detected frame; fraction of changed pixels (`absdiff > 25`) < `MOTION_THRESH` and **no active tracks** → skip detection for this frame.
3. **Detect + track** (weights `yolo11n.pt`; if Ultralytics marks it deprecated, use the newest nano detection model it ships): `model.track(frame, persist=True, tracker=<path to bytetrack_nazar.yaml>, classes=[0,1,2,3,5,7,24,26,28,39,63,67], conf=DETECT_CONF, imgsz=DETECT_IMGSZ, device=..., half=cuda, verbose=False)`.
   `bytetrack_nazar.yaml`: `tracker_type: bytetrack, track_high_thresh: 0.4, track_low_thresh: 0.1, new_track_thresh: 0.5, track_buffer: 30, match_thresh: 0.8, fuse_score: true`.
4. **tracker_state.py:** for each (id, cls, box, conf) append `[t_ms, x1, y1, x2, y2, conf]` (normalized) to the track's path; class = majority vote over observations; keep `max_conf`; feed crop candidates (§ crops). Tracks unseen for `TRACK_END_S` → **finalize**. Every `ACTIVE_UPSERT_S`, batch-upsert all active tracks (`INSERT ... ON CONFLICT (camera_id, run_id, local_id) DO UPDATE SET path, t_end, cls, max_conf, updated_at=now()`). Ignore tracks with < 3 observations at finalize (noise) by deleting them.
5. **Finalize:** choose crops, blur faces, save up to 3 JPEGs (q=85, 10 % padding, min side 96 px, upscale small crops ×2), compute appearance vector from the best crop, upsert final row with `active=false`, `crop_keys`, `appearance`.
6. **crops.py:** candidates = first sighting, best quality, and one near the middle of the track. Quality = `sqrt(area) * min(1, laplacian_var/150) * conf * (0.5 if box touches frame edge else 1)`. Keep at most 3 candidate crop images in memory per track (replace worse ones).
7. **faceblur.py:** OpenCV `FaceDetectorYN` with `face_detection_yunet_2023mar.onnx` (downloaded by `scripts/download_models.py` from the opencv_zoo GitHub repo), run on every detection frame at width 640; reuse the latest face boxes for in-between segment frames; blur = heavy Gaussian over the face box padded 30 %. **Fallback when the model is missing or finds nothing for a person box:** blur the top 18 % of every person box. Applied to: segment frames, live snapshots, crops, preview.
8. **segments.py:** every `SEGMENT_SECONDS`, start a new ffmpeg process writing raw BGR frames from stdin: `ffmpeg -y -f rawvideo -pix_fmt bgr24 -s WxH -r SEGMENT_FPS -i - -an -c:v libx264 -preset veryfast -crf 28 -pix_fmt yuv420p -movflags +faststart <file>.mp4`. Frames resized to `SEGMENT_WIDTH`. Name files `segments/<camera>/<YYYYMMDD>/<t_start_ms>.mp4`; insert a `segments` row with the exact first/last frame timestamps on close. Segments are faceblurred and never contain boxes.
9. **snapshot.py:** write `live/<camera>.jpg` (blurred, q=70, width 854) atomically on every detection frame (≈5 fps).
10. **heartbeat.py:** every 5 s insert `camera_status` (ok, fps_in, fps_proc, active_tracks).
11. On first frame, update `cameras.width/height`.
12. Graceful shutdown (Ctrl+C / SIGTERM): finalize all tracks, close the segment, final heartbeat `ok=false note='stopped'`.

`--preview` writes an annotated MP4 for debugging (boxes, `cls#id`, zones polygons, fps text).

**Performance target:** on the RTX 4050, ≥ 5 detection fps for 1080p input with headroom; on a 4-vCPU EC2, ≥ 5 fps with YOLO exported to ONNX or OpenVINO (`--device cpu` should automatically use an exported `yolo11n_openvino_model` if present; `scripts/download_models.py --export-cpu` creates it).

---

## 8. Worker (`nazar/worker`) — `python -m nazar.worker.run`

One process, several threads, each loop wrapped in try/except with logging and backoff. All loops are idempotent.

1. **eventize_loop (every 1 s):** select tracks with `updated_at > cursor` (cursor in memory, start = now − 10 min on boot). For each: run `eventize` with the camera's zones; in a transaction delete that track's events and insert new ones; update `zone_path`. Then hand the track to the rules loop. Also handle `cameras.zones` changes: a `zones_version` (hash) per camera kept in memory; on change, re-eventize that camera's last 7 days of tracks in batches.
2. **rules_loop (driven by eventize, plus a 1 s tick for count_over):** for each active rule on that camera, `evaluate_track(...)` (for `object_removed`, fetch person tracks overlapping in time ±3 s from DB). New hits → `alerts.build(...)`. Uniqueness via `UNIQUE(rule_id, track_id)` (`ON CONFLICT DO NOTHING`). `count_over` uses a per-rule cooldown.
3. **alerts.py — build(rule, hit):**
   - If `confirm_with_vision`: crop from `live/<camera>.jpg` (live) or the track's best crop (finished track) using the last box; call `vision_check` (agent model, structured `{yes: bool, reason: str}`); if no → store the alert with `vision_confirmed=false` and do NOT notify (visible in UI as "suppressed").
   - Message in the rule's language: e.g. "Desk 14 से बैग उठाया गया — रात 2:41" / "Bag taken from desk 14 at 2:41 AM".
   - TTS mp3 → storage; snapshot crop → storage; insert alert; `pg_notify('nazar_alerts', alert_id)`; clip is cut lazily by the API when opened.
4. **stitcher (every 5 s):** fix broken tracks (ID switches inflate counts). For finished tracks of the same camera and class where B starts ≤ 1.5 s after A ends, the end of A and start of B are within 0.08 normalized distance, and appearance cosine similarity ≥ 0.85 → set `B.merged_into = root(A)`. Counting and search use root tracks (`merged_into IS NULL`), aggregating times and paths of merged children (SQL view `root_tracks`). Unit-test with synthetic tracks.
5. **enricher (every 2 s, `ENRICH_CONCURRENCY` threads):** finished, unenriched, root tracks, duration ≥ `ENRICH_MIN_SECONDS`, newest first. Send up to 3 crops (detail=low) + class to the vision model with the `TrackCaption` schema. Build embed text: `"{cls}. {caption}. upper {upper_color}, lower {lower_color}. headwear {headwear}. carrying {carrying}. action {action}. vehicle {vehicle_type} {vehicle_color}. {notable}"`. Embed in batches of up to 64. Save `caption, attrs, caption_emb, enriched=true`. On error store `enrich_error` and retry later (max 3 attempts). Respect the daily cap.
6. **retention (hourly):** delete media and rows older than `RETENTION_DAYS` (segments, crops, clips, tts, snapshots, tracks, events, camera_status); never delete `usage` or `queries`.

---

## 9. API (`nazar/api`) — `uvicorn nazar.api.main:app --port 8000`

FastAPI with CORS for `WEB_ORIGINS`. Auth: `POST /api/auth {"passcode"}` → returns a signed token (HMAC of passcode + expiry); all `/api/*` except health/auth require header `X-Nazar-Token` or `?token=` (needed for `<video>`, `<img>`, MJPEG and WS URLs). `/media/*` served from `DATA_DIR` in local mode (token required).

**Endpoints:**
- `GET /api/health` → db ok, openai key present, cameras live status.
- `GET /api/cameras` → list with live status (last heartbeat age, ok), today's person count, data coverage (`min(t_start)`, `max(t_end)`).
- `POST /api/cameras {id,name,source_url,kind}` → validate URL (§13 security), insert. `PATCH /api/cameras/{id}` (name, zones). `DELETE`.
- `GET /api/cameras/{id}/snapshot.jpg` → latest `live/<id>.jpg`, else first frame of the latest segment (ffmpeg).
- `GET /api/cameras/{id}/live.mjpg` → multipart MJPEG stream re-reading `live/<id>.jpg` at ~5 fps (blurred; works on every browser, no HLS needed).
- `POST /api/cameras/{id}/suggest-zones` → sends the current snapshot (blurred) to the agent model; Structured Output: `zones: [{name (snake_case English), label (owner-friendly), polygon: [[x,y]...] normalized, 4–8 points}]` (max 6). Returned as suggestions only; the UI lets the user edit and save.
- `GET /api/cameras/{id}/timeline?from&to&bucket=hour|15min&cls=person&zone=` → series from `date_bin` over root tracks/events.
- `GET /api/cameras/{id}/gaps?from&to` → offline periods (no heartbeat > 15 s or ok=false).
- `POST /api/cameras/upload` (multipart: `file`, `name`, optional `start` local datetime, default = now − video duration) → saves to `data/uploads/`, creates a `file` camera (id from name), probes with ffprobe (reject non-video, > 2 GB, or > 60 min; downscale anything above 1280 px wide, rotate portrait correctly), then starts processing via the edge manager with `--fast`. `GET /api/cameras/{id}/progress` → `{state: queued|processing|enriching|ready|error, processed_seconds, duration_seconds, tracks, enriched, error}`.
- **Edge manager** (`nazar/api/edge_manager.py`): starts/stops edge subprocesses (`python -m nazar.edge.run --camera <id> ...`) for cameras, restarts a crashed live edge with backoff, writes logs to `data/logs/edge_<id>.log`, never runs more than `MAX_EDGES` (default 2 on the laptop) at once (others queue). `POST /api/cameras/{id}/start`, `POST /api/cameras/{id}/stop`, `GET /api/cameras/{id}/edge` (running, pid, uptime, last log lines). With `AUTO_START_EDGES=true`, the API starts edges for all active live (non-file) cameras on boot. Adding a camera in the UI therefore needs no terminal.
- `POST /api/ask` → JSON `{text, camera_id?}` or multipart `audio` (+ `camera_id`). See §10. Returns `AskResponse`.
- `GET /api/search` (debug, same params as the tool) and `GET /api/count` (debug).
- `GET /api/tracks/{id}` → track with caption, attrs, crops URLs, path, zone_path, events.
- `GET /api/tracks/{id}/similar?hours=24` → "find this person again": appearance-vector cosine search, same camera(s), within ±hours, excluding itself and merged children, top 10. Level: `probable` only if caption attrs (upper+lower colours) also match, else `candidate`.
- `GET /api/clips/track/{id}` → `{url, t0_ms, t1_ms, path}`: clip window `[t_start − 2 s, t_end + 2 s]`, max 30 s (if longer, centre on `?at=` or the first event). `GET /api/clips/range?camera_id&from&to` (max 60 s).
- `POST /api/rules/compile {text, camera_id, language?}` → `RuleDraft` (see §10.4) with replay results; rule saved inactive.
- `POST /api/rules/{id}/activate`, `POST /api/rules/{id}/deactivate`, `DELETE /api/rules/{id}`, `GET /api/rules`.
- `GET /api/alerts?limit=50`, `POST /api/alerts/{id}/ack`.
- `WS /api/ws?token=` → server pushes `{"type":"alert", alert}` (from a background thread `LISTEN nazar_alerts` on a dedicated connection, forwarded to the asyncio loop with `call_soon_threadsafe`), `{"type":"camera_status", ...}` every 5 s.
- `GET /api/metrics` → `MetricsOut`: total spend (USD, INR), spend by kind and model, **cost per camera-day** (enrich + embed cost per camera ÷ hours of footage processed × 24, in ₹), naive baseline (measured avg cost of one caption image × 86,400 per camera-day), ratio, tracks processed, enrichment backlog, ask latency p50/p90, query count.
- `GET /media/{key}` (local mode).

**clips.py:** find segments overlapping the window; write an ffmpeg concat list; `ffmpeg -f concat -safe 0 -i list.txt -ss <offset> -t <dur> -c:v libx264 -preset veryfast -crf 26 -movflags +faststart out.mp4`; cache by hash of (camera, from, to); return URL. If segments are missing, return 404 with `{"error":"no footage stored for that time"}`. Also return the track's path within the window so the web app can **draw the box over the video on a canvas** (no re-encode with boxes).

---

## 10. AI behaviour (the heart)

### 10.1 Voice in (`voice.py`)
- Accept webm/opus (Chrome/Android), mp4/m4a/aac (iOS Safari), wav. Save with the correct extension (from content-type/filename) — the transcription API uses the extension.
- Transcribe with `OPENAI_TRANSCRIBE_MODEL`, `prompt` = "Shop CCTV questions in Hindi, English or Hinglish. Zones: <zone labels>. Words: camera, counter, gate, desk, parcel, bag, kitne log, kab, raat, subah." Measure audio seconds (ffprobe) for cost.
- Return transcript as-is (Devanagari or Latin).

### 10.2 Query agent (`agent.py`, `agent_tools.py`)
Model: `OPENAI_AGENT_MODEL`, Responses API, function tools, max 6 tool rounds, then a final Structured Output.

**System prompt (stable, cached) must state:**
- You are Nazar, an assistant that answers questions about the owner's own CCTV footage. Current local time `<now IST>`, timezone Asia/Kolkata. Cameras: `<id, name, zones with labels, data coverage from–to>`.
- Resolve relative times against now ("kal raat" = yesterday 20:00 → today 06:00 unless specified; "subah" = 05:00–11:00; "2 baje ke baad raat ko" = 02:00 onwards that night). **If the question's time is outside data coverage, use the coverage window and say so.**
- Always use tools for facts. Never invent counts, times or clips. Counts come only from `count_events`/`timeline`. Descriptions ("red shirt", "carrying a box") go to `search_tracks` with structured attributes AND a short English `text`.
- If the owner asks to be notified/alerted ("mujhe batana", "alert me", "jab bhi"), call `create_rule`.
- If nothing is found, say it plainly and mention offline gaps if any.
- Reply in the user's language and script (Hindi question → Hindi in Devanagari; Hinglish in Latin → Hinglish; English → English). 1–3 short sentences, spoken style, times like "रात 2:41" or "2:41 AM". Never mention evidence levels by name in the text except "pakka"/"confirmed" for Confirmed facts and "shayad"/"possible match" for candidates.

**Tools (JSON schemas, strict):**
1. `search_tracks({camera_ids?: string[], time_from: ISO, time_to: ISO, cls?: string[], zones?: string[], upper_color?: string, lower_color?: string, carrying?: string[], vehicle_type?: string, vehicle_color?: string, action?: string, text?: string, limit?: int<=12})`
   Server: SQL filter (time overlap, root tracks, cls, `zone_path && zones`), then if `text` → embed and rank by cosine; compute `attr_requested/matched` against `attrs`; `levels.assign_level`; drop None; sort by level then score. Returns `[{track_id, camera_id, cls, t_start, t_end, zones, caption, level, score, why}]` (`why` = short machine explanation, e.g. "upper=red ✓, carrying=bag ✓, sim 0.42").
   If no description at all (structural), results are `confirmed`, sorted by time, and the tool also returns `total`.
2. `count_events({camera_id, zone?: string, cls?: string = "person", event?: "enter"|"exit"|"dwell"|"present" = "enter", time_from, time_to, bucket?: "hour"|"15min"})`
   Distinct root tracks; `present` = distinct tracks seen at all (zone optional). Returns `{value, series:[{t, n}], level:"confirmed"}`.
3. `peak_occupancy({camera_id, zone?, cls?, time_from, time_to})` → max simultaneous tracks and when.
4. `camera_gaps({camera_id, time_from, time_to})` → offline periods.
5. `create_rule({camera_id, text})` → runs the rule compiler (§10.4) and returns the `RuleDraft` summary (rule id, human sentence, replay count). Does NOT activate.

**Final Structured Output (`AgentAnswer`):** `{reply_text, language: "hi"|"en"|"hinglish", show_track_ids: int[] (<= 6, chosen from tool results), count_ref?: {tool_call_index}, rule_id?: int, followups: string[] (<= 3 short suggestions in the same language)}`.
**Server assembles `AskResponse`:** levels/clip info are taken from the server-side tool results for each `show_track_id` (ignore ids not returned by a tool); count + series from the referenced count tool result; offline gaps if any tool returned them; TTS of `reply_text`; logs to `queries`.

```python
class AskResponse(BaseModel):
    query_id: int; transcript: str | None; language: str
    reply_text: str; audio_url: str | None
    count: CountResult | None          # {value, label, level:"confirmed", series:[{t,n}]}
    clips: list[ClipItem]              # {track_id, camera_id, t_start, t_end, level, why, caption, thumb_url}
    rule: RuleDraft | None
    gaps: list[dict]; followups: list[str]
    cost_usd: float; latency_ms: int
```
Latency target: < 6 s for a text question, < 9 s for voice (transcribe + agent + TTS). Run TTS in parallel with response assembly where possible; if TTS fails, still return text.

### 10.3 Voice out
`OPENAI_TTS_MODEL`, voice `OPENAI_TTS_VOICE`, `instructions` = "Speak warmly and naturally like a helpful Indian shop assistant. If the text is Hindi, use natural Hindi pronunciation." mp3 → storage → `audio_url`.

### 10.4 Rule compiler
`compile_rule(text, camera_id, language)` with the agent model and a strict schema:
`{ok: bool, spec?: RuleSpec, human?: string (owner's language, one sentence, e.g. "रात 10 से सुबह 7 के बीच desk_14 से कोई बैग उठाए तो voice note भेजो"), missing_zone_label?: string, question?: string}`.
Prompt includes the camera's zones (name + label), the allowed triggers/classes, and examples:
- "Jab bhi koi desk 14 se bag uthaye, mujhe batana" → object_removed, any_bag, zone desk_14.
- "Raat 11 ke baad gate pe koi aaye toh batao" → zone_enter, person, gate, window 23:00–06:00.
- "Counter pe 5 se zyada log ho jaayein toh" → count_over, person, counter, count 5.
- "Agar koi gate pe 2 minute se zyada ruke" → dwell_over, person, gate, dwell_s 120.
- "Parcel ke paas koi jaaye" → zone_enter person in the zone containing the parcel, if such a zone exists; else ask.
Validate with Pydantic; if the zone doesn't exist → `ok=false` with `missing_zone_label` and a question ("Desk 14 ka area camera pe draw kar dijiye"). Then **replay**: evaluate on the last 24 h (or data coverage if older) using the same `evaluate_track`; store `replay = {window_from, window_to, count, hits:[{track_id, t, actor_track_id?}] (max 20)}`; return `RuleDraft {rule_id, human, spec, replay, active:false}`.

---

## 11. Web app (`web/`)

**Stack:** Next.js (latest stable, App Router, TypeScript) with `output: 'export'` (fully static, deployable to Amplify/S3), Tailwind CSS, `lucide-react` icons. No server components that need a Node server. API base URL from `NEXT_PUBLIC_API_BASE_URL`. Token stored in localStorage after the passcode screen.

**Design:** phone-first (375–430 px) but good on desktop (max-width centered column + side panel). Messenger feel (Equal AI's product is an AI messenger): clean white, deep blue `#0B5FFF` primary, lime accent `#D4F53C` for the mic button, rounded-2xl cards, Inter font. Dark mode optional. Every screen has loading, empty and error states.

**Evidence level badges** (must differ by more than colour — SETU rule): Confirmed = solid green pill, filled dot, text "Confirmed"; Probable = amber pill, half-filled dot, "Probable"; Candidate = grey **dashed outline** pill, hollow dot, "Candidate · check this". A Candidate card is visually quieter and never placed first above a Probable/Confirmed item.

**Screens:**
1. `/login` — passcode.
2. `/` **Chat (main screen):**
   - Top bar: "Nazar" logo, camera picker (All / each camera with live dot), link to Cameras, Rules, Metrics.
   - Thread: user bubbles (text or "🎤 voice note 0:04" with transcript under it), Nazar bubbles containing: `reply_text`; audio player (auto-plays after a user-initiated ask; see audio note); a **count card** (big number, label, Confirmed badge, mini hourly bar chart in inline SVG); **clip cards** (thumbnail → tap opens the clip player: `<video>` + `<canvas>` overlay drawing the tracked box from `path` synced to `currentTime`; time, camera, level badge, `why` text, "Find again" button → similar search results in a sheet); **rule card** (human sentence, trigger chips, "Would have fired N times in the last 24 h" + up to 4 hit thumbnails, **Activate** button); followup chips; offline-gap note.
   - Live alerts arrive as special red-bordered bubbles via WebSocket (snapshot, message, audio, "Open clip", "Acknowledge").
   - Composer: big lime **mic button** (tap to start, tap to stop; shows a live timer and level meter; max 30 s), text input, send. Suggested question chips on an empty thread (in Hinglish and English): "Aaj kitne log aaye?", "Raat 2 baje ke baad counter pe kaun aaya?", "Show people carrying a bag", "Jab bhi koi gate pe aaye, mujhe batana".
   - **Audio note:** browsers block autoplay without a gesture. Unlock audio on the first tap anywhere (play a silent buffer). Show a "🔊 Sound on" toggle; if autoplay fails, show a tap-to-play button.
   - Recording: `MediaRecorder` with the best supported mimeType (`audio/webm;codecs=opus`, else `audio/mp4`); send as multipart with a matching filename extension. Microphone requires HTTPS or localhost — show a clear message otherwise.
3. `/cameras` — camera cards: live MJPEG thumbnail, status (Live / Offline since …), today's count, coverage window. "Add camera" button.
4. `/cameras/new` — three tabs: **Upload a video** (drag-and-drop or file picker, name, optional "recorded at" time; shows an upload progress bar, then processing progress from `/progress`, then "Ready — ask about it" which opens the chat filtered to this camera), **Phone** and **CCTV / RTSP URL** (name + URL → Start). Every camera card has Start/Stop buttons via the edge manager. For **Phone**: shows the exact Larix Broadcaster connection URL (`srt://<host>:8890?streamid=publish:<id>` and `rtmp://<host>/<id>`), a QR code of it (`qrcode` npm package), and step-by-step setup text; the camera source is then `rtsp://<MEDIAMTX_HOST>:8554/<id>`. A Start button launches its edge via the edge manager.
5. `/cameras/[id]` (static export → use `/camera?id=` query param instead of dynamic routes) — live view (MJPEG), **zone editor**: snapshot image with an SVG overlay, click to add polygon points, drag points, name each zone (name auto-slugified, label free text), delete, "Suggest zones with AI" (fills editable suggestions), Save. Below: today's hourly timeline chart, recent tracks strip (thumbnails, caption, time), offline gaps.
6. `/rules` — list: human sentence, active toggle, replay count, last alert; create rule by text or voice (same composer) → rule card with replay → Activate.
7. `/metrics` — "Cost per camera-day: ₹X" (big), vs. naive "₹Y if every frame went to AI" with the ratio ("Nz× cheaper"), spend by kind, tracks processed, enrichment backlog, ask latency p50/p90, evidence-level distribution of answers. Plus the eval numbers from `scripts/eval_*` if present (`data/eval/latest.json`).

`npm run build` and `npm run lint` must pass with zero errors. Type everything (`web/lib/types.ts` mirrors API schemas).

---

## 12. Live ingest (MediaMTX) and recordings

`infra/mediamtx.yml`: SRT on 8890/udp, RTMP on 1935, RTSP on 8554, HLS off (we serve blurred MJPEG ourselves), `paths: all_others:` with `record: yes` **only** when `RECORD_RAW=1` (overnight raw recording to `/recordings/%path/%Y-%m-%d_%H-%M-%S-%f`, fmp4, segment 10 min) so raw footage can be reprocessed later.

Docker dev compose maps ports 8554/tcp, 1935/tcp, 8890/udp and mounts `data/recordings`.

**Phone camera (Larix Broadcaster):** Settings → Connections → New: URL `srt://<laptop-or-EC2-host>:8890?streamid=publish:<camera_id>` (or `rtmp://<host>/<camera_id>`); Video 1280×720, 15 fps, 2–3 Mbps, H.264. Document in DEPLOY.md and in the Add Camera screen. Note: venue Wi-Fi may isolate clients; streaming to the EC2 public IP avoids that. Windows Firewall must allow the ports for laptop-hosted MediaMTX.

`scripts/process_recordings.py --camera <id> --dir data/recordings/<id>`: for each recorded file in time order, parse the start time from the filename and run the edge pipeline with `--source <file> --start-time <parsed> --fast`.

---

## 13. Security and robustness
- Camera URL validation: allowed schemes `rtsp, rtsps, srt, rtmp, file path inside the repo's samples/ or data/recordings/`; reject `http(s)` and any host resolving to link-local/metadata (`169.254.0.0/16`), and reject private ranges except `localhost`/`MEDIAMTX_HOST`.
- Never log secrets; redact tokens in logs.
- `.env` never committed; `.env.example` complete.
- All SQL parameterized.
- Timeouts: OpenAI 60 s, ffmpeg 60 s, DB statement timeout 15 s.
- Every background loop survives exceptions and logs them.
- If the DB is down, the API returns 503 and the edge buffers up to 60 s of upserts in memory then drops with a warning.

---

## 14. Scripts
- `scripts/check_env.py` — Python packages, torch CUDA, ffmpeg/ffprobe on PATH, DB connection + extensions, data dir writable, models downloaded, OpenAI key present, S3 reachable when `STORAGE_MODE=s3`, disk space. Prints a ✅/❌ table.
- `scripts/check_models.py` — §1.
- `scripts/download_models.py` — `yolo11n.pt` (via ultralytics) and YuNet ONNX (GitHub opencv_zoo); `--export-cpu` exports OpenVINO/ONNX.
- `scripts/demo_setup.py --manifest samples/demo_manifest.yaml [--reset]` — per §0.1: creates each camera (with per-camera settings such as upscale for low-res clips), creates zones (AI suggestions if a key exists, else default boxes: centre "counter", left "entrance"), runs the edge with `--fast --start-time <manifest time>` for every clip, waits for the worker to finish eventizing/enriching (progress bar), then prints 8 sample questions that have real answers on this data. `--reset` deletes previous demo data first. Idempotent.
- `scripts/fetch_samples.py` — re-downloads clips listed in `samples/sources.yaml` and normalizes them (§0.1).
- `scripts/live_from_file.ps1 <clip> <camera_id>` — loops a clip into MediaMTX over RTSP (§0.1).
- `scripts/demo_live.ps1` — starts camera `live-demo` from `samples/clip6_bag.mp4` (or `staged_bag.mp4` if present) using `--simulate-live --loop` (a recorded clip acting as a live camera, for live alerts when no phone stream is available).
- `scripts/eval_counts.py --camera demo --zone counter --from --to --truth 37` → prints and saves count accuracy.
- `scripts/eval_search.py --file scripts/eval/questions.yaml` → for each question with ground-truth time windows, calls `/api/ask` (text), checks whether a returned clip overlaps the truth window in the top 3; reports hit@3, confidently-wrong rate (Confirmed/Probable items overlapping no truth window), avg latency; saves `data/eval/latest.json`.
- `scripts/cost_report.py` — prints ₹ per camera-day and the naive baseline (same logic as `/api/metrics`).
- `scripts/smoke.ps1` — starts nothing; assumes services run; hits health, cameras, a text ask, a rule compile, metrics; prints PASS/FAIL.
- `scripts/eval/questions.yaml` — template with 5 example entries and comments explaining how to fill truth windows by watching the sample.

---

## 15. Deployment kit (`infra/`) — write everything; do NOT create AWS resources without the user's yes

- `Dockerfile.backend` (python:3.12-slim + ffmpeg + libgl, CPU torch `--index-url https://download.pytorch.org/whl/cpu`, then requirements; one image used for api, worker and edge with different commands).
- `docker-compose.prod.yml`: `mediamtx`, `api` (also runs the edge manager, which spawns edge processes inside the same container; set `MAX_EDGES=3` on EC2), `worker`, `caddy` (reverse proxy + automatic HTTPS). Optional `postgres` service under a profile (fallback if RDS isn't used). Volumes for `data/`.
- `Caddyfile`: `{$DOMAIN}` → `/api/*`, `/media/*` → api:8000 (WebSocket upgrade works by default). Domain = `<EC2-public-IP-with-dashes>.sslip.io` so HTTPS works without buying a domain.
- `infra/DEPLOY.md` — console click-steps, in order, PowerShell-friendly:
  1. **S3:** create bucket `nazar-media-<random>` in us-west-2, block public access ON, lifecycle rule "delete after 7 days".
  2. **IAM instance role** `nazar-ec2-role` with a policy limited to that bucket (Get/Put/Delete/List) — attach to the EC2 instance. No workshop keys on the server.
  3. **Security groups:** `nazar-ec2-sg` inbound 22 (My IP), 80, 443 (anywhere), 8890/udp SRT, 1935 RTMP (anywhere; streams require a publish path); `nazar-db-sg` inbound 5432 only from `nazar-ec2-sg`.
  4. **RDS:** PostgreSQL 16, Free-tier/Dev template, `db.t4g.micro`, 20 GB gp3, no public access, `nazar-db-sg`, initial DB `nazar`. After creation: `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;` (migration does this) — RDS supports pgvector.
  5. **EC2:** ONE instance, Ubuntu 24.04, **c7i.xlarge** (4 vCPU, 8 GB, CPU only), 60 GB gp3, `nazar-ec2-sg`, role `nazar-ec2-role`, a key pair. Allocate an Elastic IP (stable URL).
  6. SSH in → install Docker → clone repo → create `.env` (prod values: RDS `DATABASE_URL`, `STORAGE_MODE=s3`, `S3_BUCKET`, `DOMAIN`, OpenAI key, `WEB_ORIGINS` = Amplify URL) → `docker compose -f infra/docker-compose.prod.yml up -d --build` → run migrations → `python scripts/download_models.py --export-cpu` inside the container.
  7. **Web on Amplify Hosting:** `cd web; $env:NEXT_PUBLIC_API_BASE_URL="https://<domain>"; npm run build` → zip `web/out` → Amplify console → "Deploy without Git" → upload zip. (Or connect the GitHub repo with build settings `npm ci && npm run build`, artifacts `web/out`.)
  8. Phone → Larix → `srt://<elastic-ip>:8890?streamid=publish:hall-1`; add camera `hall-1` in the web app with source `rtsp://mediamtx:8554/hall-1` and press Start.
  9. **Guardrails checklist:** one EC2, no GPU, no Bedrock, budget alert set, stop RECORD_RAW when not needed, tear down after the event.
- Local dev compose (`infra/docker-compose.yml`): `postgres` (`pgvector/pgvector:pg16`, user/pass/db `nazar`, port 5432, volume, `mem_limit: 1g`) and `mediamtx` (`bluenviron/mediamtx`, ports above, `mem_limit: 256m`).

---

## 16. Milestones (build in this order; each ends with checks that must pass)

**M0 — Bootstrap**
Repo layout, `pyproject.toml`, venv instructions (`python -m venv .venv; .\.venv\Scripts\Activate.ps1`; torch cu121 first; `pip install -e backend`), `.claude/settings.json` with `{"includeCoAuthoredBy": false}`, git identity check (§19), config, logging, db pool, migration runner + `001_init.sql`, dev docker-compose, `.env.example`, `check_env.py`, `check_models.py`, `download_models.py`, `PROGRESS.md`.
Also: the footage plan in §0.1 (6 clips downloaded, normalized, inspected, SOURCES.md, sources.yaml, fetch_samples.py, demo_manifest.yaml).
✅ `samples/clip1..5.mp4` and `samples/clip6_bag.mp4` exist and pass ffprobe + visual check → `docker compose -f infra/docker-compose.yml up -d` → `python -m nazar.core.migrate` succeeds → `python scripts/check_env.py` all green (OpenAI items may be yellow if no key) → `python scripts/check_models.py` (if key present) all OK or fallback suggested.

**M1 — Core library + unit tests**
geometry, eventizer, rules (RuleSpec, evaluate_track, evaluate_count), levels, appearance, timeutil, prices, storage, usage.
✅ `pytest backend/tests -q` green: eventizer hysteresis/boundary jitter; enter/exit/dwell; each trigger incl. object_removed with/without nearby person; count_over cooldown; time windows across midnight; level assignment table; appearance determinism; stitcher logic (pure function part).

**M2 — Edge pipeline on a file**
All of §7.
**Self-review (the user will not check this; you must):** extract ~8 frames from each preview and from 3 random segments and crops into `data/inspect/` as PNG and look at them with your image-reading tool. Check: boxes sit on the right objects, IDs stay stable while a person walks, faces are blurred, nothing is upside-down/stretched, timestamps are right. If anything is wrong, fix it (thresholds, upscale, blur padding, class filters) and re-run before moving on. Do the same visual self-review for the web app in M6/M9 using the Playwright screenshots, and fix layout problems you see.
✅ `python -m nazar.edge.run --camera demo --source samples/clip1.mp4 --start-time "<yesterday 22:30>" --fast --preview` processes the whole clip; `data/preview_demo.mp4` shows stable IDs and blurred faces; DB has tracks (active=false at end), segments covering the clip with no gaps, camera_status rows; crops exist and are blurred. Print a summary (frames, detection fps, tracks, segments). Measure and log detection fps on CUDA.

**M3 — Worker**
eventize loop, zones re-eventize on change, stitcher, enricher, alerts builder, retention, rules loop.
✅ With demo data: events exist for default zones; editing zones (SQL update) re-eventizes; enricher fills captions/attrs/embeddings (needs key); usage rows with costs; stitcher merges at least the synthetic test case; a manually inserted active rule on the demo data produces alerts with TTS audio.

**M4 — API (non-agent)**
Auth, cameras, snapshot, MJPEG, zones, suggest-zones, timeline, gaps, search, count, tracks, similar, clips (with path), rules CRUD, alerts, WS, metrics, media.
✅ `pytest backend/tests/test_api_smoke.py` (TestClient against the dev DB with demo data) green; upload a clip not in the manifest via the API → progress reaches `ready` → asking about it works; start/stop an edge through the API; manual: open a clip URL in the browser and it plays; MJPEG works while an edge runs.

**M5 — Agent, voice, rule compiler**
§10 fully.
✅ Text asks return correct structure: "Aaj kitne log aaye?" → count with series (Confirmed); "Kisi ne bag pakda tha?" → clips with levels; "Jab bhi koi counter pe aaye mujhe batana" → rule draft with replay count; voice: post a recorded webm/m4a → transcript + answer + audio_url; latency logged; the model cannot inject levels (test: a tool result with candidate stays candidate).

**M6 — Web app**
§11 fully.
✅ `npm run build` + `npm run lint` clean; local run against the API: login → ask by text and by voice (Chrome on localhost) → count card, clips with box overlay, find-again, rule card → activate → live alert bubble arrives (use `scripts/demo_live.ps1` with a clip where a person enters a zone) → metrics page shows ₹/camera-day.

**M7 — Live ingest**
MediaMTX config, phone instructions, Add Camera screen with QR, edge on RTSP from MediaMTX, reconnect logic, RECORD_RAW, `process_recordings.py`, `demo_live.ps1`.
✅ `scripts/live_from_file.ps1 samples/clip2.mp4 cam1` (or a phone via Larix) → edge on `rtsp://localhost:8554/cam1` → live snapshot updates → tracks appear within 2 s → an active zone_enter rule alerts in the web app within ~5 s.

**M8 — Deploy kit**
§15 files and DEPLOY.md. Build the backend image locally to prove the Dockerfile works (`docker build -f infra/Dockerfile.backend .`). Static web export builds. **Do not create AWS resources** — present DEPLOY.md steps to the user and wait.
✅ Image builds; `docker compose -f infra/docker-compose.prod.yml config` validates; `web/out` exists.

**M9 — Eval, demo polish, docs**
eval scripts (run them on the demo data and save results), questions template, cost report, smoke script, screenshots, **README exactly per §22**, `docs/architecture.md`. Update CLAUDE.md to match this spec. Final QA pass (§17).
✅ `scripts/smoke.ps1` PASS; README complete per §22 with real measured numbers (or clearly marked "run `python scripts/cost_report.py` to fill" if no key yet) and real screenshots; `git status` clean after commit.

---

## 17. Final QA checklist (run at the end, fix everything that fails)
- [ ] Fresh clone → follow README locally → works end to end on `samples/clip1.mp4`.
- [ ] No secrets in git history (`git log -p | Select-String "sk-"` finds nothing).
- [ ] Every OpenAI call writes a `usage` row; `/api/metrics` totals match the sum.
- [ ] Faces blurred in: crops, segments/clips, snapshots, MJPEG, alert snapshots (inspect 5 random files).
- [ ] Counts in answers equal direct SQL counts for the same window.
- [ ] A Candidate never appears styled as Confirmed/Probable and never first above them.
- [ ] Offline gap shown when the edge was stopped for a while.
- [ ] Rule replay count equals the number of alerts produced when the same footage is re-run with the rule active.
- [ ] Hindi (Devanagari), Hinglish and English questions each get a reply in the same language/script, with TTS audio.
- [ ] Mobile layout at 390 px: no horizontal scroll, mic button reachable, clip player full width.
- [ ] Killing and restarting edge/worker/api does not corrupt data (idempotent loops, unique constraints).
- [ ] `npm run build`, `npm run lint`, `pytest` all green.
- [ ] PROGRESS.md has run instructions for: dev services, edge (file, simulate-live, RTSP), worker, api, web, demo setup, eval, deploy.

---

## 18. Run commands (put in README and PROGRESS.md)
```powershell
# one-time
docker compose -f infra/docker-compose.yml up -d
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -e backend
python -m nazar.core.migrate
python scripts/download_models.py
python scripts/check_env.py; python scripts/check_models.py

# demo data (recorded clip stamped as last night)
python scripts/demo_setup.py --manifest samples/demo_manifest.yaml

# services (separate terminals)
python -m nazar.worker.run
uvicorn nazar.api.main:app --host 0.0.0.0 --port 8000
cd web; npm install; npm run dev        # http://localhost:3000

# live camera options
python -m nazar.edge.run --camera live-demo --source samples/clip6_bag.mp4 --simulate-live --loop
python -m nazar.edge.run --camera hall-1   # source rtsp://localhost:8554/hall-1 from MediaMTX (phone via Larix)
```

**Build it completely, verify every milestone, keep PROGRESS.md current, and commit after each milestone.**


---

## 19. Git rules (follow exactly)
- Remote: `https://github.com/Shivansh0911/Nazar.git` (branch `main`). If the local repo has no `origin`, add it. Pushing uses the user's existing Git credentials on this machine; if a push fails for auth, tell the user once and keep committing locally.
- **Author identity = the user only.** Before the first commit, check `git config user.name` and `git config user.email`. If they are empty or not the user's GitHub identity, ask the user once for their GitHub name/email (or the GitHub noreply address `<id>+Shivansh0911@users.noreply.github.com`) and set them with `git config` **for this repo**. Never commit with any other identity.
- **No AI attribution anywhere in git:** no `Co-Authored-By:` trailers, no "Generated with Claude Code" lines, no bot/assistant names in commit messages, branch names, tags or PR text. Make sure `.claude/settings.json` in the repo contains `{"includeCoAuthoredBy": false}` (create or merge it; keep other keys).
- **Smart commits:** commit a coherent, working unit of work (a milestone, or a meaningful sub-part of one) — not every small edit, and never a broken build on `main`. Run the relevant checks before committing. Use Conventional Commit messages in plain human style, imperative mood, ≤ 72-char subject, optional short body explaining why:
  `feat(edge): track objects with ByteTrack and store 5 Hz paths` · `feat(worker): derive zone events from trajectories` · `fix(api): clip cutting across segment boundaries` · `test(core): cover rule evaluator edge cases` · `docs: deployment runbook for EC2 and RDS` · `chore: download and normalize sample clips`.
- Push after each milestone commit (and at least every ~45 minutes of work).
- Never commit: `.env`, keys, `data/`, `samples/*.mp4`, model weights, `node_modules`, `.venv`, build output. Before every commit run `git status` and check the staged list. Before the final commit run a secret scan (`git grep -nE "sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|aws_secret_access_key"` must find nothing).

## 20. Verifying what cannot run yet
Some things may be impossible to run in a session (missing key, expired AWS credentials, no phone stream). For each such part:
- Write the real implementation fully — no placeholders, no TODOs, no "implement later".
- Unit-test the plumbing with a **test-only stub** of the OpenAI client (in `backend/tests/fakes.py`, never imported by product code) that returns schema-valid responses, so request building, parsing, cost logging, error handling and fallbacks are exercised.
- Add a real-call test marked `@pytest.mark.live` that runs automatically when `OPENAI_API_KEY` is set.
- Validate external configs statically: `docker compose config`, `caddy validate` (via the caddy image), ffmpeg command dry-runs on a 2-second clip, `python -m py_compile` on everything, `npm run build`.
- List in PROGRESS.md under "Needs the user's env to verify", with the exact command to run later.
When the user later adds the missing env values, running `python scripts/check_env.py`, `python scripts/check_models.py`, `pytest -m live` and `scripts/smoke.ps1` must be all that is needed to confirm everything works.

## 21. Definition of complete (do not stop before every box is true)
**Priority if time gets short** (code freeze Sun 2 PM IST): finish in this order and never leave the build broken: M0–M2 → M3 (eventize, enricher, rules, alerts) → M4 → M5 → M6 → M7 → M9 docs → M8 deploy kit → nice-to-haves (stitcher, find-again, suggest-zones, metrics eval numbers). Nice-to-haves still get built if time allows.
- [ ] All milestones M0–M9 done with their checks passing (or listed under §20 with the exact verification command).
- [ ] Demo dataset from the 6 downloaded clips is processed, zoned, enriched; demo_setup prints questions that really work.
- [ ] Ask by text and by voice works in Hindi, Hinglish and English with counts, clips, levels, TTS.
- [ ] Rule by voice/text → replay with clips → activate → live alert (via `--simulate-live` and via RTSP `live_from_file.ps1`) in the web app with audio.
- [ ] Any real camera can be added (RTSP/SRT/RTMP/phone with QR instructions) and started from the UI; any uploaded video (including a judge's) is processed and can be questioned.
- [ ] Metrics page shows ₹ per camera-day vs naive, from real usage rows.
- [ ] Faces blurred everywhere; retention job works; secrets never committed.
- [ ] `pytest`, `npm run lint`, `npm run build`, `docker build`, `docker compose config` all pass.
- [ ] No `TODO`, `FIXME`, `NotImplementedError`, `pass  # later` or placeholder text left (`git grep` check).
- [ ] Every endpoint the web app calls exists, and request/response types match (`web/lib/types.ts` ↔ `nazar/core/schemas.py`).
- [ ] README and infra/DEPLOY.md complete; PROGRESS.md ends with a "Final status" section: what works, how to run the demo in 5 commands, and anything needing the user's env.
- [ ] Final commit pushed to `origin/main` under the user's identity with no AI attribution.
- [ ] `FINAL_STEPS.md` written per §23, committed, and printed as the final message.

## 22. README.md (make it excellent — judges and reviewers read it first)
Write it like a top open-source project, in clear English, scannable, no fluff, no emoji walls. Every claim must be true of the code; every number must come from a script output (`cost_report.py`, `eval_counts.py`, `eval_search.py`, edge fps logs) with the date measured — if a number is not measured yet, show "—" and the command that produces it. Sections, in order:
1. **Title + one-liner:** "Nazar — ask your CCTV anything, in your own language." A short tagline under it, and badges (Python, Next.js, OpenAI, AWS, licence).
2. **Hero screenshot / GIF:** `docs/screenshots/chat.png` (generated by `scripts/screenshots.mjs` using Playwright against the running app with demo data: chat with a count card + clips, rule card with replay, live alert, camera zones, metrics). Optionally a short GIF of ask → answer → clip.
3. **The problem** (3–4 lines): Indian shops/homes/societies already paid for CCTV; nobody watches it; owners scrub hours of footage on a DVR.
4. **What Nazar does:** Ask · Teach · Alert · Find again — one line each with a real example question in Hinglish and its real answer from the demo data.
5. **Demo in 60 seconds:** the 5 commands to run it locally (§18) and the 8 sample questions printed by demo_setup.
6. **How it works:** Mermaid architecture diagram (edge → Postgres/pgvector → worker → API → web; OpenAI calls marked), then short subsections: *Trajectories are the truth* (paths → events, retroactive zones/rules), *Evidence levels* (table: Confirmed / Probable / Candidate with exact rules, and "the model can never upgrade a level"), *Replay before you trust a rule*, *Cost by design* (CV on every frame, AI on 1–3 crops per track; ₹ per camera-day vs. naive with the ratio), *Privacy by design* (face blur everywhere, no face recognition, crops only, 7-day retention).
7. **Where OpenAI is used:** table — model (from env), job, when it's called, measured cost share.
8. **Where AWS is used:** table — EC2 (CPU only), RDS Postgres + pgvector, S3 (7-day lifecycle), Amplify, IAM instance role; and the guardrails (no GPU, no Bedrock, one instance, budget alert).
9. **Measured results:** table — detection fps (laptop GPU / EC2 CPU), count accuracy, search hit@3, confidently-wrong rate, ask latency p50/p90, ₹ per camera-day, naive ₹ per camera-day, ratio. With "measured on <date> on <data>".
10. **Connect a real camera:** phone (Larix SRT/RTMP + QR), CCTV DVR (RTSP URL format examples for common Indian DVR brands, e.g. `rtsp://user:pass@ip:554/...`), upload a video.
11. **Run it yourself:** prerequisites, env vars table (name, purpose, default, secret yes/no), local setup, deploy summary linking `infra/DEPLOY.md`.
12. **API reference:** compact table of endpoints.
13. **Project structure:** short tree.
14. **Honest limitations:** e.g. occlusion and crowded scenes, night/IR footage quality, ID switches (mitigated by the stitcher), low-res sources, attribute errors from the vision model (hence levels).
15. **Roadmap:** Nazar as a Camera Agent inside Equal's AI messenger (ask over chat/voice note, alerts as messages and calls), an on-site box beside the DVR so video never leaves the premises, multi-camera journeys (SETU-style), homes, housing societies, clinics.
16. **Built on / credits:** SETU lineage (2 lines), open-source libraries, and every sample clip's source and licence (link `samples/SOURCES.md`).

## 23. Final handoff (the last thing you do)
The user will not check intermediate milestones; they only act at the very end. When §21 is satisfied (or time runs out), create `FINAL_STEPS.md` in the repo root, commit it, and also print it as your final message. It must be short, exact and in this order:
1. **Paste these into `.env`** — a table of every empty secret (`OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `S3_BUCKET` if deploying) with where to get each one (OpenAI dashboard → API keys; Workshop page → Get AWS CLI credentials; S3 bucket name after DEPLOY step 1).
2. **Run these checks** (copy-paste PowerShell, in order): `check_env.py`, `check_models.py`, `pytest -m live`, `demo_setup.py --manifest samples/demo_manifest.yaml` (if enrichment needed a key), `smoke.ps1` — with what "success" looks like for each and what to do if one fails.
3. **Start the demo locally** — the exact terminals/commands (or one `scripts/start_all.ps1` that you write, opening each service in its own window) and the URL + passcode.
4. **Demo script for judges** — 6–8 steps with the exact questions to ask (Hinglish + English), which camera to pick, the rule to create, and how to trigger the live alert (`demo_live.ps1` / `live_from_file.ps1`).
5. **Deploy to AWS** — pointer to `infra/DEPLOY.md` with the 3 things the user must decide/click; nothing that Claude ran without permission.
6. **Fill the README numbers** — `python scripts/cost_report.py` and the eval commands; then commit and push.
7. **Submission checklist** — repo link, demo (deployed URL or recording), 4–5 slides (problem, what we built, how it works, what's next) with the README sections to copy from.
8. **Known issues** — anything not verified, with the command that verifies it.

