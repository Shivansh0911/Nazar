# NAZAR v3 — Final polish: verify everything, redesign the UI, tell the story, make the demo film

> **How to use this spec:** Save it verbatim as `BUILD_PROMPT_V3.md` in the repo root. Read it fully, then `CLAUDE.md`, `BUILD_PROMPT_V2.md`, `PROGRESS.md`, `FINAL_STEPS.md` and the code. v2 works and is pushed (`7c25b2e`). This is the **last round of changes before the project is locked and deployed** — quality over quantity, nothing half-done, `main` always working. Secrets are in `.env`. Work through phases P1 → P5 **in order and inside their time boxes (§0)**. After each phase: checks green → `PROGRESS.md` updated (v3 section) → commit + push (git rules §8). You verify everything yourself (Playwright, screenshots, frames, audio you analyse) — the user is not checking.
>
> **If you are resuming:** read `PROGRESS.md` → continue from its v3 "exact next step", respecting the clock in §0.

---

## 0. How to finish (no clock deadline — but no endless loops)
Last time the work never stopped: it kept polishing and re-checking. This time each phase has a clear **"done when"** list. Work through P1 → P5 in order; when a phase's checks pass, **be confident: wrap it up (PROGRESS.md, commit, push) and move to the next phase immediately.** Do not go back to polish a finished phase unless a later check proves it broken.
- **Done means done:** when the "done when" list of a phase is satisfied, stop working on that phase. "It could be a bit better" is not a reason to continue.
- **No loops:** never retry the same failing approach more than **2 times**. If one issue is still not fixed after about **20 minutes** of focused work, record it in PROGRESS.md "Known issues" (what you tried, why it failed, how to verify later) and move on.
- **Optional items** (marked optional below) are attempted only after everything else in their phase is done, get one honest attempt, and are dropped if they fail.
- **No new features in P3–P5** — only fixes.
- **After P5 you are finished:** print the final report (§7) and FINAL_STEPS.md and end the session. Do not start extra rounds of improvements.

---

