// Records the "proof" part of the film on its own (incident PDF preview, security events, Telegram pairing) so it can
// be spliced into the main film when the live run's PDF took too long.   cd web; node ../scripts/film_patch.mjs
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const BASE = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = path.resolve(here, "..", "demo");
const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: OUT, size: { width: 1440, height: 900 } } });
const page = await ctx.newPage();
const t0 = Date.now();
const lines = [];
const pause = (ms) => page.waitForTimeout(ms);
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
    d.innerHTML = `<div style="font:700 13px Inter;letter-spacing:.16em;color:#FFB020;margin-bottom:6px;font-family:Geist Mono,monospace">${c}</div>` + t;
  }, [text, chapter]).catch(() => undefined);
  lines.push(`[${((Date.now() - t0) / 1000).toFixed(0).padStart(4)}s] ${chapter} | ${text}`);
}
const tok = (await (await fetch(`${API}/api/auth`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ passcode: "nazar2026" }) })).json()).token;
const rep = (await (await fetch(`${API}/api/reports`, { headers: { "X-Nazar-Token": tok } })).json())[0];

await page.goto(`${BASE}/login/`);
await page.fill('input[type="password"]', "nazar2026");
await page.keyboard.press("Enter");
await page.waitForURL((u) => !u.pathname.startsWith("/login"));
await page.goto(rep.preview_url);
await page.evaluate(() => {
  const i = document.querySelector("img");
  document.body.style.background = "#0B0D0E";
  if (i) Object.assign(i.style, { width: "62%", height: "auto", margin: "0 auto", display: "block" });
});
await pause(800);
await caption("FIR-ready PDF: timeline, blurred frames, AI description (marked), evidence levels, SHA-256 hashes.", "11 · INCIDENT REPORT");
await pause(3500);
for (let i = 0; i < 7; i++) { await page.mouse.wheel(0, 420); await pause(1700); }
await page.goto(`${BASE}/alerts/`);
await pause(1500);
await page.click('button:has-text("Security events")');
await pause(1500);
await caption("Security analytics out of the box: object taken, abandoned bag, loitering, running, fall, crowding, after-hours, snatch.", "11 · SECURITY");
await pause(6500);
await page.click('button:has-text("Object taken")', { timeout: 8000 }).catch(() => undefined);
await caption("Heuristics are Candidates until an AI check of blurred frames agrees → Probable. Every incident gets a PDF.", "11 · SECURITY");
await pause(6000);
await page.goto(`${BASE}/settings/`);
await pause(2000);
await page.locator('button:has-text("Get pairing code"), button:has-text("New code")').first().click({ timeout: 15000 }).catch(() => undefined);
await caption("Telegram: pair with a 6-digit code. Ask by voice note, search by photo, get alerts with clip + voice.", "12 · TELEGRAM");
await pause(8000);
const v = page.video();
await ctx.close();
await browser.close();
fs.renameSync(await v.path(), path.join(OUT, "film_patch.webm"));
fs.writeFileSync(path.join(OUT, "film_patch.log"), lines.join("\n") + "\n");
fs.writeFileSync(path.join(OUT, "film_patch_fast.json"), "[]");
console.log("patch:", lines.length, "captions");
