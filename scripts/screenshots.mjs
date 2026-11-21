// Screenshots of the running app for the README and visual self-review.
//   cd web; node ../scripts/screenshots.mjs [--base http://localhost:3000] [--ask "Aaj kitne log aaye?"]
// Needs: API on :8000 with demo data, web on :3000 (npm run dev, or a static server on web/out), Playwright chromium.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// playwright is a devDependency of web/
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const outDir = path.resolve(here, "..", "docs", "screenshots");
fs.mkdirSync(outDir, { recursive: true });

const args = process.argv.slice(2);
const opt = (k, d) => {
  const i = args.indexOf(k);
  return i >= 0 ? args[i + 1] : d;
};
const BASE = opt("--base", "http://localhost:3000").replace(/\/$/, "");
const PASS = opt("--pass", process.env.DEMO_PASSCODE || "nazar2026");
const ASKS = args.flatMap((a, i) => (a === "--ask" ? [args[i + 1]] : []));
const DESK = opt("--desk-camera", "office-desk");

async function shot(page, name, full = false) {
  const p = path.join(outDir, name);
  await page.screenshot({ path: p, fullPage: full });
  console.log("saved", path.relative(process.cwd(), p));
}

const browser = await chromium.launch();
for (const vp of [
  { tag: "mobile", width: 390, height: 844, deviceScaleFactor: 2 },
  { tag: "desktop", width: 1280, height: 860, deviceScaleFactor: 1 },
]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: vp.deviceScaleFactor });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("pageerror:", e.message));
  await page.goto(`${BASE}/login/`);
  await page.fill('input[type="password"]', PASS);
  await page.click('button:has-text("Continue")');
  await page.waitForURL(`${BASE}/`);
  await page.waitForTimeout(800);
  if (vp.tag === "mobile") await shot(page, "chat_empty_mobile.png");
  for (const q of ASKS) {
    await page.fill('input[placeholder^="Ask"]', q);
    await page.keyboard.press("Enter");
    await page.waitForSelector("text=Watching the footage", { state: "detached", timeout: 90000 }).catch(() => undefined);
    await page.waitForTimeout(1500);
  }
  if (ASKS.length) await shot(page, `chat_${vp.tag}.png`, true);
  if (vp.tag === "desktop" && ASKS.length) await shot(page, "chat.png", true);

  await page.goto(`${BASE}/cameras/`);
  await page.waitForTimeout(2500);
  await shot(page, `cameras_${vp.tag}.png`, true);

  await page.goto(`${BASE}/camera/?id=${DESK}`);
  await page.waitForTimeout(3000);
  await shot(page, `camera_zones_${vp.tag}.png`, true);

  await page.goto(`${BASE}/rules/`);
  await page.waitForTimeout(2500);
  await shot(page, `rules_${vp.tag}.png`, true);

  await page.goto(`${BASE}/metrics/`);
  await page.waitForTimeout(2000);
  await shot(page, `metrics_${vp.tag}.png`, true);

  await page.goto(`${BASE}/cameras/new/`);
  await page.waitForTimeout(800);
  await shot(page, `add_camera_${vp.tag}.png`);
  await page.click('button:has-text("Phone")');
  await page.waitForTimeout(1200);
  await shot(page, `add_camera_phone_${vp.tag}.png`, true);

  // no horizontal scroll at phone width
  if (vp.tag === "mobile") {
    for (const route of ["/", "/cameras/", `/camera/?id=${DESK}`, "/rules/", "/metrics/", "/cameras/new/"]) {
      await page.goto(`${BASE}${route}`);
      await page.waitForTimeout(1200);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      console.log(`horizontal overflow ${route}: ${overflow}px`);
    }
  }
  await ctx.close();
}
await browser.close();
