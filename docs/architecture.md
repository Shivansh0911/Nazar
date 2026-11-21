# Nazar architecture

## Processes
| Process | Command | Talks to |
|---|---|---|
| postgres (pgvector) | docker compose | everyone |
| mediamtx | docker compose | phones/DVRs push SRT/RTMP/RTSP; edges pull RTSP |
| edge (one per camera) | `python -m nazar.edge.run --camera <id>` | Postgres, media dir |
| worker (one) | `python -m nazar.worker.run` | Postgres (+ LISTEN/NOTIFY), OpenAI |
| api (one) | `uvicorn nazar.api.main:app` | Postgres, media dir, OpenAI, spawns edges |
| web | static Next.js export | api over HTTPS + WebSocket |

No queues, no microservices: processes share Postgres and the media directory. Alerts travel
`worker → pg_notify('nazar_alerts') → API LISTEN thread → WebSocket`.

## Data flow
1. **Edge**: decode → keep frames at 10 fps for segments, detect at 5 fps → motion gate (skip when nothing moves and
   no track is active) → YOLO11n + ByteTrack → per-track path `[t_ms, x1, y1, x2, y2, conf]` (normalized) → upsert
   active tracks every second → on track end (2 s unseen): up to 3 face-blurred crops + 76-d appearance vector.
   Segments are 10 s H.264 files of blurred frames; timestamps are exact (file start + PTS, or wall clock live).
2. **Worker / eventizer**: for every updated track, `eventize(path, cls, zones)` writes enter/exit/dwell events
   (feet point for people/vehicles, centre for objects, 2-point hysteresis). A zone edit re-eventizes 7 days.
3. **Worker / rules**: the same pure evaluators as replay (`core/rules.py`) run on each updated track
   (+ a 1 s tick for `count_over`). `object_removed` = stationary ≥ 10 s in the zone, then gone/left, with a person
   within 0.1 of it ±3 s (the actor). Alerts are unique per (rule, track).
4. **Worker / stitcher**: merges a track into its predecessor when it starts ≤ 1.5 s later, ≤ 0.08 away, with
   appearance cosine ≥ 0.85. Counting and search use `root_tracks`.
5. **Worker / enricher**: 1–3 crops → `TrackCaption` (structured output) → embedding text → `text-embedding-3-small`.
   Daily cap, 3 attempts, never re-enriches.
6. **API / ask**: transcribe (voice) → agent with strict function tools → final JSON (reply, track ids, count ref,
   rule id, follow-ups) → the server assembles counts/clips/levels **from its own tool results** → TTS in parallel.

## Evidence levels
`core/levels.py::assign_level` is the only place a level is decided:
- structural question (time/zone/class only) → **confirmed**
- all requested attributes match and similarity ≥ 0.35, or similarity ≥ 0.45 with no attributes → **probable**
- similarity ≥ 0.25 or any attribute match → **candidate**
- else not returned.

## Tables
`cameras, tracks (path jsonb, appearance vector(76), caption_emb vector(1536)), events, segments, camera_status,
rules (spec, replay, language, activated_at), alerts, queries, usage, jobs` + view `root_tracks`.
See `backend/nazar/sql/`.
