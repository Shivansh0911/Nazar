# FINAL STEPS (v3) — what you do now

Nazar v3 is built and tested on this laptop with your real keys, committed and pushed (`main`). Everything below is
PowerShell from the repo root. Nothing was created on AWS.

## 1. Environment (`.env`)
| Key | Status | Needed for |
|---|---|---|
| `OPENAI_API_KEY` | ✅ set (5/5 models OK) | all AI features |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME=nazar_hackathon_bot` | ✅ set (bot reachable) | Telegram bot |
| `KAGGLE_*` | ✅ set | MOT17 tracking eval |
| `FERNET_KEY` | ✅ auto-generated | encrypts camera passwords — keep it, never commit |
| AWS keys, `S3_BUCKET` | empty | only for deploy (Workshop page → refresh on `ExpiredToken`) |

## 2. Check everything (what each proves: `docs/TEST_PLAN.md`)
```powershell
.\.venv\Scripts\Activate.ps1
python scripts/check_env.py; python scripts/check_models.py
cd backend; python -m pytest -q; python -m pytest -q -m live; cd ..     # unit + every API route + triggers + telegram
python scripts/privacy_spotcheck.py        # served media -> 0 faces found
python scripts/eval_counts.py              # 3/3 windows exact
python scripts/eval_voice_matrix.py        # 12 voice notes, 8 languages
python scripts/eval_battery.py             # 32 questions, latency p50/p90, cost
cd web; node ../scripts/e2e.mjs --viewport both --theme dark; cd ..   # real Chrome, every clip must play
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
```

## 3. Start
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
```
Docker (Postgres + MediaMTX), vision service (:8010), worker, API (:8000), web (:3000), Telegram bot. Open
**http://localhost:3000**, passcode `nazar2026`. 8 GB laptop: close other apps (vision ~2.8 GB; the API grows to ~2.4 GB
after teaching objects — restart it if memory runs low).

## 4. Telegram — the 60-second phone test (please do this; also screen-record it for the film)
1. Web app → **Settings** → **Get pairing code**.
2. Telegram → **@nazar_hackathon_bot** → send `/pair <code>` → "Jud gaya ✅".
3. Send a voice note: *"kal raat counter pe kitne log aaye?"* → text + voice reply + clip.
4. Trigger an alert: Ask (camera Office desk) → *"Jab bhi koi desk 14 se bag uthaye, mujhe batana"* → Activate → Live →
   Office desk → Play as live → ~5 min later the alert (snapshot + voice note + clip) lands on the phone.
5. `python scripts/telegram_selftest.py` then sends the latest alert + digest to your paired chat and prints message ids.
Save the phone screen recording as `demo\telegram_phone.mp4`, then rebuild the film:
`python scripts/film_build.py --telegram demo/telegram_phone.mp4`.

## 5. Judge demo (film order, ≈ 5 min)
Today → Add camera (upload the venue clip, live analysis; CCTV test connection; Excel; phone QR) → zones → Ask
*"Builders venue pe kitne log dikhe?"* (Confirmed, receipts, proof reel) → *"Which camera was busiest and at what hour?"*
(SQL shown) + heatmap → Hindi voice note (spoken Hindi reply) → face request refused → Search (words, verify, journey,
photo) → teach *"kursi"* + teach by photo → rule *"Jab bhi koi desk 14 se bag uthaye…"* (would have fired N times) →
Activate → Live (WebRTC, boxes, faces blurred) → alert with voice note → incident PDF (hashes) → security events →
Telegram pairing → Insights (₹0 to index, ₹ per question, speed, accuracy).

## 6. Demo film
- **`demo\nazar_film.mp4`** — narrated (AAC audio: narrator + the owner's Hindi voice note + Nazar's spoken Hindi reply
  + the alert's voice note). Rebuild: `cd web; node ../scripts/demo_full.mjs --wav ..\demo\q_hi.wav --photo ..\demo\bag_photo.jpg; cd ..;
  python scripts/film_build.py`.
- `demo\nazar_full.mp4` (silent, captions) and `demo\nazar_v2.mp4` (short v2 cut). Videos are not committed — upload them.

## 7a. Live link (deployed 22 Nov 2026)
**https://main.d3c12rzknieyam.amplifyapp.com**, passcode `nazar2026`. The web app is on AWS Amplify (app `nazar`).
The API runs on this laptop through a Cloudflare quick tunnel. Keep the laptop on, with `start_all.ps1` running, and:
```powershell
# 1) tunnel (prints a new https://<words>.trycloudflare.com URL each time)
& "$env:LOCALAPPDATA\Nazar\bin\cloudflared.exe" tunnel --no-autoupdate --url http://localhost:8000
# 2) restart the API with that URL (replace <URL>)
$env:API_BASE_URL="<URL>"; $env:WEB_ORIGINS="https://main.d3c12rzknieyam.amplifyapp.com,http://localhost:3000"
cd backend; python -m uvicorn nazar.api.main:app --host 0.0.0.0 --port 8000
# 3) only if the tunnel URL changed: rebuild the web with it and redeploy to Amplify
cd web; $env:NEXT_PUBLIC_API_BASE_URL="<URL>"; npm run build   # zip out/ with forward slashes, Amplify -> Deploy updates
```
The tunnel URL changes if `cloudflared` restarts. Then repeat steps 2 and 3. A named Cloudflare tunnel gives a fixed URL.
Why not EC2: the account's one allowed instance is the organisers' Code Editor machine.

## 7. Full cloud deploy (when you decide)
`infra/DEPLOY.md`: one CPU EC2 + RDS + S3 + Amplify; `docker compose -f infra/docker-compose.prod.yml config -q` and
`caddy validate` (with `DOMAIN` set) pass. You approve every AWS resource; never GPU instances, never Bedrock.

## 8. Known issues (honest numbers, 22 Nov 2026)
| Item | Status |
|---|---|
| Answer latency | count questions ~2.5 s (one model round); 6-question profile p50 4.1 s, first words 3.3 s; 32-question battery p50 9.0 s, first words 7.2 s (multi-tool questions 8–15 s) |
| Live edge | loop ~8 fps with all services up (was ~3), ~6 frames/s analysed; target 8 |
| Dense footage | 8.9× real time (venue clip 17.7×); target 15× not met |
| Telegram on a real phone | not yet tested — §4 |
| UI | Night-shift redesign of every page done; public story landing page, 3D login camera and ⌘K bar not done |
| Film | `demo\nazar_film.mp4` 7:05 on the Night-shift UI, with sound (narrator + real Hindi voice note + spoken Hindi reply + alert voice note + closing line); no Remotion title scenes, 1440×900, no 2-minute cut |
| Spoken Hinglish | transcribed in Devanagari → the voice reply comes in Hindi script |
| Running / fall / snatch | unit-tested on synthetic paths only (no real clip; snatch dataset not downloaded) |
| Marathi voice | not claimed |
| Chrome DevTools MCP | fails to connect (Playwright covers the checks) |
| Memory | 8 GB is tight: an upload failed once with "unable to allocate" while everything + Chrome recording ran |

## 9. Submission checklist
- [ ] Repo https://github.com/Shivansh0911/Nazar (pushed)
- [ ] Upload `demo\nazar_film.mp4` and paste its link in the README ("Demo film")
- [ ] Do the Telegram phone test (§4) before presenting; run `scripts\smoke.ps1` once
