// Screenshots of every screen at 390 px and 1440 px, dark and light (W11 self-review).
//   cd web; node ../scripts/shots_v2.mjs [--only ask,today] [--theme dark|light|both] [--out ../docs/screenshots/v2]
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = opt("--base", "http://localhost:3000");
const OUT = path.resolve(opt("--out", path.resolve(here, "..", "docs", "screenshots", "v2")));
const ONLY = opt("--only", "");
const THEMES = opt("--theme", "both") === "both" ? ["dark", "light"] : [opt("--theme", "dark")];
const ASK = opt("--ask", "");
fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ["today", "/"],
  ["ask", "/ask/"],
  ["search", "/search/"],
  ["live", "/live/"],
  ["cameras", "/cameras/"],
  ["camera", "/camera/?id=builders-venue"],
  ["add-camera", "/cameras/new/"],
  ["alerts", "/alerts/"],
  ["reports", "/reports/"],
  ["insights", "/metrics/"],
  ["settings", "/settings/"],
  ["login", "/login/"],
].filter(([n]) => !ONLY || ONLY.split(",").includes(n));

const browser = await chromium.launch({ channel: opt("--channel", undefined) });
const problems = [];
for (const theme of THEMES) {
  for (const [w, h, tag] of [[390, 844, "390"], [1440, 900, "1440"]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: tag === "390" ? 2 : 1 });
    const page = await ctx.newPage();
    page.on("console", (m) => m.type() === "error" && problems.push(`[${theme} ${tag}] console: ${m.text().slice(0, 160)}`));
    await page.goto(`${BASE}/login/`);
    await page.evaluate((t) => localStorage.setItem("nazar_theme", t), theme);
    await page.fill('input[type="password"]', "nazar2026");
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 });
    for (const [name, url] of PAGES) {
      if (name === "login") {
        await page.evaluate(() => localStorage.removeItem("nazar_token"));
      }
      await page.goto(`${BASE}${url}`);
      await page.waitForTimeout(name === "ask" && ASK ? 500 : 2500);
      if (name === "ask" && ASK) {
        await page.fill('input[placeholder^="Ask"]', ASK);
        await page.keyboard.press("Enter");
        await page.waitForSelector("text=/ s ·/", { timeout: 90000 }).catch(() => undefined);
        await page.waitForTimeout(2500);
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 2) problems.push(`[${theme} ${tag}] ${name}: horizontal overflow ${overflow}px`);
      await page.screenshot({ path: path.join(OUT, `${name}-${tag}-${theme}.png`), fullPage: tag === "1440" && name !== "ask" });
      if (name === "login") {
        await page.fill('input[type="password"]', "nazar2026");
        await page.click('button[type="submit"]');
        await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 }).catch(() => undefined);
      }
    }
    await ctx.close();
  }
}
await browser.close();
console.log(problems.length ? problems.join("\n") : "no console errors, no horizontal overflow");
console.log("screenshots:", OUT);
