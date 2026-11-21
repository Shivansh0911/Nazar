# NAZAR v2 — Upgrade Specification (builds on the working v1 in this repo)

> **How to use this spec:** Save it verbatim as `BUILD_PROMPT_V2.md` in the repo root. Read it fully, then read `CLAUDE.md`, `BUILD_PROMPT.md` (v1 spec), `PROGRESS.md`, `FINAL_STEPS.md` and the current code before changing anything. v1 works and is tested — **evolve it, never rewrite blindly, never leave `main` broken.** Where this spec conflicts with v1, this spec wins. Work in the workstreams below in priority order; after each workstream: run its checks, self-review visually (screenshots/frames you look at yourself), fix until green, update `PROGRESS.md` (add a "v2" section), commit + push per the git rules (§K). The user is NOT checking intermediate work — you verify everything yourself. Ask the user only when truly blocked (a secret, a physical action, an AWS action). All secrets are already in `.env` (OpenAI key works: 5/5 models OK). Everything must **actually work on this laptop, end to end, with real data — no mocks, no faked results, no demo-only paths.**
>
> **If you are resuming:** read `PROGRESS.md` → continue from its v2 "exact next step".

---

## A0. Ready on this machine for v2 (the user has done these)
- `samples/hackathon.mp4` — a real clip from today's Builders hackathon venue. Process it as camera **"Builders venue"** (id `builders-venue`) and make it the hero of the demo (W9.2). It shows real people: faces must be blurred everywhere it is served.
- `.env` has `TELEGRAM_BOT_TOKEN` for the bot **@nazar_hackathon_bot** (add `TELEGRAM_BOT_USERNAME=nazar_hackathon_bot` to `.env`/`.env.example` if missing, so Settings can show a t.me link + QR for pairing). The user has sent `/start` to the bot.
- Kaggle is set up by the user: `KAGGLE_API_TOKEN` (and/or `KAGGLE_USERNAME` + `KAGGLE_KEY`) in `.env`, and/or `C:\Users\ssojh\.kaggle\kaggle.json`. Use `kagglehub` (supports `KAGGLE_API_TOKEN`) or the `kaggle` CLI — load the values from `.env` into the process environment before calling them. If a dataset returns 403, it needs its rules accepted on its Kaggle page: list it for the user and continue with other data.
- **MCP servers — set them up yourself as your very first step** (the user has not added them). Run in PowerShell from the repo root:
  ```powershell
  claude mcp add playwright -- npx @playwright/mcp@latest
  claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
  claude mcp add --transport http context7 https://mcp.context7.com/mcp
  claude mcp list
  ```
  If a server is already added, keep it. Use **Playwright** (drive a real browser: click through every screen, screenshots, mobile viewport), **Chrome DevTools** (console errors, network failures, Lighthouse/performance) and **Context7** (current docs — use it before coding against YOLOE/TensorRT, the OpenAI Realtime API, python-telegram-bot, Next.js/shadcn, MediaMTX WebRTC). MCP servers added during a session usually load only in the **next** session: if they are not available yet, continue without waiting — use the Playwright npm package (`npx playwright`, `scripts/screenshots.mjs`) and web docs for now — and note in PROGRESS.md that the next session will have them. Never block the build on MCPs.
- The laptop is set not to sleep; RAM is tight (8 GB) — keep memory discipline (W1.9).

## A. Where v1 stands (facts — do not re-discover)
- Working: edge (YOLO11n + ByteTrack, 5 Hz paths, face blur, 10 s segments), worker (eventizer, rules, alerts, stitcher, enricher), API (all v1 routes), agent (Responses API, 5 tools, server-assigned evidence levels), voice notes (transcribe + TTS), web (Next.js static export: chat, cameras, upload, phone/RTSP add, zones, rules, metrics), live RTSP via MediaMTX, demo dataset (6 cameras, ~650 tracks), 72 tests pass, smoke PASS.
- Measured: detection 24.6 fps on RTX 4050 (fp16, imgsz 640); file pipeline only **1.2× real time** (an hour of footage ≈ 50 min — too slow); ask latency p50 9.5 s (text 7–10 s); agent is ~50 % of all AI spend; captions ₹0.01 per described person but **₹351/camera-day on busy footage — the "paise per day" pitch failed**; count accuracy measured once (80 % on one hand-counted window); "people seen" counts inflate when ByteTrack fragments IDs (74 in the lobby); bag search returned only Candidates; count card chart shows one lonely bar; metrics page shows raw JSON; UI is plain and narrow; laptop RAM (8 GB) runs out under load.
- Environment: Windows 11, RTX 4050 6 GB (CUDA 12.3 driver, torch 2.5.1+cu121), 8 GB RAM, Postgres on host port 5433, ffmpeg 9.1, ultralytics 8.4.x, openai SDK 3.57, DATA_DIR outside OneDrive, OpenCV < 5. Close-to-limit RAM: keep one model process, reuse it, avoid duplicate model loads, cap Docker.
- OpenAI models available (env-driven): gpt-6-luna, gpt-6-sol, gpt-6-astra, gpt-5.4-mini, text-embedding-3-small/large, gpt-4o-transcribe, gpt-4o-mini-transcribe, gpt-transcribe, gpt-realtime-whisper, gpt-4o-mini-tts, gpt-realtime-2, gpt-realtime-2.1, gpt-realtime-2.1-mini, gpt-live-1.1, gpt-realtime-translate. The project allows service tiers Standard, **Flex** (≈50 % cheaper, slower — use for background jobs), Fast, Ultrafast.

