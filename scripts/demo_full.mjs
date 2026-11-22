// Complete product demo in chronological order (every feature and USP), recorded in real Chrome with captions.
//   cd web; node ../scripts/demo_full.mjs --wav ..\demo\q_hi.wav --photo ..\demo\bag_photo.jpg
// Needs API :8000, worker, vision service, web :3000, demo data. Writes demo/nazar_full.webm + demo/nazar_full_fast.json;
// then: python scripts/make_demo_mp4.py --src demo/nazar_full.webm --fast demo/nazar_full_fast.json --out demo/nazar_full.mp4
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = path.resolve(here, "..", "demo");
const WAV = path.resolve(opt("--wav", path.join(OUT, "q_hi.wav")));
const PHOTO = path.resolve(opt("--photo", path.join(OUT, "bag_photo.jpg")));
const UPLOAD = path.resolve(here, "..", "samples", "hackathon.mp4");

const browser = await chromium.launch({
  channel: opt("--channel", "chrome"),
  args: ["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${WAV}`],
});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["microphone"],
  recordVideo: { dir: OUT, size: { width: 1440, height: 900 } } });
const page = await ctx.newPage();
const t0 = Date.now();
const fast = [];
const now = () => (Date.now() - t0) / 1000;
const log = (m) => console.log(`[${now().toFixed(0).padStart(4)}s] ${m}`);
const pause = (ms) => page.waitForTimeout(ms);
const safe = (p) => p.catch((e) => log(`  (skipped: ${String(e).split("\n")[0].slice(0, 90)})`));

async function caption(text, chapter) {
  await page.evaluate(([t, c]) => {
    let d = document.getElementById("demo-cap");
    if (!d) {
      d = document.createElement("div");
      d.id = "demo-cap";
      Object.assign(d.style, { position: "fixed", left: "50%", transform: "translateX(-50%)", bottom: "26px", zIndex: "99999",
        background: "rgba(11,13,14,.94)", color: "#fff", padding: "12px 22px", borderRadius: "16px", border: "1px solid #FFB020",
        font: "600 22px Geist, Inter, system-ui, sans-serif", maxWidth: "78%", textAlign: "center", pointerEvents: "none",
        boxShadow: "0 10px 30px rgba(0,0,0,.45)", lineHeight: "1.4" });
      document.body.appendChild(d);
    }
    d.innerHTML = (c ? `<div style="font:700 13px Inter;letter-spacing:.16em;color:#FFB020;margin-bottom:6px;font-family:Geist Mono,monospace">${c}</div>` : "") + t;
  }, [text, chapter || ""]).catch(() => undefined);
  log(`${chapter ? chapter + " | " : ""}${text}`);
}
async function waitFast(fn, ms = 0) {
  const a = now();
  await fn().catch(() => undefined);
  if (ms) await pause(ms);
  fast.push([a, now()]);
}
const answered = () => page.waitForFunction(() => !document.body.innerText.includes("Thinking") && !document.querySelector("main .animate-spin, section .animate-spin"), null, { timeout: 180000 });
async function ask(q, wait = 4000) {
  await page.fill('input[placeholder^="Ask"]', q);
  await pause(700);
  await page.keyboard.press("Enter");
  await pause(1500);
  await waitFast(answered);
  await pause(wait);
}
async function titleCard(lines, ms = 6000) {
  await page.evaluate((ls) => {
    const d = document.createElement("div");
    d.id = "demo-title";
    Object.assign(d.style, { position: "fixed", inset: "0", zIndex: "100000", background: "radial-gradient(circle at 50% 35%, #2A1E08 0%, #0B0D0E 62%)",
      color: "#fff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "14px",
      font: "500 22px Inter, system-ui, sans-serif", textAlign: "center", padding: "40px" });
    d.innerHTML = ls.map((l, i) => i === 0 ? `<div style="font:500 78px Fraunces,Georgia,serif;letter-spacing:-.02em">${l}</div>`
      : `<div style="opacity:.9">${l}</div>`).join("");
    document.body.appendChild(d);
  }, lines);
  await pause(ms);
  await page.evaluate(() => document.getElementById("demo-title")?.remove());
}

const tok = (await (await fetch(`${API}/api/auth`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ passcode: "nazar2026" }) })).json()).token;
const H = { "X-Nazar-Token": tok, "Content-Type": "application/json" };

