// Short recording of the clip player in real Chrome (H.264): open a person track, the clip plays with the tracked
// box drawn on a canvas, then "Find again".   cd web; node ../scripts/demo_clip_player.mjs [--camera lobby]
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = opt("--base", "http://localhost:3000");
const CAM = opt("--camera", "lobby");
const OUT = path.resolve(here, "..", "demo");
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: opt("--channel", "chrome") });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, recordVideo: { dir: OUT, size: { width: 1280, height: 800 } } });
const page = await ctx.newPage();
const caption = (t) => page.evaluate((t) => {
  let d = document.getElementById("demo-cap");
  if (!d) {
    d = document.createElement("div");
    d.id = "demo-cap";
    Object.assign(d.style, { position: "fixed", left: "50%", transform: "translateX(-50%)", top: "96px", zIndex: "99999",
      background: "rgba(15,23,42,.92)", color: "#fff", padding: "10px 18px", borderRadius: "14px",
      font: "600 16px Inter, system-ui, sans-serif", maxWidth: "86%", textAlign: "center", pointerEvents: "none" });
    document.body.appendChild(d);
  }
  d.textContent = t;
}, t);

await page.goto(`${BASE}/login/`);
await page.fill('input[type="password"]', "nazar2026");
await page.click('button:has-text("Continue")');
await page.waitForURL(`${BASE}/`);
await page.goto(`${BASE}/camera/?id=${CAM}`);
await page.waitForTimeout(3000);
await caption("Tap any tracked person to open the evidence clip");
await page.waitForTimeout(2500);
await page.locator("button:has(img)").nth(2).click({ timeout: 10000 });
await page.waitForSelector("video", { timeout: 30000 });
await page.waitForTimeout(1500);
await caption("Clip cut from stored 10-second segments; the tracked box is drawn live on a canvas. Faces stay blurred.");
await page.waitForTimeout(9000);
const fa = page.locator('button:has-text("Find again")');
await fa.click({ force: true, timeout: 10000 }).catch(() => undefined);
await page.waitForTimeout(3500);
await caption("Find again: same-looking people within ±24 h from a 76-number appearance fingerprint — no face recognition");
await page.waitForTimeout(6000);
const v = page.video();
await ctx.close();
await browser.close();
const dst = path.join(OUT, "clip_player_chrome.webm");
fs.renameSync(await v.path(), dst);
console.log("video:", dst);