---

## B. The v2 product and its USP

**One line:** *Nazar turns any CCTV — or any video you have — into a security analyst you can talk to, in your own language. Show it a photo and it finds every sighting across all cameras in seconds. Tell it what to watch and it checks yesterday first, then watches live. One tap makes a police-ready incident report. Indexing a full day of footage costs ₹0 in AI — you only pay when you ask.*

**Three pillars (the "how did one person build this in a night?" moments):**
1. **Search footage like Google Photos — by words, by photo, by voice.** "Red scooter", "man in a yellow kurta with a backpack", "was the shutter open at 3 am?", or upload a photo of a bag / jacket / vehicle → every matching moment across all cameras, ranked, playable, with a cross-camera journey. Runs on a **local visual index** (GPU, free); OpenAI only verifies the top hits.
2. **Teach it anything, no training.** "Gas cylinder pe nazar rakho", "watch for helmets", or show a photo of *your* scooter → open-vocabulary detection starts on that camera immediately, rules apply, replay on the past first, then live alerts — to the web app and to **Telegram** (voice note in, voice note + clip out).
3. **Proof, not claims.** Every number has receipts (each counted person with its clip, a "proof reel" montage), every match has an evidence level, every incident becomes a **FIR-ready PDF** (timeline, blurred keyframes, descriptions, evidence levels, SHA-256 hashes). Plus security analytics out of the box: loitering, abandoned object, running, fall, crowding, after-hours presence, possible snatch — each verified by AI before it becomes "Probable".

**Who it's for:** shop owners, homes, housing societies, small offices, security guards, and police/security teams reviewing footage (lost person in a mela, chain-snatching suspect, stolen vehicle). Indian languages first.

**Non-negotiable principles (carry over + tighten):**
- **No face recognition, ever.** Photo search uses body/clothing/object/vehicle appearance computed on face-blurred images. If a user asks to find a *face*, refuse politely and offer clothing/appearance search. Every photo search is written to an audit log with an optional "purpose" field (SETU-style accountability).
- **Evidence levels decided only by server code.** Confirmed = tracker/database fact. Probable = local similarity AND an independent check agree (attributes or OpenAI vision verification "yes"). Candidate = similarity only. Nothing promotes a Candidate except a recorded verification.
- **Counts come from SQL, never a model — and every count shows its receipts.**
- **Privacy:** raw video stays on the owner's machine (like a DVR) and is never served unblurred and never sent to OpenAI. Everything served or sent (clips, crops, snapshots, live view, keyframes, PDFs, Telegram media) is face-blurred at the moment it leaves the pipeline. Retention 7 days (configurable).
- **Honest numbers only:** every metric in the UI/README comes from a script run, with date and dataset. Never claim "100 % accurate"; show measured accuracy and let receipts prove each answer.

---

## C. Time budget and priorities (READ THIS)
Now is Saturday ~23:30 IST. **Feature freeze: Sunday 09:00 IST.** After that only fixes, README, demo video, deploy prep. Code freeze 14:00. AWS deploy is done by the user later (keep the deploy kit working; do not create AWS resources).

Build strictly in this order; each item must be fully working before the next tier. If time runs out, a finished P0 beats a half-built P1.
- **P0 (must ship):** W1 speed pipeline · W2 counting accuracy + receipts + always-playable clips · W3 local visual index + search by text/photo + journey · W6 agent v2 (any analysis, charts, streaming, faster, cheaper) · W9 onboarding (upload with live analysis view, RTSP builder, Excel/CSV bulk import, the hackathon clip) · W11 UI redesign of core screens + mobile · W13 cost/metrics truth.
- **P1 (should ship):** W4 teach by voice/photo (open-vocabulary) · W5 security events + anomaly + morning digest + incident PDF · W8 Telegram bot · W10 low-latency live view with overlay · W12 dataset-based evaluation.
- **P2 (if time):** W7 Realtime "Call Nazar" voice · plate reading (ANPR) for vehicles · YOLO fine-tune on Indian classes · outbound phone-call alerts · Hindi/English UI toggle.

---

## D. Workstreams (specs)

