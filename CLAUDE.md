# Nazar — ask your CCTV anything

Hackathon project (Builders 2026, Equal AI × OpenAI). Solo build. **Code freeze: Sunday 22 Nov 2026, 2:00 PM IST.**
Speed matters more than polish. Working end-to-end beats perfect parts. Ship each phase working before starting the next.

> **v2 (BUILD_PROMPT_V2.md) is the current spec** and wins over v1 on conflicts. Resume from PROGRESS.md (v2 section).

## What we are building
Any camera (phone stream, shop DVR over RTSP, or a video file) becomes something you can talk to:
1. **Ask:** owner sends a voice note in Hindi/English/Hinglish ("Raat 2 baje ke baad counter pe kitne log aaye?") → answer + count + exact clips, each with an evidence level.
2. **Teach:** "Jab bhi koi desk 14 se bag uthaye, mujhe batana" → compiled into a watch rule → **replayed on past footage first** → then runs live → alert as a voice note.
3. **Cheap:** cheap CV code watches every frame; OpenAI only sees 1–3 crops per track + the owner's questions. Cost = paise per camera-day. We measure and show this.

Design lineage: the author's previous project SETU (vehicle search without number plates). Same ideas: edge detection, appearance fingerprints, pgvector search, honest evidence levels, "replay first".

## Architecture (v2)
```
file  → ffmpeg samples 5 fps → batched GPU YOLO11s → ordered ByteTrack → 5 Hz paths (+ head boxes) ┐ no re-encode:
live  → OpenCV decode → same detector/tracker (+ YOLOE for taught objects) → blurred 10 s segments ┘ originals kept
      → crops (blurred at cut + YuNet) + keyframes every 2 s (blurred) → Postgres + pgvector
vision service (SigLIP 2, GPU) → indexes crops + keyframes locally (Rs 0) → visual search / photo search / journey
worker → eventizer (zones + count lines) → rules/alerts → stitcher → security detectors (+ Flex AI check) → digest
agent (luna first, sol on escalation, SSE streaming) → tools: count_events (receipts), analytics_query (read-only
      views), visual_search (+AI verify), journey, describe_clip, look_now, compare, heatmap, list_events,
      create_rule, teach_object (YOLOE), make_report (PDF) → answer + evidence panel + TTS
Telegram bot (long polling) → same agent; alerts pushed with snapshot + clip + voice note
```

## Repo layout
See BUILD_PROMPT.md section 3 (backend/nazar/{core,edge,worker,api}, web/, infra/, scripts/, samples/, data/). BUILD_PROMPT.md is the full spec and wins on any conflict.

## Stack (do not swap without asking)
- Python 3.12, one venv (`.venv`) with the `backend` package installed editable. `ultralytics` (YOLO11n, ByteTrack via `model.track(persist=True, tracker="bytetrack.yaml")`), `opencv-python` (YuNet face detector for blur), `psycopg[binary]`, `pgvector`, `fastapi`, `uvicorn`, `openai`, `pydantic`, `python-dotenv`, `boto3`.
- Detection classes (COCO): person, car, motorcycle, bicycle, backpack, handbag, suitcase, laptop, cell phone, bottle.
- ffmpeg for segments and clip cutting. MediaMTX for SRT/RTMP/RTSP ingest; the web shows a face-blurred MJPEG from the API (no HLS).
- Postgres 16 + `vector` + `pg_trgm`. Local: docker image `pgvector/pgvector:pg16`. Prod: AWS RDS.
- Next.js (App Router, static export) + Tailwind, `MediaRecorder` for voice notes, WebSocket for alerts.
- Dev machine: Windows 11, 8 GB RAM, i5-13420H, NVIDIA RTX 4050 Laptop 6 GB, driver 546.18 (max CUDA 12.3). Install PyTorch with the **cu121** wheel (`pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121`), never a newer CUDA build. Use CUDA for YOLO if `torch.cuda.is_available()`, else CPU. Keep RAM use low (Docker capped ~3 GB). Commands must work in PowerShell. Installed: Python 3.12.5, Node 20.14, npm 10.7, Docker 29.7, ffmpeg 9.1 (has SRT + NVENC), AWS CLI 2.42.
- The local GPU is the developer's own laptop and is fine to use. GPUs on AWS are forbidden.
- Prod: ONE AWS EC2 CPU instance (Ubuntu) for mediamtx + edge + api; RDS Postgres; S3; Amplify for web. Region us-west-2.

