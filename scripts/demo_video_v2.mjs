// v2 judge run-through, recorded in real Chrome with on-screen captions (acceptance G12).
//   cd web; node ../scripts/demo_video_v2.mjs [--photo path\to\bag.jpg] [--channel chrome]
// Needs: API :8000, worker, vision service, web :3000, demo data. Writes demo/nazar_v2.webm and demo/nazar_v2_fast.json
// (intervals to speed up while waiting); scripts/make_demo_mp4.py turns them into demo/nazar_v2.mp4.
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
const PHOTO = opt("--photo", "");
const UPLOAD = opt("--upload", path.resolve(here, "..", "samples", "hackathon.mp4"));
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: opt("--channel", "chrome"), args: ["--autoplay-policy=no-user-gesture-required"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: OUT, size: { width: 1440, height: 900 } } });
const page = await ctx.newPage();
const t0 = Date.now();
const fast = [];
const now = () => (Date.now() - t0) / 1000;
const log = (m) => console.log(`[${now().toFixed(0).padStart(3)}s] ${m}`);
const pause = (ms) => page.waitForTimeout(ms);
async function caption(text) {
  await page.evaluate((t) => {
    let d = document.getElementById("demo-cap");
    if (!d) {
      d = document.createElement("div");
      d.id = "demo-cap";
      Object.assign(d.style, { position: "fixed", left: "50%", transform: "translateX(-50%)", bottom: "28px", zIndex: "99999",
        background: "rgba(10,15,31,.94)", color: "#fff", padding: "12px 20px", borderRadius: "16px", border: "1px solid #2F6BFF",
        font: "600 17px Inter, system-ui, sans-serif", maxWidth: "80%", textAlign: "center", pointerEvents: "none",
        boxShadow: "0 10px 30px rgba(0,0,0,.45)", lineHeight: "1.4" });
      document.body.appendChild(d);
    }
    d.textContent = t;
  }, text).catch(() => undefined);
  log(text);
}
async function waitFast(fn, ms) { // waiting is recorded but sped up 8x in the final video
  const a = now();
  await fn().catch(() => undefined);
  if (ms) await pause(ms);
  fast.push([a, now()]);
}
async function ask(q, wait = 4000) {
  await page.fill('input[placeholder^="Ask"]', q);
  await pause(600);
  await page.keyboard.press("Enter");
  await waitFast(() => page.waitForSelector("text=/ s · ₹/", { timeout: 150000 }));
  await pause(wait);
}

