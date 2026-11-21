# Nazar — ask your CCTV anything, in your own language.

**Send a voice note in Hindi, English or Hinglish to your shop's CCTV. Get back a spoken answer, a count, and the
exact clips, each with an honest evidence level. Teach it what to watch for, and it alerts you by voice.**

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Next.js 15](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs)
![OpenAI](https://img.shields.io/badge/OpenAI-Responses%20API-412991?logo=openai)
![AWS](https://img.shields.io/badge/AWS-EC2%20%7C%20RDS%20%7C%20S3%20%7C%20Amplify-FF9900?logo=amazonaws)
![License: MIT](https://img.shields.io/badge/License-MIT-green)

<p align="center">
  <img src="docs/screenshots/cameras_desktop.png" alt="Nazar cameras" width="68%">
  <img src="docs/screenshots/chat_empty_mobile.png" alt="Nazar chat on a phone" width="24%">
</p>

> Built solo for Builders 2026 (OpenAI × Equal AI, Hyderabad), Build Creative track.

## The problem
India's shops, homes, clinics and housing societies already paid for CCTV — usually a cheap DVR that records
24×7 and that nobody watches. When something happens, the owner scrubs hours of footage on a tiny DVR screen.
The cameras see everything; the owner can ask nothing.

## What Nazar does
| | Example (Hinglish) | What comes back |
|---|---|---|
| **Ask** | "Kal raat 10 baje ke baad shop counter pe kitne log aaye?" | A spoken + written reply, a **Confirmed** count from SQL with an hourly chart, and the clips |
| **Teach** | "Jab bhi koi desk 14 se bag uthaye, mujhe batana" | A readable rule, **replayed on last night first** ("would have fired 1 time", with the clip), then one tap to activate |
| **Alert** | (a person picks up the bag on desk 14) | A red alert bubble with a face-blurred snapshot and a voice note, ~4 s after it happens |
| **Find again** | tap *Find again* on any person | Same-looking people ±24 h from a 76-number appearance fingerprint — no face recognition |

On the demo data: the object-removed rule on *Office desk* replays to exactly one hit (21:51, with the person who took
the bag as the actor), and when the same clip plays as a live camera the alert arrives as a red bubble with a
Hinglish voice note. A 3-minute recorded walkthrough: `scripts/demo_video.mjs` (see *Demo video* below).

## Demo in 60 seconds
```powershell
docker compose -f infra/docker-compose.yml up -d                        # Postgres (pgvector) + MediaMTX
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121; pip install -e backend
python scripts/fetch_samples.py; python scripts/download_models.py; python scripts/demo_setup.py
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1           # worker + API + web -> http://localhost:3000
```
`demo_setup.py` stamps six downloaded clips as last night's footage and prints questions with real answers:
1. Kal raat 10 baje ke baad shop counter pe kitne log aaye?
2. How many people came to the shop counter between 6 and 8 pm yesterday?
3. Desk 14 se bag kisne uthaya?
4. Jab bhi koi desk 14 se bag uthaye, mujhe batana
5. Raat 11 baje ke baad main road pe kitni bikes guzri?
6. Aaj subah lobby mein sabse zyada bheed kab thi?
7. रात 2 बजे के बाद night stall पर कितने लोग आए?
8. Show me people carrying a bag on the market street this morning

## Demo video
`scripts/demo_video.mjs` records the real app end to end (captions on screen): cameras → zones → teach a rule by
text, replay, activate → bag clip playing as a live camera → Hinglish count → Hindi voice note → bag search with
evidence levels → clip player with the tracked box → find again → **live alert** → cost page. Run it with
`cd web; node ../scripts/demo_video.mjs --channel chrome --wav ..\demo\q_hi.wav` (writes `demo/nazar_demo.webm`).

## How it works
```mermaid
flowchart LR
  cam["Camera<br/>file · RTSP DVR · phone (SRT/RTMP→MediaMTX)"] --> edge
  subgraph edge["Edge (one process per camera)"]
    direction TB
    e1["5 fps sample + motion gate"] --> e2["YOLO11n + ByteTrack"] --> e3["5 Hz paths · face blur<br/>crops · 76-d fingerprint<br/>10 s segments · snapshot"]
  end
  edge --> pg[("Postgres + pgvector<br/>tracks · events · segments")]
  pg --> worker
  subgraph worker["Worker"]
    direction TB
    w1["eventizer: paths → zone events"] --> w2["rules: live evaluation → alerts"]
    w3["stitcher: merge broken tracks"]
    w4["enricher: 1–3 crops → caption + attributes → embedding"]:::ai
  end
  worker --> pg
  pg <--> api["FastAPI<br/>agent tools · clips · WS"]
  api <--> web["Next.js PWA<br/>chat · voice notes · zones"]
  api -. "transcribe · agent · TTS · rule compiler" .-> oai(("OpenAI")):::ai
  w4 -.-> oai
  classDef ai fill:#efe7ff,stroke:#7c3aed
```

**Trajectories are the truth.** The edge stores each object's path (normalized boxes, 5 Hz), not "events". One
function — `nazar/core/eventizer.py`, with hysteresis so boundary jitter never flaps — turns paths into
enter/exit/dwell events. Redraw a zone and the worker re-derives a week of events; replay a rule and it runs the
same evaluator the live engine uses.

**Evidence levels** (assigned only by `nazar/core/levels.py`; the model never sets or upgrades one):

| Level | Rule | Looks like |
|---|---|---|
| **Confirmed** | A tracker fact: a count from SQL, an entry into a zone, a timestamp | solid green pill, filled dot |
| **Probable** | All requested attributes match the vision caption (colours, carrying, vehicle) **and** semantic similarity ≥ 0.35 — or similarity ≥ 0.45 with no attributes asked | amber pill, half-filled dot |
| **Candidate** | Similarity ≥ 0.25 or some attribute matches | grey **dashed** outline, hollow dot, "check this", never placed above the others |

If nothing matches, Nazar says so and lists the hours the camera had no footage.

**Replay before you trust a rule.** A rule compiled from the owner's words is validated against the camera's zones,
replayed over the last 24 h (or the footage window), shown with its hits, and stays inactive until the owner taps
Activate. Live alerts only fire for events after activation.

**Cost by design.** Computer vision watches every frame for free on the edge; OpenAI only sees 1–3 face-blurred crops
per tracked object (detail `low`) plus the owner's questions. The Metrics page computes ₹ per camera-day from the
real `usage` rows and compares it with a naive "one frame per second to a vision model" baseline using the same
measured price per image. Numbers: see *Measured results*.

**Privacy by design.** Faces are blurred (YuNet, with a head-band fallback for every person box) before any crop,
segment, snapshot, clip or live frame is written. No face recognition, ever — "find again" uses clothing colour and
edge statistics. The vision prompt forbids identity, ethnicity, religion, caste and age guesses. Media is deleted
after 7 days (`worker/retention.py`, plus an S3 lifecycle rule in production).

## Where OpenAI is used
| Model (from `.env`) | Job | When | Cost share |
|---|---|---|---|
| `OPENAI_VISION_MODEL` (gpt-6-luna; falls back to `OPENAI_VISION_FALLBACK`) | Track caption + structured attributes (`TrackCaption`) | once per finished track ≥ 1 s, 1–3 crops | — (`python scripts/cost_report.py`) |
| `OPENAI_EMBED_MODEL` (text-embedding-3-small) | Caption embeddings; query embedding for search | batched after captions; per described question | — |
| `OPENAI_AGENT_MODEL` (gpt-6-sol) | Query agent (function tools), rule compiler, zone suggestions, vision confirm | per question / rule / button | — |
| `OPENAI_TRANSCRIBE_MODEL` (gpt-4o-transcribe) | Voice-note transcription with a zone-aware prompt | per voice note | — |
| `OPENAI_TTS_MODEL` (gpt-4o-mini-tts) | Spoken replies and alert voice notes | per answer / alert | — |

Every call writes a `usage` row (tokens, images, audio seconds, cost). Model names are only read from the env.

## Where AWS is used
| Service | Role |
|---|---|
| **EC2** (one c7i.xlarge, CPU only) | MediaMTX ingest, API + edge manager, worker, Caddy HTTPS |
| **RDS PostgreSQL 16 + pgvector** | tracks, events, rules, alerts, usage, vectors |
| **S3** (7-day lifecycle) | crops, clips, TTS voice notes, alert snapshots (presigned URLs) |
| **Amplify Hosting** | the static web app |
| **IAM instance role** | S3 access without keys on the server |

Guardrails: no GPU instances, no Bedrock, exactly one instance, budget alert. Click-by-click: [infra/DEPLOY.md](infra/DEPLOY.md).

## Measured results
Measured on 2026-11-21 with the real models (gpt-6-luna captions, gpt-6-sol agent), on the demo data (6 cameras,
~0.2 h of busy footage, ~650 tracks, 340 described), on the dev laptop (RTX 4050 Laptop 6 GB, i5-13420H, 8 GB RAM).

| Metric | Value | Source |
|---|---|---|
| Detection fps, laptop GPU (YOLO11n fp16, 1280×720, imgsz 640) | **24.6 fps** (19.6 fps for a 720×480 source upscaled ×2 at imgsz 960) | edge `EDGE_SUMMARY` |
| Whole edge pipeline speed on files | **1.2–1.6× real time** (crowded street 1.27×) | edge `EDGE_SUMMARY` |
| Detection fps, EC2 CPU (OpenVINO) | — | run the edge on EC2 after `download_models.py --export-cpu` |
| Count accuracy | **80 %** (1 window: 6 tracked vs 5 people counted by hand; one ID switch) | `scripts/eval_counts.py` |
| Live alert latency (RTSP → WebSocket) | **3.3–4.2 s** (3 alerts) | M7 live test |
| End-to-end question battery (10 text Hinglish/Hindi/English + 2 Hindi voice notes) | **12/12 pass**: reply in the asker's language/script, counts = SQL series, Candidates never above Probables, voice reply delivered | test battery + `scripts/smoke.ps1` PASS |
| Ask latency p50 / p90 (text answer) | **9.5 s / 13.0 s** over 46 questions (best 5.2 s); the voice reply follows 2–3 s later | Metrics page |
| Cost per question | **₹0.25–0.85** typical (₹2.1 for a multi-search question) | `queries.cost_usd` |
| Cost to describe one tracked person/vehicle | **₹0.010** ($0.00011, 1–3 crops, gpt-6-luna) | `python scripts/cost_report.py` |
| ₹ per camera-day / naive / ratio | **₹351 / ₹449 / ~1.3×** on this rush-hour-dense demo footage (~1,500 described objects per hour) — see note | `python scripts/cost_report.py` |
| Search hit@3 / confidently-wrong rate | — (fill truth windows in `scripts/eval/questions.yaml`) | `python scripts/eval_search.py` |

**Cost, honestly.** Nazar's AI cost follows *activity*, not time: ₹0.01 per person or parked vehicle it describes
(passing traffic seen < 5 s is not described). The demo clips are rush-hour streets and malls, so extrapolating them
to 24 h gives ₹351/day — barely below a naive "one image per second" design (₹449/day, priced at the same small
crop; real full frames would cost more, and Nazar never sends full frames). For a shop with ~500 visitors a day the
same numbers give ≈ ₹5/day. Questions cost ₹0.25–0.85 each.

## Connect a real camera
- **Phone:** Cameras → Add camera → **Phone** shows a QR and the exact Larix Broadcaster URL
  (`srt://<host>:8890?streamid=publish:<id>` or `rtmp://<host>/<id>`); press *Create & start*.
- **CCTV DVR / NVR (RTSP):** Cameras → Add → **CCTV / RTSP**. Typical URLs (use the sub-stream):
  Hikvision `rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102`,
  CP Plus / Dahua `rtsp://user:pass@192.168.1.108:554/cam/realmonitor?channel=1&subtype=1`.
- **A video file:** Cameras → Add → **Upload** (any phone/DVR export up to 60 min / 2 GB; 4K and portrait are
  normalized on ingest), then "Ready — ask about it".
- No camera at hand? `scripts\live_from_file.ps1 samples\clip2.mp4 cam1` streams a clip into MediaMTX over RTSP.

## Run it yourself
Prerequisites: Windows/Linux, Python 3.12, Node 20, Docker, ffmpeg, an NVIDIA GPU optional (CPU works, slower).

| Variable | Purpose | Default | Secret |
|---|---|---|---|
| `OPENAI_API_KEY` | all AI features (503 with a clear message when empty) | — | yes |
| `OPENAI_VISION_MODEL` / `_FALLBACK` / `_AGENT_MODEL` / `_EMBED_MODEL` / `_TRANSCRIBE_MODEL` / `_TTS_MODEL` | model names | gpt-6-luna / gpt-5.4-mini / gpt-6-sol / text-embedding-3-small / gpt-4o-transcribe / gpt-4o-mini-tts | no |
| `DATABASE_URL` | Postgres | `postgresql://nazar:nazar@localhost:5433/nazar` | no (yes in prod) |
| `STORAGE_MODE`, `S3_BUCKET`, `AWS_REGION` | local disk or S3 | `local`, —, `us-west-2` | no |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` | laptop-only S3 access (EC2 uses a role) | — | yes |
| `API_BASE_URL`, `WEB_ORIGINS`, `PUBLIC_HOST` | URLs, CORS, host phones stream to | localhost | no |
| `DEMO_PASSCODE` | the single demo passcode | `nazar2026` | yes in prod |
| `DATA_DIR` | media directory | `<repo>/data` | no |
| `DETECT_FPS`, `DETECT_IMGSZ`, `DETECT_CONF`, `SEGMENT_*`, `TRACK_END_S`, `MOTION_THRESH` | edge tuning | 5, 640, 0.30, 10 fps/10 s/854 px, 2.0, 0.002 | no |
| `ENRICH_DAILY_USD_CAP`, `RETENTION_DAYS`, `MAX_EDGES`, `LEVEL_*_SIM`, `USD_INR`, `PRICES_JSON` | cost/safety knobs | 5.0, 7, 2, 0.35/0.25, 88, — | no |

Full local setup: the five commands above, then `python scripts/check_env.py` and `python scripts/check_models.py`.
Services individually: `python -m nazar.worker.run`, `uvicorn nazar.api.main:app --port 8000` (from `backend/`),
`cd web; npm run dev`. Deploy summary: one EC2 + RDS + S3 + Amplify — see [infra/DEPLOY.md](infra/DEPLOY.md).

## API reference
| Method & path | Purpose |
|---|---|
| `POST /api/auth` | passcode → token (send as `X-Nazar-Token` or `?token=`) |
| `GET /api/health` | db, key, camera status |
| `GET/POST /api/cameras`, `GET/PATCH/DELETE /api/cameras/{id}` | cameras and zones |
| `POST /api/cameras/upload`, `GET /api/cameras/{id}/progress` | upload any video and follow processing |
| `POST /api/cameras/{id}/start`, `/stop`, `GET /edge` | edge manager |
| `GET /api/cameras/{id}/snapshot.jpg`, `/live.mjpg` | blurred live view |
| `POST /api/cameras/{id}/suggest-zones` | AI zone suggestions |
| `GET /api/cameras/{id}/timeline`, `/gaps`, `/tracks` | hourly series, offline periods, recent tracks |
| `POST /api/ask` | text JSON or multipart `audio` → `AskResponse` |
| `GET /api/search`, `GET /api/count` | the agent's tools, for debugging |
| `GET /api/tracks/{id}`, `/similar` | track details, find again |
| `GET /api/clips/track/{id}`, `/api/clips/range` | clip + path for the canvas overlay |
| `POST /api/rules/compile`, `GET /api/rules`, `POST /api/rules/{id}/activate|deactivate`, `DELETE` | watch rules |
| `GET /api/alerts`, `POST /api/alerts/{id}/ack` | alerts |
| `WS /api/ws` | live alerts + camera status |
| `GET /api/metrics` | cost per camera-day, latency, levels |

## Project structure
```
backend/nazar/core     shared: config, db, eventizer, rules, levels, appearance, OpenAI client, storage
backend/nazar/edge     per-camera process: source, detector, tracker state, face blur, crops, segments
backend/nazar/worker   eventize, rules, alerts, stitcher, enricher, retention
backend/nazar/api      FastAPI routes, agent + tools, voice, clips, WebSocket, edge manager
backend/tests          unit tests (fake OpenAI client) + API smoke tests
web/                   Next.js static PWA
infra/                 docker compose (dev/prod), MediaMTX, Caddy, Dockerfile, DEPLOY.md
scripts/               setup, demo data, live stand-ins, eval, cost report, smoke, screenshots
samples/               clip sources + demo manifest (videos are downloaded, not committed)
```

## Honest limitations
- **Crowds and occlusion:** busy street/lobby scenes produce more tracks than people (ID switches); the stitcher
  merges some, counts are still an upper bound there. Measured count accuracy so far is from one short window.
- **Night / IR footage:** low light lowers detection confidence; the night clip is lit, real IR footage is untested.
- **Low-res and top-down views:** a 20-px bag from a ceiling fisheye (CAVIAR) is never detected — we switched the
  bag demo to a corner camera (ABODA) and document the miss in `samples/SOURCES.md`.
- **The bag-pickup demo clip is constructed:** its second half is the same footage played backwards.
- **Attribute errors:** colours and "carrying" come from a vision model on small crops; that is why they only ever
  reach *Probable*, and a pure similarity match stays a *Candidate*.
- **Laptop limits:** on 8 GB RAM two edges at once compete with everything else; the edge needs ~30 s to load.
- **Answer latency** is 7–13 s (two agent rounds + tools), above the 6 s goal; the voice reply streams in after the text.
- **Cost on busy scenes:** on rush-hour footage the per-camera-day cost is close to a naive per-second design (see
  *Measured results*); the saving comes from quiet hours and from never sending full frames.

## Roadmap
- **A Camera Agent inside Equal's AI messenger:** ask over chat or voice note, alerts arrive as messages or calls.
- **An on-site box beside the DVR** so video never leaves the premises; only crops and questions go out.
- **Multi-camera journeys** (SETU-style appearance search across cameras), then homes, housing societies, clinics.

## Built on / credits
**Lineage:** the author previously built SETU — vehicle search across 80,000 police cameras without readable number
plates (edge detection, appearance fingerprints, pgvector, evidence tiers, "replay first"). Nazar is the same
discipline shrunk to one shop camera.

Open source: Ultralytics YOLO11 + ByteTrack, OpenCV (YuNet face detector), FastAPI, psycopg + pgvector, PostgreSQL,
MediaMTX, ffmpeg, Next.js, Tailwind CSS, lucide icons, qrcode, Caddy.

Footage: Pexels creators GK Kumawat, Aksinfo7, Karthick S, Joshua Santos, Riaz Uddin (Pexels License); ABODA
abandoned-object dataset; CAVIAR (EC Funded CAVIAR project/IST 2001 37540). Details and links: [samples/SOURCES.md](samples/SOURCES.md).

License: MIT (code). Sample footage keeps its own licence.
