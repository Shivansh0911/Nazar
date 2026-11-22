# Nazar — ask your CCTV anything (setup, launch and use)

> **Live demo:** https://main.d3c12rzknieyam.amplifyapp.com — passcode **`nazar2026`**
> (web app on AWS Amplify; the API runs on the builder's GPU laptop through a secure tunnel, so it is up only while
> that laptop is on — if it does not load, run it yourself with the steps below: it is the same product).
> **Code:** https://github.com/Shivansh0911/Nazar · **Demo film:** see `VIDEO.md` · **Full test plan:** `docs/TEST_PLAN.md`

### Credentials at a glance
| What | Login / password | Where |
|---|---|---|
| Web app (owner — the only user role) | passcode **`nazar2026`** (no username) | http://localhost:3000/login/ · live demo above |
| API | `POST /api/auth` with `{"passcode":"nazar2026"}` → token → header `X-Nazar-Token: <token>` | http://localhost:8000 · Swagger UI `/docs` |
| Postgres (Docker) | user **`nazar`**, password **`nazar`**, database **`nazar`** | `localhost:5433` (`DATABASE_URL` in `.env`) |
| Telegram bot | no password: web app → Settings → **Get pairing code** → send `/pair <code>` to the bot | needs `TELEGRAM_BOT_TOKEN` in `.env` |
| Phone camera / RTSP | no password for local MediaMTX; DVR passwords you enter are stored encrypted | Cameras → Add camera |
| OpenAI | `OPENAI_API_KEY` in `.env` (a budget-capped test key if one is supplied with the submission) | `.env` |
Change the passcode with `DEMO_PASSCODE=` in `.env` and restart the API.

### 5-minute quick start (Linux/macOS)
```bash
cp .env.example .env            # put OPENAI_API_KEY=... in it (skip if the zip already has a .env)
bash scripts/setup.sh           # installs everything (first run ~5-10 min: PyTorch + models)
bash scripts/start_all.sh       # API :8000, web :3000, vision :8010, worker (+ Telegram bot)
source .venv/bin/activate && python scripts/demo_setup.py   # demo cameras (GPU ~3 min, CPU ~15 min)
# open http://localhost:3000  ->  passcode nazar2026  ->  Ask: "Builders venue pe kitne log dikhe?"
```

Nazar turns any camera (a shop DVR over RTSP, a phone, or a video file) into something you can talk to, in Hindi,
English or Hinglish (and Tamil, Telugu, Bengali, Gujarati, Kannada by voice):
**Ask** ("Raat 2 baje ke baad counter pe kitne log aaye?") → a number counted from the database, with the receipts
(every counted person, playable) · **Search** footage by words or by a photo, like Google Photos · **Teach** it any
object or a rule in your own words — it checks yesterday's footage first, then watches live and alerts you (web +
Telegram, with a voice note) · **Prove** it: FIR-ready incident PDF with SHA-256 hashes. Faces are blurred in
everything it shows or sends; there is no face recognition, ever. Indexing is local (₹0 in AI); you pay only per
question (~₹0.03).

---

## 1. Login (all user types)
| Touch point | How to get in |
|---|---|
| **Web app** (desktop + phone, installable PWA) | Open http://localhost:3000 (or the live demo) → passcode **`nazar2026`** → Continue. Tick "remember this device" to stay logged in. There is one user type: the **owner** (single passcode by design, set with `DEMO_PASSCODE` in `.env`). Wrong passcodes are rate-limited. |
| **API** | `POST http://localhost:8000/api/auth {"passcode":"nazar2026"}` → `{"token": ...}`; send it as header `X-Nazar-Token` (or `?token=` on media URLs). Interactive docs: http://localhost:8000/docs |
| **Telegram bot** | Needs `TELEGRAM_BOT_TOKEN` (any bot from @BotFather). Web app → **Settings → Get pairing code** (6 digits, 10 min) → in Telegram send `/pair <code>` to the bot → "Jud gaya ✅". |
| **Phone as a camera** | Web app → Cameras → Add camera → **Phone** → scan the QR into the free *Larix Broadcaster* app (SRT/RTMP). |

