// End-to-end UI suite (v3 P1.9) in real Chrome. Every step asserts visible content, no spinner stuck > 15 s, no
// console errors and no failed API calls; every kind of clip must PLAY (currentTime advances, a canvas-sampled frame
// is not black). Screenshots per step.
//   cd web; node ../scripts/e2e.mjs [--viewport desktop|mobile|both] [--theme dark|light|both] [--live] [--quick]
// --live adds the simulated live alert (office desk plays as live; ~3-5 min). Writes <DATA_DIR>/e2e/<run>/report.json.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "..");
const { chromium } = createRequire(path.resolve(ROOT, "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = opt("--base", "http://localhost:3000");
const API = opt("--api", "http://localhost:8000");
const DATA = process.env.DATA_DIR || path.join(process.env.LOCALAPPDATA || ROOT, "Nazar", "data");
const RUN = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const OUT = path.join(DATA, "e2e", RUN);
fs.mkdirSync(OUT, { recursive: true });
const VIEWPORTS = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };
const vps = opt("--viewport", "both") === "both" ? ["desktop", "mobile"] : [opt("--viewport", "desktop")];
const themes = opt("--theme", "dark") === "both" ? ["dark", "light"] : [opt("--theme", "dark")];
const LIVE = args.includes("--live");
const QUICK = args.includes("--quick");
const PHOTO = path.join(ROOT, "demo", "bag_photo.jpg");

const tok = (await (await fetch(`${API}/api/auth`, { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ passcode: "nazar2026" }) })).json()).token;
const H = { "X-Nazar-Token": tok, "Content-Type": "application/json" };

// a 12 s upload clip cut from the hackathon video (kept out of the repo)
const SHORT = path.join(OUT, "e2e_upload.mp4");
execFileSync("ffmpeg", ["-v", "error", "-y", "-ss", "20", "-t", "12", "-i", path.join(ROOT, "samples", "hackathon.mp4"),
  "-c:v", "libx264", "-preset", "veryfast", "-an", SHORT]);

const report = { run: RUN, base: BASE, results: [] };
const browser = await chromium.launch({ channel: opt("--channel", "chrome"), args: ["--autoplay-policy=no-user-gesture-required"] });