## Config (.env, never commit, never print values)
```
OPENAI_API_KEY=
OPENAI_VISION_MODEL=gpt-6-luna          # cheap vision for track captions; fallback gpt-5.4-mini if unavailable
OPENAI_AGENT_MODEL=gpt-6-sol            # query agent, rule compiler, zone suggestion
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_TRANSCRIBE_MODEL=gpt-4o-transcribe
OPENAI_TTS_MODEL=gpt-4o-mini-tts
DATABASE_URL=postgresql://nazar:nazar@localhost:5433/nazar   # 5433: another local Postgres uses 5432
STORAGE_MODE=local          # local | s3
S3_BUCKET=
AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
API_BASE_URL=http://localhost:8000
```
Read model names ONLY from env. Never hardcode a model name. Provide `.env.example` with empty secret values.
Write a `scripts/check_models.py` early that makes one tiny call to each configured model (vision with a small image, agent, embed, transcribe, TTS) and prints OK/FAIL, so a bad model name is caught before it breaks a phase.
Use the Responses API with Structured Outputs for vision/agent calls. Use prompt caching (stable system prompts first) to cut cost.
AWS keys are temporary workshop credentials and expire; on an auth error, tell the user to refresh them from the Workshop page.

## Data model
- `cameras(id, name, source_url, kind, zones jsonb, settings jsonb, ...)` — zones = `[{name, label, polygon:[[x,y],...] normalized 0..1}]`
- `tracks(... path jsonb (5 Hz normalized boxes), zone_path, crops, appearance vector(76), caption, attrs, caption_emb vector(1536), merged_into ...)` — full schema in BUILD_PROMPT.md section 5. Trajectories are the truth; events are derived from paths by one eventizer.
- `events(id, camera_id, track_id, type, zone, t, meta jsonb)` — type ∈ enter, exit, dwell (derived from paths; object_removed is a rule trigger, not an event)
- `segments(camera_id, t_start, t_end, key)`
- `rules(id, camera_id, text, spec jsonb, active, replay jsonb, created_at)`
- `alerts(id, rule_id, track_id, t, clip_key, ack)`
- `queries(id, text, plan jsonb, answer jsonb, latency_ms, cost_usd, created_at)`
- `usage(...)` — EVERY OpenAI call writes a row. `jobs(...)` — upload/demo processing progress.
All timestamps are real wall-clock (timestamptz). For files, wall clock = configured start time + PTS. Never derive time from a declared fps.

## Hard rules
1. **Counts come from SQL, never from a model — and every count carries its receipts** (the counted tracks).
   "People seen" = root tracks >= 1.5 s with max confidence >= 0.6. Line crossings count entrances.
2. **Evidence levels (decided only in server code):** Confirmed = tracker/database fact. Probable = local similarity
   AND an independent check agree (attributes, or a RECORDED AI verification "yes"). Candidate = similarity or a
   heuristic only. A Candidate is never presented as an answer and never styled like Confirmed. If nothing matches, say so and list hours the camera was offline.
3. **Privacy (v2: blur at egress):** raw originals stay on the owner's machine and are never served or sent.
   Everything that leaves the pipeline (crops, keyframes, clips, live view, snapshots, PDFs, Telegram media) is
   face-blurred when it is produced (stored head boxes + YuNet). OpenAI sees only blurred crops / a few blurred
   keyframes (detail low) and the owner's questions. No face recognition, ever: photo search compares clothes,
   objects and vehicles; a face-only photo is refused; every photo search is audited with its purpose.
4. **Cost:** indexing is local (YOLO + SigLIP 2, Rs 0). Captions are on demand (`ENRICH_MODE=smart`), background
   vision uses the Flex tier with fallback. Every call writes a `usage` row (incl. `service_tier`). The UI shows
   measured unit costs (per question / verification / report / caption).
5. All LLM outputs that drive code use Structured Outputs (JSON schema) + Pydantic validation. Rule specs are validated before saving.
6. **AWS guardrails:** never launch GPU instances (g*, p*, inf*, trn*), never use Bedrock, never create more than one EC2 instance, never run an AWS command that creates/deletes resources without showing it to the user and getting a yes. Prefer giving the user console steps.
7. Never commit `.env`, keys, samples > 50 MB, or `data/`.
8. Keep it simple: no auth system beyond a single demo passcode, no microservices, no Kubernetes, no queues beyond a DB table/polling.