### W1 — Speed: "an hour of footage in minutes", live feels real-time (P0)
Goal: uploaded/recorded files processed at **≥ 15× real time** on the RTX 4050 at 5 detection fps (1 h of 720p–1080p in ≤ 4 min), live streams at **10 detection fps** with smooth overlay. Measure and print a benchmark table (`scripts/bench_pipeline.py`) before and after; put the numbers in README.
1. **GPU decode + frame sampling in ffmpeg:** for files, read frames through an ffmpeg subprocess pipe (`-hwaccel cuda` when available, `-vf fps=<DETECT_FPS>,scale=<W>:-2`, `-f rawvideo -pix_fmt bgr24`) instead of decoding every frame with OpenCV. Keep exact timestamps: frame i at `start + i/DETECT_FPS` relative to the stream's first PTS (verify against `ffprobe` duration; drift < 0.2 s per hour). Fallback to CPU decode automatically.
2. **Faster inference:** export the detector to **TensorRT FP16** (`model.export(format="engine", half=True, batch=8, imgsz=640)`; install `tensorrt-cu12` — if TensorRT is unavailable on Windows, fall back to ONNX Runtime GPU, then to PyTorch fp16). Run detection in **batches** (8 frames) for files; tracking stays sequential per frame (feed the batch results to the tracker in order). Keep one model instance per process.
3. **Better model if speed allows:** benchmark `yolo11n`, `yolo11s` and `yolo26n`/`yolo26s` (if the installed ultralytics ships them) on the demo clips; pick the most accurate one that still meets the speed goal; record the choice and numbers in PROGRESS.md.
4. **Take media work off the hot path:** for files, **do not re-encode the whole video**. Keep the normalized original (`data/originals/<camera>/<job>.mp4`) and cut clips lazily (W2.5). Compute **head boxes from a pose model** (`yolo11n-pose` or `yolo26n-pose`, TensorRT, batched — keypoints nose/eyes/ears → padded head box) on detection frames and store them in each path point, so blur can be applied later anywhere without re-running face detection. YuNet stays as a second pass on crops and clip frames only (belt and braces).
5. **Crops:** keep up to 3 best crops per track in memory (as v1) and write them blurred at track end — on a writer thread.
6. **Parallel chunks for long files:** split files > 10 min into 2 chunks processed by 2 workers sharing the GPU (overlap 3 s); stitch tracks at the boundary using position + appearance (reuse the stitcher). Only if memory allows; measure.
7. **Progressive results:** tracks/events are queryable while processing (they already upsert); the upload page shows a **live analysis view**: the video plays at up to 8× speed with boxes, IDs and counts drawn as they are produced (stream annotated JPEG frames or JSON detections over WebSocket), a progress bar, and "Ask now about the first N minutes" enabled from the first minute.
8. **Live cameras:** detect at 10 fps; publish a **face-blurred view stream** to MediaMTX (`<camera>_view`, NVENC `h264_nvenc` if available, else libx264 ultrafast, baseline profile) for low-latency viewing (W10), and push per-frame detections (boxes, IDs, class) over WebSocket for the overlay.
9. **Memory:** measure RSS; the whole stack (API + worker + 1 edge + Postgres + MediaMTX + web dev) must run within the laptop's 8 GB with ≥ 1 GB free. Lazy-load models; share the GPU models between the edge manager's jobs (one "vision service" process owning YOLO/pose/SigLIP/YOLOE, others call it over a local queue or HTTP) if separate processes would exceed memory.

### W2 — Counting accuracy, receipts, always-playable clips (P0)
1. **Tracker:** switch to **BoT-SORT with ReID** (ultralytics `botsort.yaml`, `with_reid: True`, `model: auto`) if it reduces ID switches on the demo clips; tune `track_buffer` for 5/10 fps; keep ByteTrack as fallback. Measure ID switches before/after (W12 data).
2. **Stitcher v2:** also merge across short occlusions (≤ 4 s) using appearance (76-d + SigLIP crop embedding cosine) + motion continuity (predicted position); never merge two tracks that overlap in time. Unit tests.
3. **Line counters:** zones gain a "count line" type (two points + direction arrow, drawn in the zone editor) → `cross_in` / `cross_out` events with direction; for entrances, "how many came in" uses line crossings (most robust), not zone entries. Eventizer + tests.
4. **"People seen" semantics:** count distinct **root** tracks with ≥ 1.5 s duration and ≥ 0.6 max confidence (configurable), excluding tracks fully outside the visible area; document this in the count label ("people seen — tracks ≥ 1.5 s"). Compare with hand counts (W12) and tune.
5. **Clips that always play:** every clip/receipt anywhere (chat, receipts, alerts, search, Telegram, PDF keyframes) must play in Chrome, Edge, Safari iOS and Android Chrome. Cut from the original (files) or recorded segments (live) with ffmpeg, apply blur from stored head boxes (+ YuNet second pass), encode H.264 **baseline/main, yuv420p, faststart, even dimensions**, ≤ 30 s, cached. Add a server-side poster JPEG. Test playback with Playwright using **real Chrome** (`channel: "chrome"`, bundled Chromium lacks H.264). If a clip can't be produced, the UI shows why (no footage stored for that time) — never a black box.
6. **Count receipts:** every count answer (chat, Telegram, PDF, dashboard) carries the list of counted tracks: thumbnail, time, zone/line, level, play button; "Play proof reel" concatenates the counted moments (2–3 s each, max 60 s, with a small caption overlay "3/17 · 22:14") into one clip. The hourly chart bars are clickable → filters receipts to that hour. Receipts are paginated for large counts.
7. **Accuracy honesty:** a "Verify" toggle on count cards lets a human mark a receipt wrong; the corrected count is shown separately ("17 by AI · 16 after your review") and stored (feedback table) — used by W12 eval.

### W3 — Local visual index: search by words, by photo, across cameras (P0)
1. **Embeddings model:** SigLIP 2 (`google/siglip2-base-patch16-224` via `transformers`, fp16 on CUDA; fallback `open_clip` ViT-B-32 laion2b). One shared instance in the vision service. Text and image towers both used.
2. **What gets indexed (all local, ₹0 AI cost):**
   - every track's best blurred crop → `tracks.vis_emb halfvec(768)` (or the model's dim),
   - **scene keyframes** at 1 frame / 2 s per camera (blurred, 512 px JPEG kept in `data/keyframes/...`) → table `keyframes(camera_id, t, key, emb halfvec)` — this lets users ask about things that were never tracked ("was the shutter open?", "did it rain?", "was there a cylinder near the door?").
   - HNSW indexes on both.