## 2. Prerequisites (tested versions)
| Tool | Version | Notes |
|---|---|---|
| Python | **3.12** (3.12.5 tested) | one venv `.venv`, backend installed editable |
| Node.js / npm | **20.x / 10.x** (20.14 / 10.7 tested) | web app = Next.js 15 static export |
| Docker + compose plugin | 24+ (29.7 tested) | runs Postgres 16 + pgvector (`pgvector/pgvector:pg16`) and MediaMTX |
| ffmpeg | 6+ with libx264 (on PATH, or `FFMPEG_DIR`) | clips, proof reels, voice notes |
| GPU | optional | NVIDIA + CUDA 12.1 wheels are used if `nvidia-smi` works; **CPU works** (slower processing) |
| RAM / disk | 8 GB RAM minimum, ~6 GB disk (models + venv + demo data) | the vision service keeps SigLIP 2 loaded (~2.8 GB) |
| OpenAI API key | required for questions, voice, rules, verification, reports | see §3 |

## 3. Environment variables (`.env` at the repo root; template: `.env.example`)
`scripts/setup.sh` copies `.env.example` to `.env`. Only the first line is required; everything else has a working default.

| Variable | Needed? | Default / meaning |
|---|---|---|
| `OPENAI_API_KEY` | **required for AI features** | Ask (text + voice), rules, AI verification, incident-report descriptions, TTS replies. **Use a key with a small budget** (an OpenAI project key with a $5–10 limit is plenty: a question costs ~₹0.03 ≈ $0.0004). If the submission zip contains a `.env`, its key is such a budget-capped test key. |
| `OPENAI_AGENT_MODEL`, `OPENAI_AGENT_FAST_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_VISION_FALLBACK` | optional | `gpt-6-sol`, `gpt-6-luna`, `gpt-6-luna`, `gpt-5.4-mini` — model names are read only from env. If your account lacks a model, set these to models you have (e.g. `gpt-5.4-mini`) and run `python scripts/check_models.py`. |
| `OPENAI_EMBED_MODEL`, `OPENAI_TRANSCRIBE_MODEL`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` | optional | `text-embedding-3-small`, `gpt-4o-transcribe`, `gpt-4o-mini-tts`, `coral` |
| `DATABASE_URL` | optional | `postgresql://nazar:nazar@localhost:5433/nazar` (the Docker Postgres; host port **5433**) |
| `DEMO_PASSCODE` | optional | `nazar2026` — the login passcode |
| `API_BASE_URL` / `WEB_ORIGINS` | optional | `http://localhost:8000` / `http://localhost:3000` (change both when you host it elsewhere) |
| `STORAGE_MODE`, `DATA_DIR`, `S3_BUCKET`, `AWS_*` | optional | `local` storage in `./data` (or `DATA_DIR`); `s3` only for a cloud deploy |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_ALLOWED_CHAT_IDS` | optional | enables the Telegram bot |
| `FERNET_KEY` | optional | auto-generated on first use (encrypts camera passwords) |
| `ENRICH_MODE` | optional | `smart` (describe tracks on demand) · `full` · `off` |
| `MAX_EDGES`, `AUTO_START_EDGES`, `DETECT_FPS`, `DETECT_IMGSZ`, … | optional | pipeline tuning; defaults are what was measured |
| `NAZAR_BATCH` (process env) | optional | detector batch for uploaded files (16; use 8 on an 8 GB machine) |
| `KAGGLE_*`, `ROBOFLOW_API_KEY` | not needed | only for the optional evaluation scripts |

**Without an OpenAI key** the product still starts and these work: login, Today, cameras, zones/count lines, uploads
with the live analysis view, counts with receipts (`/api/count`), clips and proof reels, search by words/photo (the
local SigLIP 2 index), journeys, live view, security events, Insights. Asking questions, voice notes, rule compiling,
AI verification, report text and voice replies need the key (there is no mock LLM — the numbers always come from SQL).

## 4. Install, seed, start (exact commands)
### Linux / macOS (fresh server)
```bash
git clone https://github.com/Shivansh0911/Nazar.git && cd Nazar     # or unzip the submission
cp .env.example .env && nano .env                                     # paste OPENAI_API_KEY
bash scripts/setup.sh          # venv + PyTorch (CUDA or CPU) + backend + models + Docker DB/MediaMTX + migrations + web build + sample videos
bash scripts/start_all.sh      # starts vision service, worker, API, web (+ Telegram bot if its token is set), prints URLs
source .venv/bin/activate && python scripts/demo_setup.py    # seeds 7 demo cameras from samples/ (GPU ~3 min, CPU ~15 min)
```
Stop: `bash scripts/stop_all.sh`. Logs: `data/logs/*.log`. Re-seed from scratch: `python scripts/demo_setup.py --reset`.

### Windows 11 (PowerShell, the machine it was built on)
```powershell
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121   # or .../whl/cpu
pip install -e "backend[dev]"; python scripts/download_models.py
docker compose -f infra/docker-compose.yml up -d; cd backend; python -m nazar.core.migrate; cd ..
cd web; npm ci; npm run build; cd ..
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1      # opens one window per service
python scripts/demo_setup.py
```

### What runs where (URLs and ports)
| Part | Command (from `backend/` unless noted) | URL / port |
|---|---|---|
| Web app (static Next.js) | `python -m http.server 3000` in `web/out` (dev: `cd web; npm run dev`) | http://localhost:3000 |
| API (FastAPI + edge manager + WebSocket alerts) | `python -m uvicorn nazar.api.main:app --host 0.0.0.0 --port 8000` | http://localhost:8000 · docs `/docs` · health `/api/health` |
| Worker (events, rules, stitcher, riders, security, Flex AI checks, digest) | `python -m nazar.worker.run` | — |
| Vision service (SigLIP 2 local index) | `python -m nazar.vision.service` | http://localhost:8010/health |
| Edges (one per camera; started by the API) | `python -m nazar.edge.run --camera <id>` | — |
| Telegram bot (long polling) | `python -m nazar.telegram.run` | — |
| Postgres 16 + pgvector (Docker) | `docker compose -f infra/docker-compose.yml up -d` | localhost:**5433** (user/pass/db `nazar`) |
| MediaMTX (Docker) | same compose file | RTSP :8554 · WebRTC :8889 (+ ICE 8189/udp) · RTMP :1935 · SRT :8890/udp |

**Check it:** `python scripts/check_env.py` (every line ✅) · `python scripts/check_models.py` (each model OK) ·
`cd backend; python -m pytest -q` (118 passed, 1 skipped without OpenAI calls) · `curl localhost:8000/api/health`.

## 5. Demo data
`scripts/demo_setup.py` creates these cameras from the clips in `samples/` (sources and licences in
`samples/SOURCES.md`), stamped as last night's / this morning's footage so time questions make sense:
**Shop counter** (veg stall), **Market street**, **Main road** (bikes, autos), **Lobby** (busy mall), **Night stall**
(after midnight), **Office desk** (a bag is left on desk 14 and later taken — the rule/alert demo) and
**Builders venue** (a real clip filmed at the hackathon venue) — 7 cameras. If `samples/*.mp4` are missing,
`python scripts/fetch_samples.py --no-extras` downloads the public ones; `hackathon.mp4` (Builders venue) ships in the
submission zip.

## 6. Journeys to try end to end
**A. Owner on the web (desktop)** — log in → **Today** (every camera, overnight digest, alerts) →
1. **Count with receipts:** Ask → *"Builders venue pe kitne log dikhe?"* → a Confirmed number (from SQL), a per-minute
   chart, every counted person as a receipt (tap one to play its clip) → **Play proof reel**.
2. **Any analysis:** *"Which camera was busiest and at what hour?"* → table + chart → **How this was computed** shows the
   one read-only SQL query. *"Lobby mein log kahan sabse zyada ruke? Heatmap dikhao"* → heatmap.
3. **Hindi voice note:** tap the amber mic, say *"रात 2 बजे के बाद नाइट स्टॉल पर कितने लोग आए?"* → reply in Devanagari +
   a spoken answer (6 people).
4. **Privacy:** *"Find this person's face in all cameras"* → polite refusal, offers clothing/object search instead.
5. **Search like Google Photos:** Search → *"person carrying a bag"* → **Verify top 8 with AI** (Probable = similar
   look AND AI agrees; Candidates stay dashed) → **Journey** on a hit → **Photo** → upload any photo of a bag + a purpose
   (audited).
6. **Teach it anything:** Ask → *"Builders venue pe kursi (chair) pe nazar rakho"* → open-vocabulary detection, replayed
   on stored frames first. Or on a camera page: **teach from a photo**.
7. **Rule + live alert:** Ask (camera dropdown: Office desk) → *"Jab bhi koi desk 14 se bag uthaye, mujhe batana"* →
   "would have fired N times yesterday" → **Activate** → **Live** → Office desk → **Play as live** → in ~5 min the person
   takes the bag → **alert** (snapshot, clip, Hinglish voice note) in the web app (and on Telegram if paired).
8. **Proof:** Alerts & rules → **Incident report (PDF)** → timeline, blurred frames, AI description (marked as AI),
   evidence levels, SHA-256 hashes. **Security events** tab: object taken, abandoned bag, loitering, crowding, after-hours.
9. **Add any camera:** Cameras → Add camera → **Upload video** (any MP4; live analysis view at ~15× real time on a GPU)
   · **CCTV / DVR** (Hikvision/Dahua/CP Plus presets, Test connection explains failures) · **Excel import** · **Phone**.
10. **Insights:** ₹0 to index, measured ₹ per question, answer speed, pipeline speed, count accuracy, MOT17 tracking.

**B. Owner on a phone (390 px)** — same app, bottom tab bar (Today · Ask · Search · Alerts · More); answers show a
"N receipts" chip that opens the evidence sheet.

**C. Telegram** (with a bot token): pair (§1) → send a voice note *"kal raat counter pe kitne log aaye?"* → text +
voice note + clip; send a photo of a bag → audited photo search; `/today` digest; `/cameras`; `/report` → PDF; alerts
from active rules arrive with snapshot + voice note + clip.

**D. API only:** `POST /api/ask {"text":"How many people were seen at the office desk?"}` → JSON with `count.value`
and the receipts; `GET /api/count?camera_id=office-desk&from=...&to=...`; `POST /api/search/visual` (form `text=...`).

## 7. What is simulated, mocked or not finished
- **Simulated:** the demo cameras are recorded clips stamped as last night's footage; "live" in the demo is a recorded
  file played in real time (**Play as live**) — real RTSP/phone cameras use the same path (`scripts/live_from_file.ps1`
  publishes a file as an RTSP camera through MediaMTX).
- **Live demo hosting:** web on AWS Amplify, API on the builder's laptop via a tunnel (the account's single EC2 slot is
  the organisers' code editor). A full cloud deploy (one CPU EC2 + RDS + S3 + Amplify) is documented in `infra/DEPLOY.md`
  but was not run.
- **Not finished / limits (measured 22 Nov 2026):** busy-footage processing 8.9× real time (goal 15×; venue clip
  17.7×); live loop ~8 fps (~6 analysed/s) with everything running; multi-tool questions take 8–15 s (count questions
  ~2.5 s); spoken Hinglish is transcribed in Devanagari, so the voice reply comes back in Hindi script; running/fall
  detection is only tested on synthetic paths; snatch dataset not evaluated; Marathi voice not supported; "Call Nazar"
  realtime voice, public landing page, 3D login camera and ⌘K bar not built; Telegram was tested with the real handlers
  offline but not on a phone; CPU-only machines process footage several times slower.
- **No mocks in the product:** counts always come from SQL; evidence levels are decided by server code; without an
  OpenAI key the AI features are simply unavailable (§3).

## 8. Repository map
```
backend/nazar/   core/ (config, db, rules, riders, levels, storage) · edge/ (camera → detection/tracking/blur)
                 worker/ (events, rules, stitcher, security, alerts) · api/ (FastAPI routes, agent, search, reports)
                 vision/ (SigLIP 2 service) · telegram/ (bot) · sql/ (migrations)   backend/tests/ (pytest)
web/             Next.js app (app/ pages, components/, lib/ API client)
infra/           docker-compose.yml (Postgres + MediaMTX), prod compose, Caddy, MediaMTX config, DEPLOY.md
scripts/         setup.sh / start_all.sh / stop_all.sh (+ .ps1), demo_setup.py, fetch_samples.py, download_models.py,
                 eval_*.py, e2e.mjs (browser suite), privacy_spotcheck.py, film_build.py
samples/         demo clips (+ SOURCES.md licences) · docs/ (TEST_PLAN.md, screenshots) · README.md (story + results)
```
