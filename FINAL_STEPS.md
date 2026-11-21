# FINAL STEPS (v2) — what you do now

Nazar v2 is built, tested on this laptop with your real keys, committed and pushed (`main`). Everything below is
PowerShell from the repo root. Nothing was created on AWS.

## 1. Environment status (`.env`)
| Key | Status | Needed for |
|---|---|---|
| `OPENAI_API_KEY` | ✅ set (5/5 models OK) | all AI features |
| `TELEGRAM_BOT_TOKEN` | ✅ set · `TELEGRAM_BOT_USERNAME=nazar_hackathon_bot` added | Telegram bot |
| `KAGGLE_API_TOKEN` / `KAGGLE_USERNAME` / `KAGGLE_KEY` | ✅ set (not used yet — dataset evals were skipped, see §8) | optional evals |
| `FERNET_KEY` | ✅ generated automatically on first use | encrypts camera passwords — keep it, never commit |
| `ROBOFLOW_API_KEY` | empty (optional) | Indian-vehicle fine-tune (not done) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`, `S3_BUCKET` | empty | only for deploy (Workshop page → refresh when `ExpiredToken`) |

## 2. Check commands
```powershell
.\.venv\Scripts\Activate.ps1
python scripts/check_env.py                       # every line ✅
python scripts/check_models.py                    # 5/5 models OK
cd backend; python -m pytest -q; cd ..            # 74 passed, 1 skipped (the no-key test)
cd web; npm run lint; npm run build; cd ..        # clean
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1   # SMOKE: PASS (health, ask, rule, vision index, visual search, receipts, security, metrics)
```
Re-measure anytime: `python scripts/eval_battery.py` (27 questions), `python scripts/eval_counts.py`,
`python scripts/eval_languages.py`, `python scripts/bench_pipeline.py`, `python scripts/live_alert_test.py [--teach]`.

## 3. Start everything
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
```
Opens windows for: Docker (Postgres + MediaMTX), **vision service** (SigLIP 2, :8010), worker, API (:8000), web
(:3000) and the **Telegram bot** (because the token is set). Open **http://localhost:3000**, passcode `nazar2026`.
Close heavy apps first — the laptop has 8 GB and the vision service uses ~2.8 GB while indexing.

## 4. Pair Telegram (2 minutes, needs your phone)
1. Web app → **Settings** → **Get pairing code** (6 digits, valid 10 min; a QR opens the bot).
2. In Telegram, open **@nazar_hackathon_bot** and send `/pair <code>` → "Jud gaya ✅".
3. Try: a voice note *"kal raat counter pe kitne log aaye?"*, a photo of a bag, `/today`, `/report`.
   Alerts from active rules now arrive there with snapshot, clip and voice note.
(Your earlier `/start` was sent before the bot ran, so it was not seen — pairing needs a fresh `/pair`.)

## 5. Judge demo script (≈ 4 minutes)
1. **Today** (home): cameras incl. *Builders venue* (the clip from this venue), overnight digest, alerts.
2. **Any video, analysed live:** Cameras → **Add camera → Upload video** → drop `samples\hackathon.mp4` (or a
   judge's phone video) → the live analysis view shows boxes and counts at ~15× real time → **Ask about it**.
3. **Count with receipts:** Ask → *"Builders venue pe kitne log dikhe?"* → Confirmed number, receipts, tap
   **Play proof reel**.
4. **Any analysis:** *"Which camera was busiest and at what hour?"* → table + chart → **How this was computed**.
5. **Search like Google Photos:** Search → *"person carrying a bag"* → **Verify top 8 with AI** (Probable =
   AI-verified) → **Journey** on a hit. Then **Photo** → upload `demo\bag_photo.jpg` (purpose: "lost bag").
6. **Teach:** Ask → *"Builders venue pe laptop pe nazar rakho"* → it replays on stored frames first, then watches live.
7. **Rule + live alert:** Ask (camera: Office desk) → *"Jab bhi koi desk 14 se bag uthaye, mujhe batana"* →
   "would have fired 1 time" → **Activate** → Live → Office desk → **Play as live** → ~2.5 min later the alert
   arrives (web + Telegram) with snapshot and voice note.
8. **Incident report:** Alerts & rules → **Incident report (PDF)** → timeline, blurred frames, SHA-256 hashes.
9. **Insights:** ₹0 to index, ₹ per question (measured), the cost calculator, speed and accuracy tables.
Hindi: *"रात 2 बजे के बाद night stall पर कितने लोग आए?"* · Face request: *"Find this person's face"* → polite refusal.

Recorded run-through: `demo\nazar_v2.mp4` (re-record: `cd web; node ../scripts/demo_video_v2.mjs --channel chrome
--photo ..\demo\bag_photo.jpg; cd ..; python scripts/make_demo_mp4.py`).

## 6. Process the hackathon clip (already done) / your event camera
- The clip is processed as camera **Builders venue** by `python scripts/demo_setup.py` (manifest entry with
  `start: file` = its own recording time). Any other file: Add camera → Upload video.
- **Your live event camera:** Add camera → **CCTV / DVR** (brand preset or URL → **Test connection** → Add) or
  **Phone** (Larix QR). It starts live; draw zones/count lines on its camera page; teach objects there too.

## 7. Deploy (when you decide)
Follow `infra/DEPLOY.md` (one CPU c7i.xlarge EC2 + RDS + S3 + Amplify). v2 additions: the prod compose now runs
`vision` (SigLIP 2 on CPU) and `telegram` services; the image installs Chromium + Noto fonts for Hindi PDFs.
Validate: `docker compose -f infra/docker-compose.prod.yml config -q`. You click/approve every AWS resource;
never GPU instances, never Bedrock.

## 8. Known issues and what was not done
| Item | Status / why | How to verify / next step |
|---|---|---|
| Answer latency | p50 8.8 s full, first words 7.0 s (targets 5 s / 2.5 s not met) | Insights → Answer speed; `eval_battery.py` |
| Dense footage speed | 8.9× real time on rush-hour footage (17.7× on the venue clip); goal 15× | `bench_pipeline.py` |
| Counting over-count | riders and half-hidden people add tracks (venue 5 vs 3, shop 4 vs 3) | `eval_counts.py` |
| W10 WebRTC live view | **not done** — live wall uses the face-blurred MJPEG with tracker boxes | Live page |
| W7 "Call Nazar" realtime voice | **not done** (P2) | — |
| YOLOE photo prompts | not done (text prompts work) | Camera page → Teach |
| MOT17 / snatch datasets | **not downloaded** (multi-GB); evaluation uses hand counts + demo clips | `eval_counts.py` |
| Marathi voice | transcription returned Gurmukhi script → not claimed | `eval_languages.py` |
| Telegram end-to-end | bot runs and polls; pairing/voice/alert delivery need your phone (§4) | §4 |
| Memory | ~0.6 GB free with everything running on 8 GB | close other apps |
| Backend Docker image | not rebuilt here (PyPI timeouts earlier) | `docker build -f infra/Dockerfile.backend .` on EC2 |

## 9. Submission checklist
- [ ] Repo: https://github.com/Shivansh0911/Nazar (pushed, README renders with v2 screenshots)
- [ ] Demo video: `demo\nazar_v2.mp4` (upload it; it is not committed)
- [ ] Slides from README: problem → three pillars → how it works (Mermaid + evidence levels) → measured results → privacy → roadmap
- [ ] Pair Telegram before presenting (§4); close heavy apps; run `scripts\smoke.ps1` once
