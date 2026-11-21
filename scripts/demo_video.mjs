// Records a narrated (on-screen captions) walkthrough of the running app.
//   cd web; node ../scripts/demo_video.mjs [--wav path\to\question.wav] [--out ..\demo]
// Needs: API :8000 (with OPENAI_API_KEY), worker, web :3000, demo data. Writes demo/nazar_demo.webm (+ mp4 via ffmpeg).
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = opt("--base", "http://localhost:3000");
const API = opt("--api", "http://localhost:8000");
const OUT = path.resolve(opt("--out", path.resolve(here, "..", "demo")));
const WAV = opt("--wav", "");
fs.mkdirSync(OUT, { recursive: true });

const launchArgs = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"];
if (WAV) launchArgs.push(`--use-file-for-fake-audio-capture=${WAV}`);
// --channel chrome (or msedge): Playwright's bundled Chromium cannot play H.264 clips; real Chrome/Edge can
const CHANNEL = opt("--channel", "");
const browser = await chromium.launch({ args: launchArgs, ...(CHANNEL ? { channel: CHANNEL } : {}) });
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: OUT, size: { width: 1280, height: 800 } },
  permissions: ["microphone"],
});
const page = await ctx.newPage();
const t0 = Date.now();
const log = (m) => console.log(`[${((Date.now() - t0) / 1000).toFixed(0).padStart(3)}s] ${m}`);

async function caption(text) {
  await page.evaluate((t) => {
    let d = document.getElementById("demo-cap");
    if (!d) {
      d = document.createElement("div");
      d.id = "demo-cap";
      Object.assign(d.style, {
        position: "fixed", left: "50%", transform: "translateX(-50%)", top: "96px", zIndex: "99999",
        background: "rgba(15,23,42,.92)", color: "#fff", padding: "10px 18px", borderRadius: "14px",
        font: "600 16px Inter, system-ui, sans-serif", maxWidth: "86%", textAlign: "center",
        boxShadow: "0 8px 28px rgba(0,0,0,.35)", pointerEvents: "none", lineHeight: "1.35",
      });
      document.body.appendChild(d);
    }
    d.textContent = t;
  }, text);
  log(text);
}
const pause = (ms) => page.waitForTimeout(ms);

async function ask(text, waitMs = 2500) {
  await page.fill('input[placeholder^="Ask"]', text);
  await pause(700);
  await page.keyboard.press("Enter");
  await page.waitForSelector("text=Watching the footage", { timeout: 10000 }).catch(() => undefined);
  await page.waitForSelector("text=Watching the footage", { state: "detached", timeout: 120000 }).catch(() => undefined);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await pause(waitMs);
}

// 1. login
await page.goto(`${BASE}/login/`);
await caption("Nazar — ask your CCTV anything, in Hindi, English or Hinglish");
await pause(2500);
await page.fill('input[type="password"]', "nazar2026");
await page.click('button:has-text("Continue")');
await page.waitForURL(`${BASE}/`);
const token = await page.evaluate(() => localStorage.getItem("nazar_token"));
const H = { "X-Nazar-Token": token, "Content-Type": "application/json" };

// 2. cameras
await page.goto(`${BASE}/cameras/`);
await pause(2500);
await caption("6 cameras. Last night's 'CCTV' is downloaded footage, watched by YOLO + ByteTrack on the laptop GPU. Faces are blurred before anything is saved.");
await pause(6000);
await page.goto(`${BASE}/camera/?id=office-desk`);
await pause(3000);
await caption("Office desk camera: owner-drawn zones (Desk 14), people per hour, tracks seen. Counts come from SQL, never from the AI.");
await pause(6000);

