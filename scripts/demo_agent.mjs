// Agent film: the whole product in 3-4 minutes with the Investigator and MCP in the middle, recorded from the real app.
//   cd web; node ../scripts/demo_agent.mjs --mcp <json from a real MCP client run> | tee <DATA_DIR>/logs/demo_agent.log
// Needs API :8000, web :3000, Postgres, demo data; the vision service for the search chapter (skipped if it is down).
// Writes demo/nazar_agent.webm + demo/nazar_agent_fast.json; scripts/film_agent.py adds narration -> demo/nazar_agent_film.mp4
// Nothing is sent anywhere: the film approves only the local case note and leaves the Telegram message waiting.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.resolve(here, "..", "web", "package.json"))("playwright");
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BASE = opt("--base", "http://localhost:3000");
const OUT = path.resolve(here, "..", "demo");
const MCP = opt("--mcp", "");
const GOAL = opt("--goal", "21 Nov ki raat office desk se bag kisne uthaya? Poori jaanch karo, Pune ka mausam bhi dekho, " +
  "ek case note save karo aur mujhe Telegram pe chhota summary bhejo.");
fs.mkdirSync(OUT, { recursive: true });

let browser;
try {
  browser = await chromium.launch({ channel: opt("--channel", "chrome"), args: ["--autoplay-policy=no-user-gesture-required"] });
} catch {
  browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
}
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: OUT, size: { width: 1440, height: 900 } } });
const page = await ctx.newPage();
const t0 = Date.now();
const fast = [];
const now = () => (Date.now() - t0) / 1000;
const log = (m) => console.log(`[${now().toFixed(0).padStart(4)}s] ${m}`);
const pause = (ms) => page.waitForTimeout(ms);
const safe = (p) => p.catch((e) => log(`  (skipped: ${String(e).split("\n")[0].slice(0, 100)})`));

/** Caption on screen. With a chapter it is also a narration line, and the scene holds long enough to say it. */
async function say(text, chapter, extra = 600) {
  await page.evaluate(([t, c]) => {
    let d = document.getElementById("demo-cap");
    if (!d) {
      d = document.createElement("div");
      d.id = "demo-cap";
      Object.assign(d.style, { position: "fixed", left: "50%", transform: "translateX(-50%)", bottom: "26px", zIndex: "99999",
        background: "rgba(11,13,14,.94)", color: "#fff", padding: "12px 22px", borderRadius: "16px", border: "1px solid #FFB020",
        font: "600 21px Geist, Inter, system-ui, sans-serif", maxWidth: "78%", textAlign: "center", pointerEvents: "none",
        boxShadow: "0 10px 30px rgba(0,0,0,.45)", lineHeight: "1.4" });
      document.body.appendChild(d);
    }
    d.innerHTML = (c ? `<div style="font:700 13px Geist Mono,monospace;letter-spacing:.16em;color:#FFB020;margin-bottom:6px">${c}</div>` : "") + t;
  }, [text, chapter || ""]).catch(() => undefined);
  log(`${chapter ? chapter + " | " : ""}${text}`);
  if (chapter) await pause(Math.round((text.length / 14) * 1000) + extra);
}
async function waitFast(fn, ms = 0) { // recorded, but sped up in the film
  const a = now();
  await fn().catch((e) => log(`  (wait ended: ${String(e).split("\n")[0].slice(0, 80)})`));
  if (ms) await pause(ms);
  fast.push([a, now()]);
}
async function card(lines, id = "demo-title") {
  await page.evaluate(([ls, i]) => {
    document.getElementById(i)?.remove();
    const d = document.createElement("div");
    d.id = i;
    Object.assign(d.style, { position: "fixed", inset: "0", zIndex: "99998", background: "radial-gradient(circle at 50% 35%, #2A1E08 0%, #0B0D0E 62%)",
      color: "#fff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "14px",
      font: "500 23px Geist, Inter, system-ui, sans-serif", textAlign: "center", padding: "40px" });
    d.innerHTML = ls.map((l, k) => k === 0 ? `<div style="font:500 76px Fraunces,Georgia,serif;letter-spacing:-.02em">${l}</div>`
      : `<div style="opacity:.9;max-width:900px">${l}</div>`).join("");
    document.body.appendChild(d);
  }, [lines, id]);
}
const uncard = (id = "demo-title") => page.evaluate((i) => document.getElementById(i)?.remove(), id);
async function scrollBy(px, steps = 12) {
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, px / steps);
    await pause(70);
  }
}
const idle = (ms = 180000) => page.waitForFunction(() => !document.querySelector("main .animate-spin, section .animate-spin"), null, { timeout: ms });