## 1. Facts from the v2 review (do not re-discover)
**Works:** upload with live analysis view, CCTV builder + test connection, Excel import, phone QR, zones + count lines, counts with receipts (SQL), any-analysis with SQL shown, heatmap, Hindi voice note → Hindi spoken reply, face request refused, search by words/photo with AI-verified top hits, journey, teach by text (chair) and photo, rule by voice → replay → live alert, WebRTC live view with overlay, incident PDF with hashes, security pack/events, Telegram bot running, Insights with measured costs (₹0 to index, ~₹0.30 per question). 74 tests pass, smoke PASS. Demo `demo/nazar_full.mp4` exists (4:49) but **has no audio track**.
**Gaps / bugs seen in the review video and FINAL_STEPS §8:**
1. **Proof reel modal showed a black video** in the recording — verify it plays in real Chrome; fix if not (codec/size/poster/autoplay/muted attribute/`playsInline`).
2. Answer latency p50 9.7 s (first words 8.0 s in one run, 5.4 s in another) — target first words ≤ 3 s, full ≤ 6 s for common questions.
3. Live detection 2.3 fps under load — target ≥ 8 fps for one live camera with everything else running.
4. Dense footage 8.9× real time (target 15×; venue clip 17.7×) — improve only if a quick, safe win exists (≤ 30 min); otherwise report honestly.
5. **Motorcycle riders counted as people** (shop counter 4 vs 3) — a person whose box overlaps a motorcycle/bicycle track for > 60 % of their shared time is a **rider**: counted under "riders/vehicles", excluded from "people on foot"; label it in answers. Unit test + re-run eval_counts.
6. Telegram: pairing, voice notes, alerts never tested end-to-end with a phone.
7. "Call Nazar" realtime voice (W7) not done.
8. Snatch/theft dataset evaluation not done.
9. Marathi voice fails (don't claim it).
10. Chrome DevTools MCP added but fails to connect.
11. Backend Docker image never built successfully (network timeouts).
12. UI looks like a generic dark-navy dashboard template; intro/outro slides are a plain blue gradient — "AI slop". Captions in the video were too small to read (recorded at 1440×900).

---

## P1 — Verify every logic path, build a real test suite, fix what fails
Goal: prove that every feature works for real and stays working. Write tests that would catch regressions, run them, fix failures (respecting the no-loop rules in §0).
1. **Test inventory:** create `docs/TEST_PLAN.md` — a table of every feature (from §1 "Works" + every API route + every screen + bot commands + voice paths + rules/triggers + security events + reports + metrics) → the test that covers it → status. Every row must end up ✅ or listed as a known issue.
2. **Backend tests (pytest):** keep the 74; add integration tests against the dev DB + real services for every API route (status codes, schemas, auth required, error paths), rules for every trigger on recorded footage (zone_enter, exit, dwell, count_over, object_removed, abandoned_object, loitering, running, fall, crowding, after_hours, custom objects), the rider fix (#5), receipts count == answer count, evidence-level rules (model can't promote), privacy (`scripts/privacy_spotcheck.py` on ≥ 10 served files: 0 faces found — run it, fix any leak), clip encoding (every clip: H.264, yuv420p, even size, faststart, plays — decode the first and middle frame with ffmpeg and assert it is not black: mean luma > 10 unless the scene is truly dark).
3. **Voice tests (real calls, `-m live`):** generate question audio with TTS (`gpt-4o-mini-tts`, one voice per language) for ≥ 12 questions across Hindi, Hinglish, English, Tamil, Telugu, Bengali, Gujarati, Kannada → POST as voice notes (webm/opus and m4a) → assert transcript sense, reply language/script, Confirmed numbers equal SQL, voice reply audio exists and is non-silent (RMS check). Save the matrix to `data/eval/voice_matrix.json`.
4. **Agent battery:** re-run `scripts/eval_battery.py` (27+ questions) and fix wrong answers; add 5 questions about the hackathon clip ("Builders venue").
5. **Latency (#2) — about 30 min of effort, then report:** measure where time goes (transcribe / agent rounds / tools / TTS). Quick wins only: stream text immediately; luna-first routing for counts/when/show-me; run TTS in parallel with card assembly; prompt caching; skip the second agent round when tool results already answer. Report before/after p50/p90 in Insights.
6. **Live fps (#3) — about 30 min of effort, then report:** profile the live edge with all services up; batch/fp16/TensorRT path, skip YOLOE when no custom objects on that camera, pause SigLIP indexing of live frames when the GPU is busy, lower keyframe rate. Report fps.
7. **Proof reel (#1)** and **all clips** play in real Chrome: Playwright with `channel: "chrome"` opens each kind of clip (receipt, proof reel, search hit, journey, alert, live replay) and asserts `currentTime` advances and a canvas-sampled frame is not black.
8. **Telegram (#6):** (a) offline tests: drive the bot's handlers with constructed `Update` objects (text, voice note OGG, photo, `/pair`, `/today`, `/report`, `/cameras`) against the real API — assert replies/media are produced; (b) `scripts/telegram_selftest.py`: if a chat is already paired, send a test alert (snapshot + clip + voice note) and a digest to it and log the Telegram message ids; if not paired, print exact pairing steps. (c) Add to FINAL_STEPS the 60-second phone test the user does (pair, send a voice note, receive an alert) — and ask the user to screen-record it on the phone for the demo film (P4.6).
9. **E2E UI suite (Playwright, real Chrome, 1440×900 and 390×844):** login → today → upload a short clip → live analysis view → ask (text) → receipts → proof reel plays → any-analysis with SQL → heatmap → search words → verify → journey → photo search → teach → rule → replay → activate → simulated live alert arrives → incident PDF downloads → settings pairing code → insights. Each step asserts visible content (no spinners > 15 s, no console errors, no failed network calls). Save screenshots. This suite is re-used in P3.
10. **MCPs (#10):** try once to fix Chrome DevTools MCP (`claude mcp remove chrome-devtools` then `claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --headless`); if it still fails, skip — not needed.
11. **Optional (one honest attempt, after everything else in P1 is done):** "Call Nazar" (W7: OpenAI Realtime, ephemeral key, tools via data channel, Hindi tested). Otherwise leave it out and don't mention it as a feature anywhere.
12. Not in scope (record as not done): snatch dataset download (#8), Docker image build (#11, leave for EC2), Marathi (#9).
✅ **P1 done when:** TEST_PLAN all ✅ or listed; pytest + live tests + E2E suite green; privacy spot-check 0 faces; numbers updated in Insights/README.

---

## P2 — UI/UX redesign + a story the user understands in 30 seconds
You are now a senior product designer. The current UI is a generic dark-navy shadcn dashboard with a blue radial glow — replace that look. **Design from the product itself: CCTV.** Not a template, not glassmorphism, not purple/blue gradients, not emoji, not stock illustrations. Keep every working feature; restyle and reorganise, don't break logic. Use Context7 for current docs of anything you add.

### 2.1 Design language "Night shift"
- **Idea:** a calm, premium security console that borrows real CCTV/DVR details — the on-screen-display (OSD) timestamp in monospace (`CAM 02 · 21 NOV 2026 · 22:14:07`), a red **REC** dot for live, thin crop-mark corners around video frames, a very subtle scanline/grain texture on video only. Editorial typography for words, monospace for data.
- **Type:** display **Fraunces** (variable; large numbers and headlines), UI **Geist Sans**, data/OSD **Geist Mono** (self-host via `next/font`; static export compatible). Big confident numbers, generous whitespace, 14–16 px body (never tiny text).
- **Colour (dark default):** ink `#0B0D0E` background, surfaces `#141719` / `#1B1F22`, hairlines `#262B2E`, text `#ECEAE4` (warm), muted `#9A9C98`; **signal amber `#FFB020`** as the single brand accent (infrared/CCTV feel; buttons, focus, the mic); **REC red `#FF3B30`** only for live/alerts; evidence: Confirmed `#3DDC97` (solid), Probable amber (half), Candidate grey **dashed** outline. **Light mode "paper":** `#F4F1EA` background, `#FFFFFF` surfaces, ink `#111312`, same accents darkened for contrast (WCAG AA). Theme toggle persists; respects `prefers-color-scheme` and `prefers-reduced-motion`.
- **Motion:** framer-motion, purposeful only: numbers count up once, cards settle in, receipts fan out, the OSD clock ticks. No bouncing, no parallax overload.
- **3D (tasteful, one place + login):** a procedurally built **dome/bullet CCTV camera** in react-three-fiber + drei (no downloaded models — build from primitives: housing, lens glass with fresnel/reflection, IR LEDs ring glowing amber) that slowly turns to follow the cursor, with the lens reflecting a blurred frame from the demo footage. Lazy-loaded, ≤ 300 KB extra JS gz, falls back to a static rendered PNG on mobile/low-power/reduced-motion. Used on the landing hero and the login screen only.

### 2.2 Public landing page `/` (before login) — the story in chronological order
Real content only (real blurred frames, real answers captured from this system, measured numbers from `/api/metrics` or a generated `web/public/facts.json` produced by a script — never invented numbers).
1. **Hook:** "India bought the cameras. Nobody watches them." — a 3×3 DVR-style grid of real blurred demo frames with ticking OSD timestamps and REC dots; the 3D camera beside it. One sub-line: "Nazar lets you talk to your CCTV — in your language."
2. **The problem in one breath:** owners scrub hours of DVR footage after something happens; footage is unsearchable; alerts fire on shadows. (Short, 3 lines.)
3. **Watch it work (30 s loop):** an auto-playing muted clip from the app (recorded in P4) or an animated sequence: voice note "Kal raat 10 baje ke baad counter pe kitne log aaye?" → Confirmed count with receipts.
4. **How it works** — scroll-driven 5-step diagram: Camera (any DVR/phone/video) → Edge on your GPU (detection, tracking, faces blurred) → Local visual index (₹0 AI) → Ask · Teach · Prove → Alerts on web + Telegram.
5. **The three pillars** with real screenshots: Search like Google Photos (words/photo/journey) · Teach it anything (voice/photo, checks yesterday first) · Proof, not claims (receipts, proof reel, FIR-ready PDF).
6. **Security pack:** loitering, abandoned bag, object taken, crowding, after-hours, running, fall — "AI-verified before it alerts you".
7. **Numbers (measured, dated):** ₹0 to index · ₹/question · × real-time speed · count accuracy · languages tested.
8. **Privacy:** no face recognition ever; faces blurred everywhere; audit log; footage stays on your machine.
9. **Built with:** OpenAI (models and what each does), local GPU stack, AWS deploy plan — honest ("deploy-ready" unless actually deployed).
10. CTA: **Open the console** → `/login`. Footer: GitHub link, licence, credits for sample footage.

### 2.3 Login and app shell
- **Login:** split screen — the 3D camera + one line on the left; passcode field, "remember this device", rate-limit message, clear errors on the right. Works with Enter, shows caps-lock hint, redirects back to the page the user wanted. Logout and expired token → back to login with a message, never a blank page.
- **First run:** if no cameras → onboarding with 4 large choices (Upload a video · Connect CCTV · Use a phone · Import Excel) + "Load demo footage".
- **Shell:** slim left rail (icons + labels on desktop, bottom tab bar on mobile: Today · Ask · Search · Live · More), top bar with the OSD-style clock, camera picker, theme toggle, sound toggle, live-alert indicator. `⌘K`/`Ctrl K` command bar to ask from anywhere.
- **Ask:** the hero screen. Big composer at the bottom (mic in amber, photo search, text); answers as clean cards; evidence panel on the right (desktop) / bottom sheet (mobile) with the video player (crop marks, OSD timestamp, box overlay), timeline scrubber with an activity heatmap and event ticks, receipts grid, journey strip, "how this was computed" (SQL) collapsible. Voice replies show a small waveform with play/pause; transcripts of voice notes shown under the bubble.
- **Today, Search, Live wall, Cameras (+ add flows, zones editor), Alerts & rules (presets, replay, inbox), Reports (PDF list with previews), Insights (designed cards, charts with Recharts styled to the theme — no raw JSON), Settings (passcode, Telegram pairing with QR to t.me/nazar_hackathon_bot, enrichment mode, retention, language, theme).** Consistent spacing scale, empty/loading/error states everywhere, skeletons not spinners.
- **Accessibility & mobile:** 360–430 px and 1280–1920 px, no horizontal scroll, tap targets ≥ 44 px, keyboard navigable, focus visible, contrast AA, `prefers-reduced-motion` honoured. PWA manifest + original icon (a lens inside an OSD corner frame).
### 2.4 Checks
Playwright screenshots of every page at 390×844 and 1440×900 in **both themes** → look at them yourself and fix anything off (alignment, overflow, contrast, tiny text, broken states). Lighthouse (mobile) performance ≥ 80, accessibility ≥ 95 on landing/login/ask. E2E suite from P1 still green. `npm run lint` + `npm run build` clean.
✅ **P2 done when:** every page is redesigned in both themes and both viewports, you have reviewed the screenshots once and fixed what was off, the landing tells the story in order, and the checks above pass.

---

## P3 — Final full check. Fixes only, no new features.
Run, in order: `check_env.py` · `check_models.py` · `pytest -q` · `pytest -m live -q` · E2E suite (both viewports, both themes) · `privacy_spotcheck.py` · `smoke.ps1` · `eval_counts.py` · `eval_battery.py` (record p50/p90) · `bench_pipeline.py` (short) · live alert test · Telegram offline tests + selftest · `docker compose -f infra/docker-compose.prod.yml config -q` · `caddy validate` (with DOMAIN set) · secret scan. Update README numbers, Insights `facts.json`, `docs/TEST_PLAN.md`. Any failure → fix within the §0 no-loop rules or list it.
✅ **P3 done when:** every command above has run once on the final code and its result is recorded.

---

## P4 — The demo film: with voice, clear story, every feature, real audio
Output: `demo/nazar_film.mp4` (main, target **4:30–5:30**, 1920×1080, H.264 + AAC) and `demo/nazar_2min.mp4` (short cut). Never commit videos (gitignored); keep the scripts and the narration text in git (`video/`).
### 4.1 Story script (write `video/script.md` first, then record to it)
Narration in clear Indian-English, warm and confident, simple words, no jargon without a one-line explanation. Hindi parts are the user's real voice notes (TTS "user" voice) with English subtitles. Chronological chapters (approx. timings at 1×):
1. **Cold open (0:00–0:20):** a creative title sequence (not a gradient slide) — DVR grid of real blurred frames with ticking OSD clocks, REC dots, a slow zoom into one camera, the line "India bought the cameras. Nobody watches them." → the 3D camera turns to face us → "Nazar" wordmark lands with "Talk to your CCTV — in your language."
2. **The problem (0:20–0:40):** shopkeepers/homes/societies; scrubbing hours of footage; motion alerts on shadows; why it matters (theft, safety, lost bags/children, disputes) — on-screen captions with 1–2 sourced facts (e.g. non-IP cameras > 85 % of India's CCTV market — Bonafide Research; cite on screen).
3. **What Nazar is (0:40–0:55):** the three pillars in one line each.
4. **Any camera in a minute (0:55–1:30):** upload the hackathon venue clip → live analysis view with boxes and counts; CCTV builder + test connection; Excel import; phone QR.
5. **Ask by voice — heard (1:30–2:05):** the user's Hindi voice note is **audible**, then Nazar's **spoken Hindi reply is audible**, subtitles in English; Confirmed count from SQL; receipts; proof reel playing.
6. **Any analysis (2:05–2:25):** busiest camera/hour with the SQL shown; heatmap.
7. **Search like Google Photos (2:25–2:55):** words → AI-verified hits; journey across cameras; search by photo (bag); face request politely refused (privacy).
8. **Teach it anything (2:55–3:15):** "Builders venue pe laptop pe nazar rakho" (voice, audible) → open-vocabulary detection → past candidates.
9. **Rules that check yesterday first + live alert (3:15–3:55):** voice rule "Jab bhi koi desk 14 se bag uthaye, mujhe batana" (audible) → "would have fired 3 times" → activate → live view → bag taken → alert lands in the app **with its voice note audible** → **and on Telegram** (P4.6).
10. **Proof: incident report (3:55–4:15):** FIR-ready PDF scrolled: timeline, blurred frames, AI description marked as AI, evidence levels, SHA-256 hashes. Security pack/events.
11. **Cost and truth (4:15–4:35):** ₹0 to index, ₹/question, speed (× real time), count accuracy, languages tested — all measured, dates on screen.
12. **How it's built (4:35–5:00):** animated architecture: camera → edge on the laptop GPU (YOLO + BoT-SORT, pose head-blur, SigLIP 2 index, YOLOE) → Postgres/pgvector → OpenAI (gpt-6-luna for fast answers and visual checks, gpt-6-sol for hard questions, text-embedding-3-small, gpt-4o-transcribe, gpt-4o-mini-tts; Flex tier for background) → web app + Telegram bot. Built in one night with Claude Code using the Playwright and Context7 MCPs for self-testing and live docs. AWS: say exactly what is true at render time — "deploy-ready on AWS: EC2 (CPU), RDS Postgres + pgvector, S3 with 7-day expiry, Amplify" or, if the user has deployed by then, the live URL.
13. **Close (5:00–5:15):** "Every shop in India already bought the camera. Nazar makes it useful." + GitHub link + team name (Shivansh).
### 4.2 How to build it
- **Title/explainer scenes:** **Remotion** project in `video/` (React; scenes: cold open, problem, pillars, architecture, numbers, close) using the same "Night shift" design language, the real blurred frames and `facts.json`. Render to MP4 at 1920×1080, 30 fps. If Remotion fails within 20 min, fall back to HTML/CSS/GSAP pages recorded with Playwright.
- **App recording:** extend `scripts/demo_full.mjs` → `scripts/film_record.mjs`: Playwright, **real Chrome** (`channel: "chrome"`, H.264 playback), viewport **1920×1080 with the app at 125 % zoom** (readable text), cursor highlight, deliberate pacing, chapter markers. Feed voice notes with Chrome's fake mic (`--use-fake-ui-for-media-stream --use-file-for-fake-audio-capture=<wav>`). Log a JSON timeline of every event (question audio start, reply audio URL + start, alert arrival, chapter starts) relative to the video start.
- **Audio — the most important part:** Playwright video has no sound, so build the soundtrack yourself:
  1. **Narration:** generate each chapter's lines with `gpt-4o-mini-tts` (one consistent narrator voice; instructions: "warm, confident Indian-English documentary narrator, unhurried"), save WAVs, measure durations.
  2. **User voice notes:** the exact WAVs fed to the fake mic (a different, natural Hindi voice).
  3. **Nazar's replies:** download the actual reply audio returned by the app (`audio_url`) for each answer and alert.
  4. Mix with ffmpeg: place 2 and 3 at their logged timestamps (`adelay`), narration where it fits (never over the voice notes/replies — duck or shift), loudness-normalise (`loudnorm` to −16 LUFS), optional very quiet synthesised ambient bed (generated with ffmpeg, no copyrighted music).
  5. Burn subtitles (`.ass`) for narration and English translations of Hindi audio; large, readable, bottom-safe area, styled in the design language.
- **Pacing:** narration drives the edit. Speed up waiting/processing segments (1.5–3×, marked "sped up" in a small OSD tag) but **never** speed up voice notes, replies or narration. Target total 4:30–5:30; if longer, speed waits more or trim — don't rush the talking.
- **Telegram (4.6):** if `demo/telegram_phone.mp4` exists (the user's phone screen recording: pairing, a voice note question and its voice reply, an alert with clip), place it in chapter 9 inside a phone frame. If it doesn't exist, show the real bot terminal log + the Telegram message ids from `telegram_selftest.py` and a clean "on your phone via Telegram" slide; and add to FINAL_STEPS how to record and drop in the phone clip, plus `python scripts/film_build.py --telegram demo/telegram_phone.mp4` to rebuild the film in one command.
- **Assemble:** `scripts/film_build.py` stitches Remotion scenes + app recording + soundtrack + subtitles → `demo/nazar_film.mp4`; a second preset makes `demo/nazar_2min.mp4` (cold open, voice ask with audio, search, rule + alert, numbers, close).
- **Self-review (mandatory):** extract a frame every 5 s into a contact sheet and look at it; check text is readable at 1080p, nothing black where video should play, subtitles not covering key UI; run `ffprobe` (has audio stream, duration), measure loudness, and spot-listen by checking RMS around every voice note/reply timestamp (non-silent). Fix and re-render once.
✅ **P4 done when:** both films exist, have an audio stream, every voice note and reply is audible (RMS check), the contact sheet looks right and text is readable — then stop working on the film.

---

## P5 — Final report
Update `FINAL_STEPS.md` (v3): how to start, the judge demo flow (matching the film's order), Telegram pairing + the 60-second phone test, how to rebuild the film with the phone clip, deploy pointer (`infra/DEPLOY.md`; what's ready; nothing created on AWS), submission checklist (repo, `demo/nazar_film.mp4`, `demo/nazar_2min.mp4`, slides from README), known issues table with honest numbers. **Rewrite README.md last, so it reflects the final product** (the user wants it complete):
- **Hero:** title, one-liner, badges, and a short hero **GIF** (≤ 8 MB, `docs/media/hero.gif`, made from the film's best 10–15 s: voice ask → answer with receipts) plus a **"Watch the demo film"** link. Videos are not committed: if the GitHub CLI is authenticated (`gh auth status`), create a release `v1.0-demo` and attach `demo/nazar_film.mp4` and `demo/nazar_2min.mp4`, then link those release URLs; if not, put a clearly marked placeholder link and add "upload the film and paste its link here" to FINAL_STEPS.
- **Fresh screenshots of the redesigned UI** in `docs/screenshots/` (taken after P3 on the final code): landing, login (3D camera), Today, Ask with evidence panel + receipts, proof reel, any-analysis with SQL, heatmap, search + journey, photo search, teach, rule replay, live view with overlay, alert, incident PDF, Insights, Settings/Telegram pairing, add-camera flows (upload live analysis, CCTV builder, Excel import) — desktop **dark and light**, plus 3–4 **mobile** shots side by side. Old v1/v2 screenshots that no longer match are replaced or deleted.
- **Sections (in this order):** the problem · what Nazar does (the three pillars, with screenshots) · the demo film + 2-minute cut · feature tour (one short paragraph + screenshot each, in the film's chronological order) · Telegram bot (with the phone clip/GIF if provided, else screenshots of the bot log) · how it works (Mermaid architecture diagram: camera → edge on GPU → local index → Postgres/pgvector → OpenAI → web + Telegram) · evidence levels table · privacy · **measured results** table (dated: speed × real time, live fps, latency p50/p90, count accuracy, MOT17 tracking, cost ₹0 to index and ₹ per question, languages tested) · where OpenAI is used (model → job → cost share) · AWS (deploy-ready architecture; live URL only if actually deployed) · tech stack · tests (how to run, what they cover, counts) · run it yourself (5 commands) · connect cameras (upload, CCTV/RTSP presets, Excel, phone) · API reference · project structure · honest limitations / known issues · roadmap · built with (Claude Code + Playwright/Context7 MCPs for self-testing) · credits and licences for sample footage and datasets.
- Every image link must resolve (check that each referenced file exists); README renders correctly on GitHub (no broken Mermaid, no huge files: each image ≤ 1 MB, compress PNGs).
Also update CLAUDE.md (design language, test suite, film pipeline). Commit + push. Print the final report and FINAL_STEPS.md, and end — you are finished.

---

## 6. Rules that still apply (from v1/v2)
No face recognition ever; blur at egress; evidence levels only by server code; counts from SQL with receipts; honest measured numbers with dates; no mocks in product; never break `main`; keep RAM in check (8 GB laptop — unload idle models; one edge at a time while recording the film); no AWS resources created; do not use generated video/images as "footage" anywhere (no Higgsfield or similar).

## 7. Final report format (print at the end)
1) What changed in v3 (bullets). 2) Test results table (suite → pass/fail counts). 3) Measured numbers (latency p50/p90, live fps, × real time, count accuracy, cost per question, languages). 4) Film files + durations + "has audio: yes". 5) Known issues. 6) What the user does next (Telegram phone test/recording, deploy, submit).

## 8. Git rules (unchanged)
Remote `https://github.com/Shivansh0911/Nazar.git`, branch `main`; the user's git identity only; **no AI attribution anywhere** (no Co-Authored-By, no "Generated with"; keep `.claude/settings.json` `{"includeCoAuthoredBy": false}`); Conventional Commits in a human tone (`feat(ui): night-shift design system and story landing`, `test(e2e): full flow suite in real Chrome`, `fix(count): separate motorcycle riders from people on foot`, `feat(film): narrated demo with real voice notes and replies`); commit coherent working units; push after each phase; never commit `.env`, keys, data, videos, model weights; secret-scan before the last push.
