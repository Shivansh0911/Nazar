# FINAL STEPS — what you do now

Everything that runs without secrets is built and checked: edge, worker, API, web, live RTSP path, demo data,
deploy kit. These steps take it to a working AI demo and a submission. Commands are PowerShell, from the repo root.

## 0. Push the code (one time)
Git Credential Manager needs a GitHub sign-in on this machine:
```powershell
git push origin main          # sign in when the browser/dialog opens; all local commits go up
```

## 1. Paste these into `.env`
| Key | Where to get it | Needed for |
|---|---|---|
| `OPENAI_API_KEY` | platform.openai.com → API keys → Create new secret key | all AI features (ask, voice, captions, rules, TTS) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Workshop page → **Get AWS CLI credentials** (they expire — refresh when AWS says `ExpiredToken`) | only if you use S3 from the laptop; **not** needed on EC2 (instance role) |
| `S3_BUCKET` | the bucket name you create in `infra/DEPLOY.md` step 1 | only when `STORAGE_MODE=s3` (deploy) |

Leave everything else as is. Never commit `.env`.

## 2. Run these checks (in order)
```powershell
.\.venv\Scripts\Activate.ps1
python scripts/check_env.py                 # success: every line ✅ (OPENAI_API_KEY now ✅)
python scripts/check_models.py              # success: "5/5 models OK"
cd backend; python -m pytest -m live -q; python -m pytest -q; cd ..   # success: all passed
```
- `check_models` says the vision model is not found → put `OPENAI_VISION_MODEL=gpt-5.4-mini` in `.env` (the
  app also falls back automatically) and, if it is not in the price table, add
  `PRICES_JSON={"gpt-5.4-mini": {"input": <usd/1M>, "cached": <usd/1M>, "output": <usd/1M>}}`.
- `insufficient_quota` / 401 → OpenAI credits/key problem: check billing and the key.

Then enrich the demo data and smoke-test (the worker captions existing tracks automatically, ~600 tracks, cost shown):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1      # opens worker, API, web windows
python scripts/demo_setup.py --manifest samples/demo_manifest.yaml  # waits until every job is "ready" (enriched)
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1           # success: "SMOKE: PASS"
```
If `smoke.ps1` fails on *ask*: read the Detail column (503 = key not loaded → restart the API window).

## 3. Start the demo locally
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
```
Open **http://localhost:3000** — passcode **`nazar2026`** (`DEMO_PASSCODE` in `.env`). Use Chrome; the mic works
on localhost. For the phone on the same Wi-Fi use `http://<laptop-ip>:3000` (mic needs HTTPS there → type, or use
the deployed HTTPS URL).

## 4. Demo script for judges (≈4 minutes)
1. **Hook (Chat, All cameras):** tap the lime mic and say *"Kal raat 10 baje ke baad shop counter pe kitne log aaye?"*
   → spoken Hinglish reply, a **Confirmed** count with the hourly chart. Open a clip: the box follows the person,
   the face is blurred.
2. **Describe someone:** *"Show me people carrying a bag on the market street this morning"* → clips with
   **Probable / Candidate** badges and the "why" line. Point out the dashed Candidate badge: never shown as the answer.
3. **Hindi:** *"रात 2 बजे के बाद night stall पर कितने लोग आए?"* → Devanagari reply + voice.
4. **Find again:** open any person clip → **Find again** → same-looking people ±24 h (no face recognition).
5. **Teach (camera picker → Office desk):** say *"Jab bhi koi desk 14 se bag uthaye, mujhe batana"* → rule card:
   *"Would have fired 1 time"* (last night 21:51) with the thumbnail of the person who took the bag → tap **Activate**.
6. **Live alert:** in a terminal run `powershell -ExecutionPolicy Bypass -File scripts\demo_live.ps1 -Camera office-desk`
   (or Cameras → Office desk → **Play as live**). ~2 minutes into the loop the person takes the bag → a red alert
   bubble with snapshot + voice note arrives in ~4 s. (Real RTSP path instead:
   `scripts\live_from_file.ps1 samples\clip6_bag.mp4 desk-live`, then add camera `rtsp://localhost:8554/desk-live`.)
7. **Cost (Metrics):** ₹ per camera-day vs. the naive "every frame to AI" number and the ratio.
8. **Any video:** Cameras → Add camera → Upload a judge's phone video → progress → *Ready — ask about it*.

## 5. Deploy to AWS (optional for judging)
Follow `infra/DEPLOY.md`. You decide/click three things: (1) create the S3 bucket + IAM role + RDS in the console,
(2) launch **one** c7i.xlarge EC2 (no GPU) with that role and an Elastic IP, (3) upload `web/out` to Amplify after
building with `NEXT_PUBLIC_API_BASE_URL=https://<ip-with-dashes>.sslip.io`. Nothing was created on AWS for you.

## 6. Fill the README numbers
```powershell
python scripts/cost_report.py                       # ₹/camera-day, naive ₹, ratio -> README "Measured results"
python scripts/eval_search.py                       # hit@3, confidently-wrong (fill truth windows in scripts/eval/questions.yaml first)
python scripts/eval_counts.py --camera lobby --zone entrance --from "<..>" --to "<..>" --truth <your count>
cd web; node ../scripts/screenshots.mjs --ask "Kal raat 10 baje ke baad shop counter pe kitne log aaye?" --ask "Show me people carrying a bag on the market street this morning"; cd ..
git add README.md docs/screenshots; git commit -m "docs: measured results and screenshots"; git push
```
(Put `docs/screenshots/chat.png` as the README hero image once it exists.)

## 7. Submission checklist
- [ ] Repo link: https://github.com/Shivansh0911/Nazar (pushed, README renders)
- [ ] Demo: deployed URL, or a 2-minute screen recording of section 4
- [ ] 4–5 slides — copy from README: *The problem* → *What Nazar does* (table) → *How it works* (Mermaid +
      evidence-level table) → *Measured results* → *Roadmap*
- [ ] Mention the SETU lineage (README "Built on")

## 8. Known issues / not verified here
| Item | Why | Verify with |
|---|---|---|
| Real OpenAI calls (ask, voice, captions, compile, TTS, suggest-zones, vision confirm) | no key in this session; plumbing tested with a fake client | `python scripts/check_models.py`, `pytest -m live`, `scripts\smoke.ps1` |
| gpt-6-luna / gpt-6-sol availability and prices | from the spec, not checked live | `check_models.py`; `PRICES_JSON` if needed |
| Phone via Larix | no phone stream here; the same RTSP path is verified with `live_from_file.ps1` | Add camera → Phone, stream, watch the camera page |
| EC2 CPU fps / Docker image on EC2 | not deployed | `infra/DEPLOY.md` step 6 |
| `git push` | needs your GitHub sign-in | `git push origin main` |
| Backend Docker image | 4 builds here failed only on PyPI read timeouts inside Docker's VM (Dockerfile steps themselves ran) | `docker build -f infra/Dockerfile.backend -t nazar-backend .` on a good connection, or on EC2 (DEPLOY step 6) |
| 8 GB laptop | other apps (SETU containers, VS Code) leave little RAM; edges take ~30 s to start | close heavy apps before the demo |