// ---- 1. title + login + Today
await page.goto(`${BASE}/login/`);
await card(["Nazar", "Ask your CCTV anything, in your own language.", "Now with an agent that investigates, and tools it can connect to."]);
await say("Nazar turns any CCTV camera into something you can talk to. This film shows the product, and the new agent that plans, investigates and asks before it acts.", "NAZAR");
await uncard();
await page.fill('input[type="password"]', "nazar2026");
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/`);
await pause(2500);
await say("Today shows every camera, the overnight digest and the alerts. Cheap computer vision watches every frame on the owner's own machine, and faces are blurred in everything you see.", "TODAY");

// ---- 2. Ask: a count with receipts
await page.goto(`${BASE}/ask/`);
await pause(1500);
await say("Ask in Hindi, English or Hinglish. How many people came to the shop counter?", "ASK");
await page.fill('input[placeholder^="Ask"]', "21 Nov ko shop counter pe kitne log aaye?");
await pause(700);
await page.keyboard.press("Enter");
await pause(1500);
await waitFast(() => page.waitForFunction(() => !document.body.innerText.includes("Thinking") && !document.querySelector("main .animate-spin, section .animate-spin"), null, { timeout: 150000 }));
await pause(1200);
await say("The number comes from the database, never from the model. It is marked Confirmed, and every counted person is a receipt you can play.", "RECEIPTS");

// ---- 3. Search by words (local visual index)
await page.goto(`${BASE}/search/`);
await pause(1500);
await safe((async () => {
  await page.fill('input[aria-label="Search text"]', "person carrying a bag");
  await page.keyboard.press("Enter");
  await say("Search works like a photo library. Type what you are looking for.", "SEARCH");
  await waitFast(() => page.waitForSelector("text=similar moments", { timeout: 90000 }), 1000);
  await say("Matches from the local index start as Candidates. Only an independent check can raise one to Probable. Nazar never recognises faces.", "EVIDENCE LEVELS");
})());

// ---- 4. Investigate: connected tools
await page.goto(`${BASE}/agent/`);
await pause(2500);
await say("This is new. Investigate takes a goal, not a question.", "INVESTIGATE");
await safe(page.click('aside button:has-text("toolbox")', { timeout: 20000 }));
await pause(900);
await say("On the right are the tools the agent can use. Nazar's own, plus outside tools connected over the Model Context Protocol: weather, case notes, Telegram and Slack messages, and a long term memory.", "CONNECTED TOOLS");
await safe(page.click('aside button:has-text("memory")', { timeout: 5000 }));
await pause(600);
await say("Tools that only read run on their own. Tools with a shield change something, so they always ask the owner first.", "SAFETY");
await safe(page.click('aside button:has-text("memory")', { timeout: 5000 }));
await safe(page.click('aside button:has-text("toolbox")', { timeout: 5000 }));
await page.evaluate(() => window.scrollTo(0, 0));

// ---- 5. Investigate: the run
await page.locator("main textarea").pressSequentially(GOAL, { delay: 14 });
await say("The goal: find out who took the bag from the office desk, check the weather, save a case note and message me a summary.", "THE GOAL");
await page.click('main button:has-text("Investigate")');
await safe(page.waitForSelector("main ol li", { timeout: 90000 }));
await pause(800);
await say("First it thinks. It writes a plan of concrete checks before running anything.", "THINK");
await say("Then it executes. Each step calls real tools: security events, the tracker's counts, the journey of a track, a description of the clip, and the weather from a connected tool.", "EXECUTE");
await say("It follows the evidence, records a finding for every step, and adds a step when a new lead appears. The wait is sped up here.", "FOLLOW THE LEADS", 0);
await waitFast(() => page.waitForSelector("text=Case file #", { timeout: 300000 }), 800);
await page.evaluate(() => document.querySelector("main ol")?.scrollIntoView({ behavior: "smooth", block: "start" }));
await pause(1500);
await say("The plan is done. Every step shows what it found and which tools it used.", "THE PLAN");
await page.evaluate(() => [...document.querySelectorAll("main div")].find((d) => d.textContent?.startsWith("Case file #"))?.scrollIntoView({ behavior: "smooth", block: "start" }));
await pause(1500);
await say("The case file. Each finding carries an evidence level set by the server from the tool results it cites. The model cannot upgrade its own claims, and reasoning without evidence is labelled as such.", "CASE FILE");
await scrollBy(420);
await pause(800);

// ---- 6. approvals: approve the local note, leave the Telegram message waiting
await page.evaluate(() => [...document.querySelectorAll("main div")].find((d) => d.textContent?.startsWith("Actions"))?.scrollIntoView({ behavior: "smooth", block: "start" }));
await pause(1500);
await say("Nothing left the machine. The note and the Telegram message are waiting, with their exact contents, for the owner's approval.", "APPROVAL");
const note = page.locator("main div.rounded-2xl", { hasText: "save_case_note" }).locator('button:has-text("Approve and run")').first();
if (await note.count()) {
  await note.click();
  await waitFast(() => idle(60000), 600);
  await say("I approve the case note, and it is saved. The Telegram message stays unsent until I say so.", "ONE TAP");
} else {
  await say("One tap approves an action, and one tap rejects it. Until then nothing is sent.", "ONE TAP");
}
await scrollBy(600);
await pause(1500);
await say("Below is the evidence behind the case: the security events, the counts with their receipts, and the clips.", "EVIDENCE");
await scrollBy(500);
await pause(1200);

// ---- 7. from an alert
await page.goto(`${BASE}/alerts/`);
await pause(2500);
await say("An investigation can also start from an alert. One tap, and the agent works out what happened before and after.", "FROM AN ALERT");
const inv = page.locator('main a:has-text("Investigate")').first();
if (await inv.count()) {
  await inv.click();
  await safe(page.waitForSelector("main ol li", { timeout: 90000 }));
  await pause(1200);
  await waitFast(() => page.waitForSelector("text=Case file #", { timeout: 300000 }), 800);
  await page.evaluate(() => [...document.querySelectorAll("main div")].find((d) => d.textContent?.startsWith("Case file #"))?.scrollIntoView({ behavior: "smooth", block: "start" }));
  await pause(1200);
  await say("The same discipline every time: a plan, tool results, honest levels, and a queue for anything that needs a human.", "EVERY ALERT");
}

// ---- 8. Nazar as an MCP server (real output captured from a real client run)
if (MCP && fs.existsSync(MCP)) {
  const lines = JSON.parse(fs.readFileSync(MCP, "utf8")).lines;
  await page.evaluate(() => {
    const d = document.createElement("div");
    d.id = "demo-term";
    Object.assign(d.style, { position: "fixed", inset: "0", zIndex: "99998", background: "#0B0D0E", display: "flex", alignItems: "center", justifyContent: "center" });
    d.innerHTML = `<div style="width:1180px;border:1px solid #262b2e;border-radius:16px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.6)">
      <div style="background:#141719;padding:10px 16px;font:600 13px Geist Mono,monospace;color:#9a9c98;letter-spacing:.08em">MCP CLIENT  ·  output of a real session with Nazar's MCP server</div>
      <pre id="demo-term-body" style="margin:0;padding:20px 22px;height:520px;background:#0f1113;font:500 16px/1.65 Geist Mono,ui-monospace,monospace;color:#eceae4;white-space:pre-wrap;overflow:hidden"></pre></div>`;
    document.body.appendChild(d);
  });
  await say("It works the other way too. Nazar is itself an MCP server, so Claude Desktop, Claude Code or Cursor can query the cameras.", "NAZAR AS A TOOL", 0);
  for (const [kind, text] of lines) {
    await page.evaluate(([k, t]) => {
      const b = document.getElementById("demo-term-body");
      const s = document.createElement("div");
      s.style.color = k === "cmd" ? "#FFB020" : k === "ok" ? "#3ddc97" : "#9a9c98";
      s.textContent = (k === "cmd" ? "> " : "  ") + t;
      b.appendChild(s);
    }, [kind, text]);
    await pause(kind === "cmd" ? 900 : 500);
  }
  await say("Eighteen tools: counts with levels, security events, search, journeys, and face blurred images. Rules are only ever drafted. The owner switches them on.", "EIGHTEEN TOOLS");
  await page.evaluate(() => document.getElementById("demo-term")?.remove());
}

// ---- 9. cost + close
await page.goto(`${BASE}/metrics/`);
await pause(2500);
await say("Every model call is logged with its cost. Indexing footage costs nothing in AI. You pay when you ask, and an investigation costs a few rupees.", "COST");
await card(["Nazar", "Counts with receipts. Evidence levels set by code. An agent that plans, investigates and asks first.", "No face recognition. Footage stays on the owner's machine."]);
await say("Nazar. Ask your CCTV anything, and let it investigate.", "NAZAR", 2500);

const v = page.video();
await ctx.close();
await browser.close();
const dst = path.join(OUT, "nazar_agent.webm");
fs.renameSync(await v.path(), dst);
fs.writeFileSync(path.join(OUT, "nazar_agent_fast.json"), JSON.stringify(fast));
console.log("video:", dst, "fast intervals:", fast.length);
