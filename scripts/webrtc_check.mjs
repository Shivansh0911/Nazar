// W10 check: start a camera as live, open /live/ in Chrome, report WebRTC vs MJPEG and take a screenshot with the
// wall-clock time in the filename (compare with the time burned into the frame = glass-to-glass latency).
//   cd web; node ../scripts/webrtc_check.mjs [--camera builders-venue]
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const CAM = opt("--camera", "builders-venue");
const BASE = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = path.resolve(here, "..", "docs", "screenshots", "v2");

const tok = (await (await fetch(`${API}/api/auth`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ passcode: "nazar2026" }) })).json()).token;
const H = { "X-Nazar-Token": tok };
await fetch(`${API}/api/cameras/${CAM}/start`, { method: "POST", headers: H });
const browser = await chromium.launch({ channel: opt("--channel", "chrome") });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${BASE}/login/`);
await page.fill('input[type="password"]', "nazar2026");
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/`);
let mode = "none";
for (let i = 0; i < 30; i++) {  // the edge needs ~20-40 s to load models and connect
  await page.goto(`${BASE}/live/`);
  await page.waitForTimeout(9000);
  mode = await page.evaluate(() => [...document.querySelectorAll("span")].map((s) => s.textContent || "").find((t) => /WebRTC|MJPEG|connecting/.test(t)) || "none");
  console.log(`try ${i}: ${mode}`);
  if (mode.includes("WebRTC")) break;
}
const ts = new Date();
const name = `live-webrtc-${ts.toTimeString().slice(0, 8).replace(/:/g, "")}-${String(ts.getMilliseconds()).padStart(3, "0")}.png`;
await page.screenshot({ path: path.join(OUT, name) });
console.log("mode:", mode, "screenshot taken at", ts.toTimeString().slice(0, 8) + "." + String(ts.getMilliseconds()).padStart(3, "0"), "->", name);
await browser.close();
await fetch(`${API}/api/cameras/${CAM}/stop`, { method: "POST", headers: H });