## Watch rule spec
```json
{"camera":"hall-1","trigger":"zone_enter|zone_exit|dwell_over|count_over|object_removed",
 "cls":"person|car|backpack|...","zone":"desk_14","dwell_s":60,"count":5,
 "time_window":{"from":"22:00","to":"07:00"},
 "confirm_with_vision":"optional sentence checked on one crop before alerting",
 "notify":"voice_note"}
```
Flow: compile (LLM) → validate → show human-readable card → replay last 24h of events (return hits + clips) → user activates → live evaluation on new events → optional vision confirm → alert.
`object_removed`: a stationary object track disappears from a zone while a person track overlaps it. If unreliable, fall back to zone_exit + vision confirm.

## Machine notes
- v2: transformers must stay < 4.52 (torch 2.5.1+cu121). SigLIP 2 runs in `python -m nazar.vision.service` (:8010).
- v2: the vision service uses ~2.8 GB private memory while loaded; it unloads after 3 idle minutes.
- `DATA_DIR` on this laptop is outside OneDrive (`C:/Users/ssojh/AppData/Local/Nazar/data`).
- OpenCV must stay < 5 (YuNet is ~5x slower on 5.x); Tailwind pinned to 4.1.11 (Node 20.14).
- 8 GB RAM: run at most one or two edges at once.

## Build plan
Follow BUILD_PROMPT.md milestones M0-M9. After each: run its checks, update PROGRESS.md, commit. When resuming, read PROGRESS.md first.

## Git (every session)
- Remote `https://github.com/Shivansh0911/Nazar.git`, branch `main`. Commit + push at each milestone and meaningful working unit; never a broken build.
- Author = the user's own git identity only (check `git config user.name/user.email` for this repo; ask once if unset).
- **No AI attribution:** no `Co-Authored-By` trailers, no "Generated with Claude Code", no assistant names in any commit, branch or PR text. Keep `.claude/settings.json` with `{"includeCoAuthoredBy": false}`.
- Conventional Commits, human tone: `feat(edge): ...`, `fix(api): ...`, `test(core): ...`, `docs: ...`, `chore: ...`.
- Never commit `.env`, keys, `data/`, videos, model weights. Secret-scan before the final push.

## Footage
No venue camera and no user recordings. The 6 demo clips are downloaded by `python scripts/fetch_samples.py` (Pexels clip1..5: veg-stall counter, Mumbai street, road with bikes/autos, mall lobby, night fruit stall; clip6_bag = ABODA video10 + its reversed tail, because the CAVIAR ceiling-fisheye bag is too small to detect), with sources in `samples/SOURCES.md`, stamped as last night's footage via `samples/demo_manifest.yaml` (`python scripts/demo_setup.py`). Low-res sources are upscaled ×2 before detection. Any uploaded video (including a judge's) and any live RTSP/SRT/RTMP/phone camera must also work, started from the UI via the edge manager; `scripts/live_from_file.ps1` proves the live path.

## Setup is your job
Create/extend `.env` yourself (all non-secret values filled; `OPENAI_API_KEY`, AWS keys and `S3_BUCKET` left empty for the user to paste at the end). Start Docker Desktop yourself if `docker info` fails. Install everything. Never print or commit secrets.

## Self-review and handoff
The user does not check milestones. You verify visually yourself (extract frames/screenshots and look at them) and fix issues. At the end write `FINAL_STEPS.md` (BUILD_PROMPT.md §23): which env values to paste, check commands, how to start, judge demo script, deploy pointer, submission checklist.

## README
Must follow BUILD_PROMPT.md §22: real screenshots, real measured numbers, Mermaid architecture, evidence-level table, OpenAI and AWS usage tables, honest limitations, roadmap, credits.

## Definition of done for the demo
Demo cameras loaded (or upload any video / connect a live camera) → ask a Hindi voice question → answer + clips with levels → create a rule by voice → replay shows past hits → live alert from the bag clip running as a live camera → cost-per-camera-day page. Full checklist: BUILD_PROMPT.md §21.