// 1. login + Today
await page.goto(`${BASE}/login/`);
await caption("Nazar — a security analyst you can talk to, in your own language");
await pause(2500);
await page.fill('input[type="password"]', "nazar2026");
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/`);
const token = await page.evaluate(() => localStorage.getItem("nazar_token"));
const H = { "X-Nazar-Token": token, "Content-Type": "application/json" };
await pause(2500);
await caption("Today: every camera, the overnight digest and alerts. 8 cameras incl. a real clip from the Builders venue.");
await pause(6000);

// 2. upload any video -> live analysis view
await page.goto(`${BASE}/cameras/new/`);
await pause(1500);
await caption("Any video works. Upload is resumable (8 MB parts); the file is NOT re-encoded.");
await page.setInputFiles('input[type="file"]', UPLOAD);
await pause(1200);
await page.fill('input[value^="hackathon"]', "Venue (uploaded)").catch(() => undefined);
await page.click('button:has-text("Upload & analyse")');
await waitFast(() => page.waitForSelector("text=People so far", { timeout: 180000 }));
await caption("Live analysis: YOLO + tracker on the laptop GPU, ~15x real time. Faces blurred. Ask from the first minute.");
await pause(9000);
await waitFast(async () => { await page.waitForSelector("text=Ask about it", { timeout: 240000 }); }, 0);
await pause(2000);

// 3. count with receipts + proof reel
await page.goto(`${BASE}/ask/`);
await pause(1500);
await page.click('button:has-text("Clear")').catch(() => undefined);
await caption("Ask in Hinglish: how many people were seen at the venue?");
await ask("Builders venue pe kitne log dikhe?", 3000);
await caption("The number comes from SQL (Confirmed) and every counted person is a receipt you can play.");
await pause(5000);
await page.click('button:has-text("Play proof reel")').catch(() => undefined);
await caption("Proof reel: every counted moment, 2.5 s each, faces blurred.");
await waitFast(() => page.waitForSelector("video", { timeout: 120000 }), 0);
await pause(9000);
await page.keyboard.press("Escape");
await pause(1000);

// 4. any analysis
await caption("Any analysis, safely: the AI writes one read-only SQL query over whitelisted views - you can see it.");
await ask("Which camera was busiest and at what hour?", 4000);
await page.click("text=How this was computed").catch(() => undefined);
await pause(5000);

// 5. search by words, then photo + journey
await page.goto(`${BASE}/search/`);
await pause(1500);
await caption("Search like Google Photos: words or a photo. Local visual index (Rs 0); AI only checks the top hits.");
await page.fill('input[aria-label="Search text"]', "person carrying a bag");
await page.keyboard.press("Enter");
await waitFast(() => page.waitForSelector("text=similar moments", { timeout: 60000 }), 1500);
await page.click('button:has-text("Verify top 8 with AI")').catch(() => undefined);
await waitFast(() => page.waitForSelector("text=verified by AI", { timeout: 90000 }), 1000);
await caption("Probable = similar look AND an AI check of the blurred image agree. Candidates stay dashed.");
await pause(6000);
const journeyBtn = page.locator('button:has-text("Journey")').first();
if (await journeyBtn.count()) {
  await journeyBtn.click();
  await waitFast(() => page.waitForSelector("text=no face recognition", { timeout: 30000 }), 0);
  await caption("Journey: the same look at other times and cameras - clothes and objects only, never faces.");
  await pause(6000);
}
if (PHOTO) {
  await page.click('button:has-text("Photo")');
  await pause(800);
  await page.setInputFiles('input[type="file"][accept="image/*"]', PHOTO);
  await pause(1200);
  await page.fill('input[placeholder^="Purpose"]', "lost bag, demo");
  await caption("Search by photo: faces in the photo are blurred first; each search is audited with its purpose.");
  await page.click('button:has-text("Find every sighting")');
  await waitFast(() => page.waitForSelector("text=similar moments", { timeout: 60000 }), 4000);
}

// 6. teach an object, replay first
await page.goto(`${BASE}/ask/`);
await pause(1500);
await caption("Teach it anything, no training: \"laptop pe nazar rakho\" - open-vocabulary detection (YOLOE).");
await ask("Builders venue pe laptop pe nazar rakho", 5000);
await caption("It checks the stored frames first (replay), then watches live.");
await pause(5000);

// 7. live alert: bag rule on the office desk, the bag clip plays as a LIVE camera
await caption("Rules check yesterday first, then watch live. The bag clip now plays as a live camera...");
const rule = await fetch(`${API}/api/rules/compile`, { method: "POST", headers: H, body: JSON.stringify({ text: "Jab bhi koi desk 14 se bag uthaye, mujhe batana", camera_id: "office-desk" }) }).then((r) => r.json());
await fetch(`${API}/api/rules/${rule.rule_id}/activate`, { method: "POST", headers: H });
await fetch(`${API}/api/cameras/office-desk/start`, { method: "POST", headers: H });
await page.goto(`${BASE}/live/`);
await pause(6000);
await caption("Live wall: face-blurred view with the tracker's boxes. Waiting for someone to pick up the bag (sped up)...");
await page.goto(`${BASE}/ask/`);
await waitFast(() => page.waitForSelector("text=Alert ·", { timeout: 300000 }), 0);
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await caption("LIVE ALERT seconds after it happened: snapshot + Hinglish voice note. Also pushed to Telegram.");
await pause(9000);
await fetch(`${API}/api/cameras/office-desk/stop`, { method: "POST", headers: H });
await fetch(`${API}/api/rules/${rule.rule_id}/deactivate`, { method: "POST", headers: H });

// 8. incident report
await page.goto(`${BASE}/alerts/`);
await pause(2000);
await caption("One tap: a police-ready incident PDF - timeline, blurred frames, evidence levels, SHA-256 hashes.");
const [pdf] = await Promise.all([
  ctx.waitForEvent("page", { timeout: 180000 }).catch(() => null),
  page.click('button:has-text("Incident report (PDF)")').catch(() => undefined),
]);
const fa = now();
if (pdf) {
  await pdf.waitForLoadState().catch(() => undefined);
  fast.push([fa, now()]);
  await pdf.bringToFront();
  await pause(8000);
  await pdf.close();
}

// 9. insights
await page.bringToFront();
await page.goto(`${BASE}/metrics/`);
await pause(2500);
await caption("Cost truth: indexing costs Rs 0 in AI. You pay per question (measured) - every number from logged calls.");
await pause(9000);
await caption("Nazar - counts with receipts, search by words or photo, rules that check yesterday first. No face recognition.");
await pause(4000);

const v = page.video();
await ctx.close();
await browser.close();
const dst = path.join(OUT, "nazar_v2.webm");
fs.renameSync(await v.path(), dst);
fs.writeFileSync(path.join(OUT, "nazar_v2_fast.json"), JSON.stringify(fast));
console.log("video:", dst, "fast intervals:", fast.length);