// 3. teach a rule (replay first), activate, then play the bag clip as a LIVE camera
await page.goto(`${BASE}/`);
await pause(1500);
await page.selectOption('select[aria-label="Camera"]', { label: "Office desk" }).catch(() => undefined);
await caption("Teach it: 'Jab bhi koi desk 14 se bag uthaye, mujhe batana' → compiled into a rule and REPLAYED on last night first");
await ask("Jab bhi koi desk 14 se bag uthaye, mujhe batana", 4000);
await caption("Replay: it would have fired on last night's footage (thumbnail = the person who took the bag). Now: Activate.");
await pause(4000);
const act = page.locator('button:has-text("Activate")').last();
if (await act.count()) await act.click({ timeout: 10000 }).catch(() => undefined);
await pause(2500);
const live = await fetch(`${API}/api/cameras/office-desk/start`, { method: "POST", headers: H }).then((r) => r.json());
log(`live edge: ${live.status}`);
await caption("Rule is active. We now play the bag clip as a LIVE camera (stamped 'now'). The pickup happens ~2 min in — meanwhile, let's ask.");
await pause(5000);

// 4. Hinglish count
await page.selectOption('select[aria-label="Camera"]', { label: "Shop counter" }).catch(() => undefined);
await caption("Ask (Hinglish): 'Kal raat 10 baje ke baad shop counter pe kitne log aaye?'");
await ask("Kal raat 10 baje ke baad shop counter pe kitne log aaye?", 6000);
await caption("Spoken reply + a Confirmed count from SQL with the hourly chart");
await pause(5000);

// 5. Hindi voice note (the microphone is fed a recorded question)
if (WAV) {
  await page.selectOption('select[aria-label="Camera"]', { label: "All cameras" }).catch(() => undefined);
  await caption("Voice note in Hindi: tap the lime mic, speak, tap to send");
  await page.click('button[aria-label="Record a voice note"]');
  await pause(5500);
  await page.click('button[aria-label="Stop recording"]');
  await page.waitForSelector("text=Watching the footage", { state: "detached", timeout: 120000 }).catch(() => undefined);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await caption("Transcribed, answered in Hindi (Devanagari) with a voice reply");
  await pause(7000);
}

// 6. description search + clip player + find again
await page.selectOption('select[aria-label="Camera"]', { label: "All cameras" }).catch(() => undefined);
await caption("Describe someone: 'Show me people carrying a bag on the market street this morning'");
await ask("Show me people carrying a bag on the market street this morning", 5000);
await caption("Clips with honest evidence levels: Probable = description AND attributes agree; dashed Candidate = similarity only");
await pause(6000);
const clip = page.locator("main button:has(img)").last();
if (await clip.count()) {
  await clip.click({ timeout: 10000 }).catch(() => undefined);
  await pause(5000);
  await caption("Clip cut from the stored segments; the tracked box is drawn live on a canvas. Faces stay blurred.");
  await pause(6000);
  const fa = page.locator('button:has-text("Find again")');
  if (await fa.count()) {
    await fa.scrollIntoViewIfNeeded().catch(() => undefined);
    await fa.click({ force: true, timeout: 10000 }).catch(() => undefined);
    await pause(5000);
    await caption("Find again: same-looking people within ±24 h from a 76-number appearance fingerprint — no face recognition");
    await pause(6000);
  }
  await page.keyboard.press("Escape");
  await pause(1000);
}

// 7. wait for the live alert
await caption("Waiting for the live event on the Office desk camera…");
const got = await page.waitForSelector("text=Alert ·", { timeout: 300000 }).then(() => true).catch(() => false);
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
if (got) {
  await caption("LIVE ALERT: the bag was taken from Desk 14 — snapshot + Hinglish voice note, seconds after it happened");
  await pause(9000);
} else {
  await caption("(no live alert within 5 minutes)");
  await pause(3000);
}
await fetch(`${API}/api/cameras/office-desk/stop`, { method: "POST", headers: H }).catch(() => undefined);

// 8. metrics
await page.goto(`${BASE}/metrics/`);
await pause(3000);
await caption("Cost: OpenAI only sees 1–3 face-blurred crops per tracked person + your questions. Measured from every logged call.");
await pause(9000);
await caption("Nazar — trajectories are the truth, levels are honest, rules replay before they go live.");
await pause(3500);

const v = page.video();
await ctx.close();
await browser.close();
const src = await v.path();
const dst = path.join(OUT, "nazar_demo.webm");
fs.renameSync(src, dst);
console.log("video:", dst, "alert:", got);