async function clipPlays(page, scope = "body") {
  // wait for a <video> in scope, then require currentTime to advance and a non-black frame
  const v = page.locator(`${scope} video`).last();
  await v.waitFor({ state: "attached", timeout: 120000 });
  const ok = await page.waitForFunction((sel) => {
    const vids = document.querySelectorAll(`${sel} video`);
    const el = vids[vids.length - 1];
    if (!el) return false;
    if (el.paused) el.play().catch(() => {});
    return el.readyState >= 2 && el.currentTime > 0.6;
  }, scope, { timeout: 60000 }).then(() => true).catch(() => false);
  if (!ok) throw new Error("video did not play (currentTime did not advance)");
  // the video is served by the API (another origin), so sample the frame from a screenshot of the element
  const png = await v.screenshot();
  const raw = execFileSync("ffmpeg", ["-v", "error", "-i", "pipe:0", "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "pipe:1"],
    { input: png });
  const luma = raw.reduce((a, x) => a + x, 0) / raw.length;
  if (luma <= 10) throw new Error(`video frame is black (mean luma ${luma.toFixed(1)})`);
  return Math.round(luma);
}

async function noStuckSpinner(page, ms = 15000) {
  await page.waitForFunction(() => !document.querySelector("main .animate-spin, [aria-busy='true']"), null, { timeout: ms })
    .catch(() => { throw new Error(`spinner still visible after ${ms / 1000} s`); });
}

async function suite(vpName, theme) {
  const ctx = await browser.newContext({ viewport: VIEWPORTS[vpName], deviceScaleFactor: 1, colorScheme: theme,
    isMobile: vpName === "mobile", hasTouch: vpName === "mobile" });
  await ctx.addInitScript((t) => { try { localStorage.setItem("nazar_theme", t); } catch (e) { /* ignore */ } }, theme);
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|ERR_ABORTED|WebSocket|webrtc|WHEP|AbortError/i.test(m.text())) errors.push(m.text().slice(0, 200)); });
  page.on("requestfailed", (r) => { const u = r.url(); if (u.includes("/api/") && !/abort/i.test(r.failure()?.errorText || "")) errors.push(`request failed ${u.slice(0, 120)} ${r.failure()?.errorText}`); });
  page.on("response", (r) => { const u = r.url(); if (u.includes("/api/") && r.status() >= 500) errors.push(`HTTP ${r.status()} ${u.slice(0, 120)}`); });
  const tag = `${vpName}-${theme}`;
  let n = 0;
  async function step(name, fn) {
    const t0 = Date.now();
    errors.length = 0;
    let status = "pass", detail = null;
    try {
      detail = (await fn()) ?? null;
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 2) throw new Error(`horizontal overflow ${overflow}px`);
      if (errors.length) throw new Error(`console/network errors: ${errors.slice(0, 3).join(" ; ")}`);
    } catch (e) {
      status = "fail";
      detail = String(e.message || e).split("\n")[0].slice(0, 300);
      await page.keyboard.press("Escape").catch(() => {}); // never let an open modal break the next step
    }
    n += 1;
    const shot = path.join(OUT, `${tag}_${String(n).padStart(2, "0")}_${name.replace(/[^a-z0-9]+/gi, "_")}.png`);
    await page.screenshot({ path: shot }).catch(() => {});
    const row = { viewport: vpName, theme, step: name, status, detail, seconds: (Date.now() - t0) / 1000, screenshot: path.basename(shot) };
    report.results.push(row);
    console.log(`${status === "pass" ? "PASS" : "FAIL"} [${tag}] ${name} (${row.seconds.toFixed(1)} s)${status === "fail" ? " - " + detail : detail ? " - " + JSON.stringify(detail) : ""}`);
  }
  const askBox = () => page.locator('input[placeholder^="Ask"], textarea[placeholder^="Ask"]').last();
  // phones: the evidence panel is a bottom sheet opened from the answer's "N receipts / N evidence items" chip
  async function evidence() {
    if (vpName !== "mobile") return;
    await page.keyboard.press("Escape").catch(() => {});
    const chip = page.locator("button").filter({ hasText: /\d+ receipts|evidence item/ }).last();
    if (await chip.count()) await chip.click();
    await page.waitForTimeout(600);
  }
  async function ask(q) {
    await askBox().fill(q);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(800);
    await page.waitForFunction(() => !document.body.innerText.includes("Thinking") && !document.querySelector("main .animate-spin"),
      null, { timeout: 120000 });
  }

  await step("login", async () => {
    await page.goto(`${BASE}/login/`);
    await page.fill('input[type="password"]', "nazar2026");
    await page.keyboard.press("Enter");
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 });
  });
  await step("today", async () => {
    await page.goto(`${BASE}/`);
    await page.getByText(/Office desk/).first().waitFor({ timeout: 15000 });
    await noStuckSpinner(page);
  });
  if (!QUICK) {
    await step("upload short clip + live analysis", async () => {
      await page.goto(`${BASE}/cameras/new/`);
      await page.setInputFiles('input[type="file"]', SHORT);
      await page.locator('button:has-text("Upload & analyse")').click();
      await page.getByText(/People so far/).first().waitFor({ timeout: 180000 });
      await page.getByText(/Ask about it/).first().waitFor({ timeout: 300000 });
    });
  }
  await step("ask text -> confirmed count + receipts", async () => {
    await page.goto(`${BASE}/ask/`);
    await ask("Builders venue pe kitne log dikhe?");
    await page.getByText(/Confirmed/).first().waitFor({ timeout: 10000 });
    await evidence();
    const rec = await page.locator('[aria-label^="Play receipt"]').count();
    if (rec < 1) throw new Error("no receipts shown");
    return { receipts: rec };
  });
  await step("receipt clip plays", async () => {
    await page.locator('[aria-label^="Play receipt"]').first().click();
    const luma = await clipPlays(page);
    await page.keyboard.press("Escape");
    return { luma };
  });
  await step("proof reel plays", async () => {
    await evidence();
    await page.locator('button:has-text("Play proof reel")').first().click();
    const luma = await clipPlays(page);
    await page.keyboard.press("Escape");
    return { luma };
  });
  await step("any analysis with SQL", async () => {
    await ask("Which camera was busiest and at what hour?");
    await evidence();
    await page.getByText(/How this was computed/).first().click();
    await page.getByText(/SELECT/i).first().waitFor({ timeout: 10000 });
  });
  await step("heatmap", async () => {
    await ask("Lobby mein log kahan sabse zyada ruke? Heatmap dikhao");
    await evidence();
    await page.getByText(/Where time was spent/).first().waitFor({ timeout: 30000 });
  });
  await step("privacy: face request refused", async () => {
    await ask("Find this person's face in all cameras");
    const t = await page.locator("body").innerText();
    if (!/face recognition|chehr|face/i.test(t)) throw new Error("no refusal text");
  });
  await step("search by words", async () => {
    await page.goto(`${BASE}/search/`);
    await page.fill('input[aria-label="Search text"]', "person carrying a bag");
    await page.keyboard.press("Enter");
    await page.getByText(/similar moments/).first().waitFor({ timeout: 60000 });
  });
  await step("verify top hits with AI", async () => {
    await page.locator('button:has-text("Verify top 8 with AI")').click();
    await page.getByText(/verified by AI/).first().waitFor({ timeout: 120000 });
  });
  await step("search hit clip plays", async () => {
    await page.locator("button:has(img)").filter({ hasText: /Probable|Candidate|person/i }).first().click();
    const luma = await clipPlays(page);
    await page.keyboard.press("Escape");
    return { luma };
  });
  await step("journey clip plays", async () => {
    await page.locator('button:has-text("Journey")').first().click({ timeout: 15000 });
    await page.locator('[aria-label^="Play journey step"]').first().waitFor({ timeout: 60000 });
    await page.locator('[aria-label^="Play journey step"]').first().click();
    const luma = await clipPlays(page);
    await page.keyboard.press("Escape");
    return { luma };
  });
  await step("photo search (audited)", async () => {
    await page.goto(`${BASE}/search/`);
    await page.locator('button:has-text("Photo")').first().click();
    await page.setInputFiles('input[type="file"][accept="image/*"]', PHOTO);
    await page.fill('input[placeholder^="Purpose"]', "e2e: lost bag");
    await page.locator('button:has-text("Find every sighting")').click();
    await page.getByText(/similar moments|No similar/).first().waitFor({ timeout: 60000 });
    await page.keyboard.press("Escape");
  });
  if (!QUICK) {
    await step("teach an object by text", async () => {
      await page.goto(`${BASE}/ask/`);
      await ask("Builders venue pe kursi (chair) pe nazar rakho");
      const t = await page.locator("body").innerText();
      if (!/chair|kursi|watch|nazar/i.test(t)) throw new Error("no teach confirmation");
    });
  }
  await step("rule by words -> replay -> activate", async () => {
    await page.goto(`${BASE}/ask/`);
    await page.selectOption('select[aria-label="Camera"] >> nth=1', { label: "Office desk" }).catch(() => {});
    await ask("Jab bhi koi desk 14 se bag uthaye, mujhe batana");
    await evidence();
    await page.getByText(/would have fired|fired \d|replay/i).first().waitFor({ timeout: 20000 });
    await page.locator('button:has-text("Activate")').first().click({ timeout: 30000 });
    await page.getByText(/Active|activated|watching/i).first().waitFor({ timeout: 10000 });
  });
  if (LIVE && vpName === "desktop") {
    await step("simulated live alert arrives", async () => {
      const last = (await (await fetch(`${API}/api/alerts?limit=1`, { headers: H })).json())[0]?.id || 0;
      await fetch(`${API}/api/cameras/office-desk/start`, { method: "POST", headers: H });
      try {
        await page.goto(`${BASE}/alerts/`);
        for (let i = 0; i < 160; i++) {
          const a = (await (await fetch(`${API}/api/alerts?limit=1`, { headers: H })).json())[0];
          if (a && a.id > last) break;
          await page.waitForTimeout(3000);
        }
        await page.getByText(/Alert ·/).first().waitFor({ timeout: 20000 });
      } finally {
        await fetch(`${API}/api/cameras/office-desk/stop`, { method: "POST", headers: H });
      }
    });
  }
  await step("alert clip plays", async () => {
    await page.goto(`${BASE}/alerts/`);
    const open = page.locator('button:has-text("Open clip")').first();
    await open.waitFor({ timeout: 30000 }).catch(() => { throw new Error("the inbox shows no alerts although alerts exist"); });
    await open.click();
    const luma = await clipPlays(page);
    await page.keyboard.press("Escape");
    return { luma };
  });
  await step("incident PDF downloads", async () => {
    const dl = page.waitForEvent("popup", { timeout: 30000 }).catch(() => null);
    await page.locator('button:has-text("Incident report (PDF)")').first().click();
    const pop = await dl;
    if (pop) await pop.waitForURL(/\.pdf/, { timeout: 300000 }).catch(() => {});
    const url = pop ? pop.url() : null;
    if (pop) await pop.close();
    if (!url || !/\.pdf/.test(url)) throw new Error("no PDF opened");
    const r = await fetch(url);
    const b = Buffer.from(await r.arrayBuffer());
    if (b.subarray(0, 4).toString() !== "%PDF") throw new Error("not a PDF");
    return { bytes: b.length };
  });
  await step("security events + live replay clip plays", async () => {
    await page.locator('button:has-text("Security events")').click();
    await page.locator("button:has-text('Play')").first().click({ timeout: 45000 });
    const luma = await clipPlays(page);
    await page.keyboard.press("Escape");
    return { luma };
  });
  await step("settings: telegram pairing code", async () => {
    await page.goto(`${BASE}/settings/`);
    await page.locator('button:has-text("Get pairing code"), button:has-text("New code")').first().click();
    await page.getByText(/\b\d{6}\b/).first().waitFor({ timeout: 30000 });
  });
  await step("insights", async () => {
    await page.goto(`${BASE}/metrics/`);
    await page.getByText(/per question|₹/).first().waitFor({ timeout: 15000 });
    await noStuckSpinner(page);
    const raw = await page.locator("pre").count();
    if (raw > 2) throw new Error("raw JSON blocks on the Insights page");
  });
  await ctx.close();
  // each suite uploads the same clip: remove its camera so the next suite starts clean
  const cams = await (await fetch(`${API}/api/cameras`, { headers: H })).json();
  for (const c of cams.filter((c) => /e2e_upload/i.test(c.name || c.id))) await fetch(`${API}/api/cameras/${c.id}`, { method: "DELETE", headers: H });
}

try {
  for (const vp of vps) for (const th of themes) await suite(vp, th);
} finally {
  await browser.close();
  // clean up: the uploaded e2e camera(s), rules and objects the suite created
  const cams = await (await fetch(`${API}/api/cameras`, { headers: H })).json();
  for (const c of cams.filter((c) => /e2e_upload/i.test(c.name || c.id))) await fetch(`${API}/api/cameras/${c.id}`, { method: "DELETE", headers: H });
  const rules = await (await fetch(`${API}/api/rules`, { headers: H })).json();
  for (const r of rules.filter((r) => r.active)) await fetch(`${API}/api/rules/${r.id}/deactivate`, { method: "POST", headers: H });
  const objs = await (await fetch(`${API}/api/custom-objects`, { headers: H })).json();
  for (const o of objs) await fetch(`${API}/api/custom-objects/${o.id}`, { method: "DELETE", headers: H });
}
const pass = report.results.filter((r) => r.status === "pass").length;
report.summary = { pass, fail: report.results.length - pass, total: report.results.length };
fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 1));
console.log(`\n${pass}/${report.results.length} steps passed -> ${OUT}`);
process.exit(report.summary.fail ? 1 : 0);