3. **Search API + agent tool `visual_search`:** inputs: text (any language — the agent translates to a short English visual phrase), and/or an uploaded image (crop the main object automatically with YOLO/YOLOE or let the user draw a box; blur faces; embed). Searches tracks and keyframes in a time range/cameras; merges with structured filters (class, zone, time). Returns ranked hits with level **Candidate** by default.
4. **AI verification of top hits (cheap, on demand):** send the top K (≤ 8) crops/keyframes at `detail: low` to the vision model (Flex tier when the user isn't waiting; Standard when they are) with the question → per hit `{match: yes|no|unclear, reason}`; "yes" + similarity ≥ threshold → **Probable**; "no" → dropped. Log cost. The UI shows "verified by AI" on Probable hits.
5. **Cross-camera journey:** for a selected hit, find the same object on other cameras/times (appearance 76-d + SigLIP cosine + time plausibility between cameras) → ordered timeline "seen at Gate 21:02 → Lobby 21:04 → Parking 21:09" with clips; all hits Candidate unless verified. (SETU's journey, for people/bags/vehicles — never faces.)
6. **Photo search UX:** a camera-icon button in the composer ("Search by photo"), drag-drop or phone camera capture, optional purpose text → results grid + journey. Audit row in `photo_searches`.
7. **Captions become optional:** default `ENRICH_MODE=smart`: no per-track GPT captions; captions are produced lazily only for hits that the user opens/that are verified, or for tracks involved in alerts/incidents (Flex tier). Modes `off | smart | full` in settings. This fixes the cost story: indexing is free, AI is paid per question/verification.

### W4 — Teach it anything: open-vocabulary detection by voice or photo (P1)
1. Add **YOLOE** (ultralytics `YOLOE`, `yoloe-11s-seg` or `yoloe-26s-seg` per installed version) to the vision service, with **text prompts** ("gas cylinder", "helmet", "auto-rickshaw", "cardboard box") and **visual prompts** (a photo + box of the user's own scooter/bag).
2. Per camera `custom_objects` (name, prompt type, prompt data, threshold, active). The edge runs YOLOE on detection frames for cameras with active custom objects (combined with the base detector; measure fps impact; YOLOE at lower fps, e.g. 2–5 fps, if needed); detections become tracks with `cls = custom:<name>`.
3. **Voice/text flow:** "Gas cylinder pe nazar rakho" → agent tool `teach_object` → creates the custom object → optional rule (e.g. alert when it leaves zone / appears) → **replay**: since past footage didn't run YOLOE, replay uses the keyframe index (W3) to find past appearances (Candidate, verify top hits) and, if the user agrees, re-runs YOLOE over the last 24 h of stored footage in the background (fast with W1) → then live.
4. Rules accept custom classes (`cls: "custom:gas_cylinder"`) in all triggers. Tests.

### W5 — Security analytics, anomaly, digest, incident report (P1)
All detectors produce **events with levels**; heuristics produce Candidates; a short vision check (6 blurred keyframes, `detail: low`, Flex unless live) upgrades to Probable. Each new trigger is also a rule trigger.
- `loitering`: dwell in a zone > N s (exists as dwell_over — expose with sensible defaults).
- `abandoned_object`: bag/suitcase/box stationary ≥ T s with no person within radius r for ≥ T2 s.
- `object_removed`: (v1) keep.
- `running`: speed > k body-heights/s for ≥ 1 s (from path), excluding vehicles.
- `fall`: pose-based — torso angle > 60° from vertical and box aspect w>h sustained ≥ 2 s after being upright.
- `crowding`: count_over (v1) with defaults.
- `after_hours`: presence in a time window (v1 zone_enter + window) as a one-click preset.
- `possible_snatch`: two persons within close distance ≤ 3 s, then one accelerates away (speed > k× median walking, or joins a motorcycle track moving away) → Candidate → vision check "does this look like snatching/theft? yes/no/unclear" → Probable.
- `wrong_way` (line direction) for vehicles/people.
**Anomaly baseline:** per camera, per hour-of-week mean/std of people counts from history (fallback: same-day baseline with "low confidence" label) → hours with z > 2.5 or activity in usually-empty hours are flagged in the dashboard and digest.
**Morning digest** (worker, `DIGEST_TIME=08:00`, and on demand "aaj raat kya hua?"): overnight summary — counts vs normal, anomalies, security events (with levels), top 3 clips — as text + TTS voice note, pushed to web and Telegram.
**Incident report (FIR-ready):** from any alert/hit/selection → generate HTML → PDF with **Playwright/Chromium `page.pdf()`** (correct Devanagari shaping; do not use reportlab for Hindi): case title, camera/location, time window, timeline table, 4–8 blurred keyframes, AI description (marked as AI-generated), evidence levels and how they were decided, clip links, SHA-256 of each exported clip and of the PDF manifest, generated-at time, "no face recognition used" note. Download in the app and send on Telegram. Language: Hindi or English (user choice).

### W6 — Agent v2: any analysis, fast, cheap, streamed (P0)
1. **Tools (strict JSON schemas):** keep v1 tools; add: `analytics_query` (see 2), `visual_search` (W3), `verify_hits`, `journey`, `describe_clip` (6–8 blurred keyframes → what happened, Flex unless user waiting), `look_now` (latest live snapshot of a camera + question → answer, e.g. "abhi counter pe kitne log hain?" — counts still from the tracker; vision only for non-countable questions like "is the shutter open?"), `list_events` (security events/anomalies), `teach_object` (W4), `make_report` (W5), `compare_periods` (today vs yesterday / this week vs last), `heatmap` (where people spend time — returns a PNG generated from paths over a blurred snapshot).
2. **`analytics_query` — answers "any analysis" safely:** a read-only **semantic layer**: whitelisted views (`v_tracks`, `v_events`, `v_crossings`, `v_alerts`, `v_cameras`, `v_hourly`) with documented columns; the model writes a single SELECT against these views only; the server validates (sqlglot parse: one SELECT, only whitelisted views/functions, no writes, LIMIT ≤ 1000), runs it as a **read-only DB role** with `statement_timeout=5s`, returns rows + a chart spec. Covers: busiest hour, average dwell at counter, vehicles by type per hour, compare cameras, people who stayed > 5 min, day-over-day change, etc. Results from this tool are **Confirmed** (database facts) and show the SQL behind them in a collapsible "how this was computed".
3. **Charts:** the final answer may include `charts: [{type: bar|line|heatmap|table|pie, title, x, y, series, unit}]`; the web renders them (Recharts), Telegram gets a PNG (server-rendered with matplotlib).
4. **Speed + cost:** route with the cheap model first — `gpt-6-luna` plans and handles simple/common questions (counts, when, show me); escalate to `gpt-6-sol` only for multi-step/ambiguous questions or when luna returns low confidence. Parallel tool calls. **Stream** the answer over SSE (text tokens first, then cards). Start TTS as soon as the text is complete. Targets (measure p50/p90, print in Metrics): first visible text ≤ 2.5 s, full text answer ≤ 5 s p50 for common questions; agent cost per question ≤ ₹0.25 p50. Cache identical recent questions for 60 s.
5. **Languages:** reply in the user's language and script. Test and claim only what you tested: Hindi, Hinglish, English, plus run a TTS→transcribe round-trip test for Tamil, Telugu, Bengali, Marathi, Gujarati and Kannada; list the passing ones in README.
6. **Behaviour:** never invent; say what's not covered (offline gaps, outside coverage); suggest 2–3 follow-ups; for vague requests ask one clarifying question with tappable options.

### W7 — "Call Nazar": hands-free realtime voice (P2)
Web button "Call Nazar" → browser WebRTC session to the OpenAI Realtime API (`OPENAI_REALTIME_MODEL`, default `gpt-realtime-2.1-mini`, fallback `gpt-realtime-2`) using an **ephemeral client secret** minted by the API (`/api/realtime/session`; read the current Realtime docs/SDK for the exact endpoint and event names before coding). Tools are the same agent tools, executed by our backend via the data channel (function call events → POST to `/api/realtime/tool` → result back). Barge-in/interruptions supported by the Realtime API. Show live transcript + cards for tool results. Log usage/cost. Hindi conversation tested.

### W8 — Telegram bot: talk to your CCTV in a messenger (P1)
`python -m nazar.telegram.run` (long polling — works locally, no public URL). `python-telegram-bot` v21+. Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` (pairing: the web app's Settings shows a 6-digit code; user sends `/pair <code>` to the bot; chat id stored). Features: text or **voice note** questions (OGG → transcribe) → answer text + voice note (TTS as OGG/Opus) + up to 3 clips (MP4) + chart PNG + "More" inline buttons; alerts pushed instantly with snapshot + clip + voice note; morning digest; `/cameras`, `/today`, `/report <alert_id>`, photo message = search by photo (with purpose prompt). Rate-limit and size-limit media. If the token is missing, the bot exits with a clear message; everything else still works. Started by `start_all.ps1` when the token is set.

### W9 — Onboarding: any video, any camera, bulk (P0)
1. **Upload v2:** drag-drop multiple files (mp4/mov/mkv/avi/dav-exported mp4, ≤ 4 GB each, ≤ 3 h), optional "recorded at" time and camera/location name, resumable chunked upload (so a 2 GB file over slow Wi-Fi survives), then the **live analysis view** (W1.7). Portrait, 4K, variable frame rate, rotated, and audio-only-garbage files handled (reject clearly).
2. **The hackathon clip:** if `samples/hackathon.mp4` (or any file the user drops in `samples/`) exists, process it as camera "Builders venue" with start time = file time; include it in the demo questions; it must work as well as stock clips. If not present, the app's upload path is the way; document it in FINAL_STEPS.
3. **CCTV / RTSP builder:** brand presets that build the URL from IP/user/password/channel/stream: Hikvision (`rtsp://u:p@ip:554/Streaming/Channels/101`, sub-stream `102`), Dahua / CP Plus (`rtsp://u:p@ip:554/cam/realmonitor?channel=1&subtype=0`), Godrej/others → "custom URL". **Test connection** button: ffprobe with 8 s timeout → codec, resolution, fps, a snapshot thumbnail, or a precise error (auth failed / unreachable / wrong path). Passwords stored encrypted at rest (Fernet key in `.env`, auto-generated) and never returned by the API.
4. **Excel/CSV bulk import:** downloadable template (`.xlsx` and `.csv`: name, location, brand, ip, port, username, password, channel, stream, rtsp_url (optional override), zone_template, active) → upload → validation table → **probe all concurrently** (max 4 at a time) with status per row (✅ reachable + thumbnail / ❌ reason) → "Add all working" → edges start (queued by MAX_EDGES). `openpyxl` for xlsx.
5. **LAN discovery (nice-to-have):** ONVIF WS-Discovery scan (`WSDiscovery` package) lists cameras on the network with IP and manufacturer to prefill the builder.
6. **Phone:** keep Larix SRT/RTMP with QR (v1).
7. **First-run wizard:** if no cameras, the home screen offers 4 big options (Upload a video · Connect CCTV · Use a phone · Import from Excel) and a "Load demo footage" button.

### W10 — Low-latency live view with AI overlay (P1)
MediaMTX WebRTC (WHEP on 8889, ICE UDP 8189) serving the **blurred** `<camera>_view` stream (W1.8); the web player uses WHEP (`RTCPeerConnection`, no SDK) with automatic fallback to the v1 MJPEG. A canvas overlay draws boxes/IDs/class labels from the WebSocket detection feed, interpolated between detection frames, plus live counts per zone/line. Target glass-to-glass < 1 s on LAN. Live wall page: grid of all live cameras with overlays and per-camera live counts. Update dev and prod compose + Caddy for the WebRTC ports.

### W11 — UI/UX: simple, beautiful, real-world ready, mobile-first (P0)
Keep Next.js static export; add **shadcn/ui** (Radix) components, **framer-motion**, **Recharts**, `lucide-react`. Design language: calm and premium — dark-first "night watch" theme (near-black navy `#0A0F1F`, surfaces `#111827`, primary electric blue `#2F6BFF`, accent lime `#D4F53C` for the mic and live states, success/amber/red for levels), with a light theme toggle; Inter for UI, a display serif for big numbers; generous spacing; skeleton loaders; toasts; no raw JSON anywhere.
**Information architecture:**
- **Home / Today:** per-camera tiles (live thumbnail, people today vs normal, last event), anomalies, alerts, morning digest card, "Ask anything" bar.
- **Ask (chat):** desktop = chat on the left + **evidence panel** on the right (video player with timeline scrubber showing an activity heatmap and event markers, receipts list, journey); mobile = full-screen chat, evidence as a bottom sheet. Composer: mic (voice note), text, **photo search** button, "Call Nazar" (W7) — big tap targets.
- **Live:** live wall (W10).
- **Search:** text/photo search page with filters (cameras, time, class), results grid, journey view.
- **Cameras:** list + add (upload / CCTV builder / phone / Excel) + camera detail (live, zones & count lines editor, custom objects, health).
- **Alerts & Rules:** rule list with presets (security pack: loitering, abandoned object, after-hours, crowding, running, fall, possible snatch), replay results, alert inbox with ack, incident report button.
- **Reports:** generated incident PDFs.
- **Insights/Metrics:** cost truth (W13), accuracy numbers, latency — designed cards and charts.
- **Settings:** passcode, Telegram pairing, enrichment mode, retention, language, theme.
**Login:** polished passcode screen (brand, short tagline), "remember this device", rate-limited attempts, logout, token expiry handled gracefully (auto-redirect to login, no blank pages).
**Quality bar:** works at 360–430 px (phones) and 1280–1920 px; no horizontal scroll; every screen has loading/empty/error states; keyboard accessible; installable PWA (manifest + icons, original SVG logo — an eye inside a camera-lens circle); Lighthouse (mobile) performance ≥ 80, accessibility ≥ 90. Self-review with Playwright screenshots of every screen at 390 px and 1440 px in both themes; fix what looks off. Add the **Playwright MCP** to Claude Code for interactive checks if useful (`claude mcp add playwright -- npx @playwright/mcp@latest`).

### W12 — Data for evaluation and improvement (P1)
Find and download (scripts, reproducible, licences recorded in `samples/SOURCES.md` / `data/datasets/README.md`; large datasets never committed):
- **MOT17 / MOT20** (motchallenge.net, person boxes + IDs ground truth) → `scripts/eval_tracking.py`: ID switches, IDF1/HOTA-lite and **count error** vs ground-truth unique IDs on 3–4 sequences, before/after W2 changes.
- **Snatching / theft:** *RoadCrime-CCTV* (Mendeley Data, roadside theft/robbery/snatching CCTV from Bangladesh), *Snatch 1.0* (Zenodo — 12.5 GB, download only a few videos if partial download is possible), *UCF-Crime* samples (robbery/stealing/shoplifting), *Shoplifting Dataset (2022), MNNIT Allahabad* (Mendeley) → evaluate W5 heuristics (precision on a small labelled set; report honestly).
- **Abandoned objects:** ABODA (already used) + PETS 2006 samples.
- **Indian traffic/vehicles:** India Driving Dataset (IDD — needs registration; skip if login required), Kaggle/Roboflow Indian-vehicle sets (auto-rickshaw, e-rickshaw, two-wheeler) — **only if credentials exist** (`~/.kaggle/kaggle.json`, `ROBOFLOW_API_KEY`); otherwise list them in FINAL_STEPS as optional.
- Prefer direct HTTP/Zenodo/Mendeley/Hugging Face downloads; never scrape sites that forbid it; research licences = local evaluation only, not redistributed, credited.
- **Fine-tuning (P2, only if eval shows a real gap and time allows):** short fine-tune of the chosen detector on an Indian-vehicle set for auto-rickshaw/e-rickshaw, validated on held-out data; ship only if mAP improves and speed holds.
- Hand-count 3 short windows on the demo clips (including the hackathon clip if present) yourself by viewing frames, store ground truth in `scripts/eval/ground_truth.yaml`, and report count accuracy per window.

### W13 — Cost truth and metrics (P0)
- New cost model in UI/README: **₹ AI per indexed hour = 0** (local index), **₹ per question** (p50/p90), **₹ per verification**, **₹ per incident report**, optional captions (smart mode) per day; and a projection calculator ("a shop with 500 visitors/day asking 20 questions/day ≈ ₹X/day") computed from measured unit costs — every input visibly measured.
- Use **Flex** service tier for background vision (verification when no user is waiting, captions, digests) with automatic fallback to Standard on 429/unavailable; log the tier actually served and price it correctly (Flex ≈ 50 %).
- Metrics page: designed cards (no raw JSON): spend today/total, unit costs, latency p50/p90, accuracy table from eval scripts, evidence-level distribution, pipeline speed (× real time, fps).

### W14 — Fixes from the v1 review (P0, do first)
- Count answers had no receipts; charts were a single bar → W2.6 and better bucket choice (auto 15 min / hour / day by window length).
- "People seen" inflated by ID fragmentation → W2.1–2.4.
- Bag search returned only Candidates → W3 verification makes Probable possible.
- Ask latency 7–10 s; agent ≈ 50 % of spend → W6.4.
- Metrics page raw JSON → W13.
- Clip player black in headless tests → real-Chrome test path (W2.5).
- Cost pitch "₹351/camera-day" → W3.7 + W13.
- Low free RAM → W1.9.
- Re-check every v1 test still passes after each workstream; extend tests for every new module.

### W15 — MCP and external tools decision
- **Higgsfield** is an AI image/video generation service (models like Kling, Veo, Sora via its MCP). Generated video inside a security product would be fabricated evidence — **do not integrate it into the product.** Do not add it.
- Useful for development: the Playwright MCP (above) for UI self-testing. Do not add MCPs that need the user's accounts without asking.

---

## E. Data model changes (new numbered migrations; never edit old ones)
- `tracks`: add `vis_emb halfvec(<dim>)`, `head_boxes` inside path points (extend point format to `[t_ms,x1,y1,x2,y2,conf,hx1,hy1,hx2,hy2]`, readers must accept old 6-element points), `custom_object_id`, `quality real`.
- `keyframes(id, camera_id, t, key, emb halfvec(<dim>))` + HNSW + `(camera_id, t)` index.
- `zones` JSON gains `type: polygon|line` and `direction` for lines; events type adds `cross_in`, `cross_out`; security event types in a new `sec_events(id, camera_id, type, t_start, t_end, track_ids, level, verified_by, reason, meta)`.
- `custom_objects(id, camera_id, name, prompt_type, prompt_text, prompt_image_key, prompt_box, threshold, active, created_at)`.
- `photo_searches(id, at, purpose, image_key, params, result_count)` (audit).
- `feedback(id, at, kind, ref, correct boolean, note)`.
- `reports(id, at, title, language, pdf_key, manifest_sha256, source jsonb)`.
- `telegram_chats(chat_id, paired_at, name, language, alerts boolean)`.
- `camera_credentials(camera_id, enc_username, enc_password)`; `cameras` adds `brand, location, ip, port, channel, stream`.
- `usage` adds `service_tier`.
- Read-only role `nazar_ro` with SELECT on the semantic views only.

## F. API additions (keep v1 routes working)
`/api/search/visual` (text/image), `/api/search/verify`, `/api/journey/{track_id}`, `/api/receipts/{query_id}`, `/api/clips/reel`, `/api/custom-objects` CRUD, `/api/sec-events`, `/api/digest`, `/api/reports` (create/list/download), `/api/realtime/session`, `/api/realtime/tool`, `/api/telegram/pair-code`, `/api/cameras/test` (probe), `/api/cameras/import` (xlsx/csv) + `/api/cameras/import/template.{xlsx,csv}`, `/api/cameras/discover` (ONVIF), `/api/uploads` chunked (init/part/complete), `/api/analysis/{job}/live` (WS frames/detections), `/api/ask/stream` (SSE), `/api/feedback`, `/api/settings`. All authenticated; all typed in `web/lib/types.ts` ↔ `nazar/core/schemas.py`.

## G. Acceptance tests (you run them; all must pass)
1. **Speed:** `scripts/bench_pipeline.py` on a ≥ 30 min test file (concatenate demo clips) → ≥ 15× real time on the RTX 4050, timestamps drift < 0.5 s; live camera at 10 detection fps.
2. **Counts:** count answers equal SQL; receipts count equals the number; proof reel plays; eval_tracking on MOT17 shows fewer ID switches than v1; hand-count accuracy reported per window.
3. **Search:** "person carrying a backpack" and a photo of a bag from one clip each return the right moments in the top 5 on the demo data; verification turns at least the correct top hit into Probable; journey links the same object across ≥ 2 cameras where it exists (use the mall/lobby clips or upload two clips of the same scene).
4. **Teach:** "watch for a laptop" (or a visible custom object in the demo) → YOLOE detects it on a live/simulated camera; a rule fires live; replay shows past candidates.
5. **Security:** abandoned-object and object-removed fire on ABODA; running fires on a clip with a running person; possible-snatch evaluated on the snatch samples with an honest precision number.
6. **Agent:** a battery of ≥ 25 questions (count, when, where, compare, busiest hour, dwell, vehicles by type, describe clip, look now, visual search, teach, report, Hindi/Hinglish/English) → correct structure, Confirmed numbers equal SQL, no fabricated numbers, p50 latency target met or honestly reported.
7. **Telegram:** with a token set, a voice-note question gets text + voice + clip; an alert arrives with clip; pairing works. (If no token, verified with the bot's offline test harness, listed in FINAL_STEPS.)
8. **Onboarding:** upload 3 files at once incl. portrait + 4K; live analysis view streams boxes; Excel import of 3 rows (one valid RTSP from `live_from_file.ps1`, one wrong password, one unreachable) shows correct statuses and adds the working one; RTSP builder test-connection works.
9. **UI:** Playwright screenshots of every screen at 390 px and 1440 px, both themes, reviewed by you; no overflow; all clips play in real Chrome.
10. **Report:** a Hindi and an English incident PDF render Devanagari correctly, include hashes, and open in a browser.
11. **Regression:** all v1 tests + new tests green; `npm run lint` + `npm run build` clean; `smoke.ps1` updated and PASS.
12. **Judge demo run-through** (scripted in FINAL_STEPS, executed once end-to-end by you): load the hackathon clip (or any uploaded clip) → live analysis view → "kitne log aaye?" with receipts + proof reel → photo search + journey → teach an object by voice → replay → live alert in web + Telegram → incident PDF → Metrics with real unit costs. Record it with `scripts/demo_video.mjs --channel chrome`.

## H. Performance and robustness rules
- Never block the API event loop; long work goes to the worker/vision service with progress.
- All model calls have timeouts and fallbacks (TensorRT → ONNX → torch; SigLIP 2 → open_clip; Flex → Standard; luna → sol).
- Every background loop survives errors; every external call retries with backoff; every failure is visible in the UI as a clear message, not a spinner forever.
- Keep RAM under control (§W1.9). Release GPU memory when idle > 10 min (unload YOLOE/SigLIP; reload on demand).

## I. README and docs
Update README per v1 §22 with the v2 story: hero GIF/screenshot, the three pillars, "Show it · Say it · Find it", architecture diagram (now with the vision service, local index, Telegram, Realtime), evidence levels, privacy (no face recognition, blur at egress, audit log), **measured** speed/accuracy/cost tables (from scripts, dated), datasets used + licences, honest limitations (night/IR, crowds, small objects, heuristic security events = Candidates until verified), roadmap (Equal messenger agent, on-site box, ANPR, multi-site), how to run, how to connect cameras (incl. Excel), Telegram setup.

## J. Final handoff
Rewrite `FINAL_STEPS.md` for v2: env status (Telegram and Kaggle are already set; list anything still missing, e.g. optional `ROBOFLOW_API_KEY`), how to pair Telegram (Settings → code → `/pair <code>` to @nazar_hackathon_bot), check commands, `start_all.ps1` (starts vision service, worker, API, web, Telegram bot), the judge demo script (≈ 4 min, exact questions in Hinglish/Hindi/English, which buttons), how to process the hackathon clip, AWS deploy pointer (deploy kit updated for v2: CPU paths/OpenVINO on EC2, WebRTC ports, Telegram on the server), submission checklist, known issues with verification commands. Also update `CLAUDE.md` so it matches v2 (blur at egress instead of blur-before-save, vision service, local index, WebRTC live view, new rules). Print FINAL_STEPS.md as your final message.

## K. Git rules (unchanged from v1 §19 — follow exactly)
Remote `https://github.com/Shivansh0911/Nazar.git`, branch `main`; the user's git identity only; **no AI attribution anywhere** (no Co-Authored-By, no "Generated with", keep `.claude/settings.json` `{"includeCoAuthoredBy": false}`); Conventional Commits in a human tone (`feat(search): local visual index with SigLIP 2`, `perf(edge): TensorRT batched detection, 18x real time`, `feat(telegram): voice-note questions and alerts`, `fix(clips): baseline H.264 for Safari`); commit coherent working units only, never a broken build; push after each workstream; never commit `.env`, keys, data, videos, datasets, model weights; secret-scan before the final push.

## L. Definition of done (v2)
- [ ] All P0 workstreams done and their acceptance tests (§G) passing; P1 done or explicitly listed as not done in PROGRESS/FINAL_STEPS with the reason.
- [ ] Every feature works locally with real data (no mocks in product, no demo-only code paths).
- [ ] Measured numbers (speed, accuracy, latency, unit costs) in README and Metrics, dated.
- [ ] UI redesigned, responsive, reviewed at 390 px and 1440 px; all clips play.
- [ ] Privacy rules hold (spot-check 10 served media files: faces blurred; no face-search path exists).
- [ ] Tests, lint, build green; `smoke.ps1` PASS; deploy kit still validates (`docker compose config`, `caddy validate`).
- [ ] FINAL_STEPS.md v2 written, committed, pushed, printed.