// 0. title + login ------------------------------------------------------------------------------------------------
await page.goto(`${BASE}/login/`);
await titleCard(["Nazar", "Ask your CCTV anything — in Hindi, English or Hinglish", "1 · Search footage like Google Photos — by words, by photo",
  "2 · Teach it anything, no training — it checks yesterday first, then watches live", "3 · Proof, not claims — every number has receipts, every incident a PDF",
  "<span style='color:#FFB020'>No face recognition, ever · indexing costs ₹0 in AI</span>"], 9000);
await caption("A single passcode, rate-limited. Faces are blurred in everything Nazar shows or sends.", "LOGIN");
await pause(2500);
await page.fill('input[type="password"]', "nazar2026");
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/`);

// 1. Today -------------------------------------------------------------------------------------------------------
await pause(3000);
await caption("Today: every camera, the overnight digest (text + voice note), alerts and the security pack.", "1 · TODAY");
await pause(7000);

// 2. Onboarding -------------------------------------------------------------------------------------------------
await page.goto(`${BASE}/cameras/new/`);
await pause(1500);
await caption("Any video works: upload in 8 MB resumable parts, no re-encoding. Here: a real clip from this venue.", "2 · ADD ANY CAMERA");
await page.setInputFiles('input[type="file"]', UPLOAD);
await pause(1200);
await safe(page.fill('input[value^="hackathon"]', "Venue (uploaded)"));
await page.click('button:has-text("Upload & analyse")');
await waitFast(() => page.waitForSelector("text=People so far", { timeout: 180000 }));
await caption("Live analysis view: YOLO + tracker on the laptop GPU at ~15× real time — boxes and counts as they are found.", "2 · ADD ANY CAMERA");
await pause(9000);
await waitFast(() => page.waitForSelector("text=Ask about it", { timeout: 300000 }));
await pause(1500);
await page.click('button:has-text("CCTV / DVR")');
await pause(1000);
await caption("CCTV / DVR builder: Hikvision, Dahua, CP Plus presets. Test connection explains exactly what is wrong.", "2 · ADD ANY CAMERA");
await page.fill('input[placeholder="Counter"]', "Gate");
await page.fill('input[placeholder="192.168.1.64"]', "10.255.255.1");
await page.click('button:has-text("Test connection")');
await waitFast(() => page.waitForSelector("text=/unreachable|auth failed|wrong path|no answer/", { timeout: 30000 }));
await pause(4000);
await page.click('button:has-text("Excel import")');
await caption("Many cameras? Fill the Excel/CSV template; every row is probed (4 at a time) before anything is added.", "2 · ADD ANY CAMERA");
await pause(4500);
await page.click('button:has-text("Phone")');
await caption("Or a phone: scan the QR into Larix Broadcaster and it becomes a live camera.", "2 · ADD ANY CAMERA");
await pause(4500);

// 3. Camera detail: zones, count lines, teach ----------------------------------------------------------------------
await page.goto(`${BASE}/camera/?id=office-desk`);
await pause(3000);
await caption("Each camera: owner-drawn zones and count lines (with an IN arrow), activity chart, teach an object.", "3 · ZONES & COUNT LINES");
await pause(7000);

// 4. Proof, not claims: counts with receipts ------------------------------------------------------------------------
await page.goto(`${BASE}/ask/`);
await pause(1500);
await safe(page.click('button:has-text("Clear")', { timeout: 3000 }));
await caption("Ask in Hinglish. Answers stream in; the number comes from SQL — never from the AI.", "4 · PROOF, NOT CLAIMS");
await ask("Builders venue pe kitne log dikhe?", 3000);
await caption("Confirmed count + receipts: every counted person is listed and playable, with a per-minute chart.", "4 · PROOF, NOT CLAIMS");
await pause(6000);
await safe(page.locator("aside label:has-text('Verify') input").check({ timeout: 5000 }));
await safe(page.locator("aside button:has-text('ok?')").first().click({ timeout: 5000 }));
await caption("A human can mark a receipt wrong: “N by AI · N−1 after your review” — stored for evaluation.", "4 · PROOF, NOT CLAIMS");
await pause(4500);
await safe(page.click('aside button:has-text("Play proof reel")', { timeout: 5000 }));
await caption("Proof reel: every counted moment, 2.5 s each, captioned — faces blurred.", "4 · PROOF, NOT CLAIMS");
await waitFast(() => page.waitForSelector("video", { timeout: 120000 }));
await pause(8000);
await page.keyboard.press("Escape");

// 5. Any analysis --------------------------------------------------------------------------------------------------
await caption("Any analysis, safely: the AI writes ONE read-only SQL query over whitelisted views — and shows it.", "5 · ANY ANALYSIS");
await ask("Which camera was busiest and at what hour?", 2500);
await safe(page.click("aside >> text=How this was computed", { timeout: 5000 }));
await pause(5000);
await caption("Where do people spend time? A heatmap from the tracked paths.", "5 · ANY ANALYSIS");
await ask("Lobby mein log kahan sabse zyada ruke? Heatmap dikhao", 6000);

// 6. Hindi voice note + privacy refusal ------------------------------------------------------------------------------
await caption("Tap the lime mic and speak — here a Hindi voice note. Reply in Devanagari, with a spoken answer.", "6 · VOICE, ANY LANGUAGE");
await page.click('button[aria-label="Record a voice note"]');
await pause(6300);
await page.click('button[aria-label="Stop recording"]');
await pause(1500);
await waitFast(answered);
await pause(6000);
await caption("Asked to find a face, Nazar politely refuses and offers clothing/appearance search instead.", "6 · PRIVACY");
await ask("Find this person's face in all cameras", 5000);

// 7. Search like Google Photos ------------------------------------------------------------------------------------
await page.goto(`${BASE}/search/`);
await pause(1500);
await caption("Search by words across every camera — a local SigLIP 2 visual index, ₹0 in AI.", "7 · SEARCH LIKE GOOGLE PHOTOS");
await page.fill('input[aria-label="Search text"]', "person carrying a bag");
await page.keyboard.press("Enter");
await waitFast(() => page.waitForSelector("text=similar moments", { timeout: 60000 }));
await pause(3000);
await safe(page.click('button:has-text("Verify top 8 with AI")', { timeout: 5000 }));
await waitFast(() => page.waitForSelector("text=verified by AI", { timeout: 120000 }));
await caption("AI checks only the top hits: Probable = similar look AND AI agrees. Candidates stay dashed.", "7 · SEARCH LIKE GOOGLE PHOTOS");
await pause(6000);
const jb = page.locator('button:has-text("Journey")').first();
if (await jb.count()) {
  await jb.click();
  await waitFast(() => page.waitForSelector("text=no face recognition", { timeout: 30000 }));
  await caption("Journey: the same look at other times and cameras — clothes and objects only, never faces.", "7 · SEARCH LIKE GOOGLE PHOTOS");
  await pause(6000);
}
await page.click('button:has-text("Photo")');
await pause(800);
await safe(page.setInputFiles('input[type="file"][accept="image/*"]', PHOTO, { timeout: 10000 }));
await pause(1000);
await page.fill('input[placeholder^="Purpose"]', "lost bag at the venue");
await caption("Search by photo: faces in the photo are blurred first; every photo search is audited with its purpose.", "7 · SEARCH LIKE GOOGLE PHOTOS");
await page.click('button:has-text("Find every sighting")');
await waitFast(() => page.waitForSelector("text=similar moments", { timeout: 60000 }));
await pause(6000);

// 8. Teach it anything ------------------------------------------------------------------------------------------
await page.goto(`${BASE}/ask/`);
await pause(1500);
await caption("Teach by voice or text — an object the detector never learned. Open-vocabulary YOLOE, no training.", "8 · TEACH IT ANYTHING");
await ask("Builders venue pe kursi (chair) pe nazar rakho", 5000);
await page.goto(`${BASE}/camera/?id=builders-venue`);
await pause(2500);
await safe(page.fill('input[aria-label="Object to watch for"]', "green bag"));
await safe(page.setInputFiles('input[type="file"][accept="image/*"]', PHOTO, { timeout: 10000 }));
await caption("…or teach from a photo of your own bag / scooter: matched by appearance in every new frame.", "8 · TEACH IT ANYTHING");
await waitFast(() => page.waitForSelector("text=/Now watching .* from your photo/", { timeout: 120000 }));
await pause(5000);

// 9. Rules: replay yesterday, then live ----------------------------------------------------------------------------
await page.goto(`${BASE}/ask/`);
await pause(1500);
await page.selectOption('select[aria-label="Camera"] >> nth=1', { label: "Office desk" }).catch(() => undefined);
await caption("Teach a rule in your words. It is replayed on yesterday's footage FIRST — before you trust it.", "9 · RULES CHECK YESTERDAY FIRST");
await ask("Jab bhi koi desk 14 se bag uthaye, mujhe batana", 4000);
await safe(page.click('aside button:has-text("Activate")', { timeout: 8000 }));
await pause(3000);
const lastAlert = async () => ((await (await fetch(`${API}/api/alerts?limit=1`, { headers: H })).json())[0] || { id: 0 }).id;
const alert0 = await lastAlert();
await fetch(`${API}/api/cameras/office-desk/start`, { method: "POST", headers: H });
await page.goto(`${BASE}/live/`);
await caption("Live wall: low-latency WebRTC view, faces blurred, tracker boxes and live counts burned in.", "10 · LIVE");
await waitFast(() => page.waitForSelector("text=/WebRTC/", { timeout: 120000 }));
await safe(page.click('button[aria-label="Enlarge"]', { timeout: 5000 }));
await pause(8000);
await caption("The bag clip now plays as a live camera. Waiting for someone to take the bag (sped up)…", "10 · LIVE");
await waitFast(async () => {
  for (let i = 0; i < 180 && (await lastAlert()) <= alert0; i++) await pause(3000);
}, 4000);
await page.goto(`${BASE}/alerts/`);
await pause(1500);
await caption("LIVE ALERT seconds after it happened — snapshot, clip + Hinglish voice note. Also pushed to Telegram.", "10 · LIVE ALERT");
await pause(6500);
await fetch(`${API}/api/cameras/office-desk/stop`, { method: "POST", headers: H });

// 11. Incident PDF from that alert + security analytics --------------------------------------------------------------
await caption("One tap: an FIR-ready incident report for this alert.", "11 · INCIDENT REPORT");
await page.evaluate(() => { window.open = (u) => { window.location.href = String(u).replace(/(\d+)_[a-f0-9]{6}\.pdf/, "$1_preview.png"); return null; }; });
await safe(page.locator('button:has-text("Incident report (PDF)")').first().click({ timeout: 5000 }));
await waitFast(() => page.waitForURL(/_preview\.png/, { timeout: 300000 }));
await page.evaluate(() => {
  const i = document.querySelector("img");
  document.body.style.background = "#0B0D0E";
  if (i) Object.assign(i.style, { width: "62%", height: "auto", margin: "0 auto", display: "block", cursor: "default" });
}).catch(() => undefined);
await caption("FIR-ready PDF: timeline, blurred frames, AI description (marked), evidence levels, SHA-256 hashes.", "11 · INCIDENT REPORT");
await pause(3500);
for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, 420); await pause(1700); }
await page.goto(`${BASE}/alerts/`);
await pause(2000);
await page.click('button:has-text("Security events")');
await pause(2000);
await caption("Security analytics out of the box: object taken, abandoned bag, loitering, running, fall, crowding, after-hours, snatch.", "11 · SECURITY");
await pause(6000);
await safe(page.click('button:has-text("Object taken")', { timeout: 4000 }));
await caption("Heuristics are Candidates until an AI check of blurred frames agrees → Probable. Every incident gets a PDF.", "11 · SECURITY");
await pause(5000);
await page.goto(`${BASE}/reports/`);
await pause(4000);

// 12. Telegram + settings -------------------------------------------------------------------------------------------
await page.goto(`${BASE}/settings/`);
await pause(1500);
await safe(page.click('button:has-text("Get pairing code")', { timeout: 5000 }));
await caption("Telegram: pair with a 6-digit code. Ask by voice note, search by photo, get alerts with clip + voice.", "12 · TELEGRAM");
await pause(7000);

// 13. Insights ----------------------------------------------------------------------------------------------------
await page.goto(`${BASE}/metrics/`);
await pause(2500);
await caption("Cost truth: indexing ₹0 in AI; you pay per question (measured). Speed, MOT17 tracking and count accuracy — all measured.", "13 · INSIGHTS");
await pause(10000);
await page.evaluate(() => window.scrollTo(0, 700));
await pause(4000);
await titleCard(["Nazar", "Counts with receipts · search by words or photo · rules that check yesterday first", "Live alerts on web + Telegram · FIR-ready reports",
  "<span style='color:#FFB020'>No face recognition, ever</span>"], 6000);

const v = page.video();
await ctx.close();
await browser.close();
const dst = path.join(OUT, "nazar_full.webm");
fs.renameSync(await v.path(), dst);
fs.writeFileSync(path.join(OUT, "nazar_full_fast.json"), JSON.stringify(fast));
console.log("video:", dst, "fast intervals:", fast.length);
