// Real-browser end-to-end check against a running stack (not part of `npm test`).
//
//   1. inference-service with ENABLE_UNIVERSAL_ENGINE=true and sdk/sites.local.json on :8000
//   2. python sdk/examples/rewards-campaign/server.py on :5500
//   3. node test/e2e.browser.mjs [--channel chrome|msedge]
//
// Scene A: a person-like session through the example campaign (script-tag install) gets paid.
// Scene B: the Lens extension on a local page that copies CyreneAI's strict Content Security
//          Policy (scripts by nonce only, network calls to its own host only) still reports events.
import { createServer } from "node:http";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";

const channel = process.argv.includes("--channel") ? process.argv[process.argv.indexOf("--channel") + 1] : "msedge";
const API = "http://127.0.0.1:8000";
let seed = 7;
const rand = (lo, hi) => { seed = (seed * 16807) % 2147483647; return lo + (seed / 2147483647) * (hi - lo); };
let failures = 0;
const check = (ok, label) => { console.log(`${ok ? "PASS" : "FAIL"}  ${label}`); if (!ok) failures += 1; };

async function humanScene() {
  const browser = await chromium.launch({ channel, headless: true });
  const page = await browser.newPage();
  const sent = [];
  page.on("request", (r) => { if (r.url().includes("/api/v1/sdk/events")) sent.push(...JSON.parse(r.postData() || "{}").events ?? []); });
  await page.goto("http://localhost:5500");
  await page.waitForFunction(() => window.neurosoc !== undefined);

  const wander = async (x, y) => {
    await page.mouse.move(x + rand(-40, 40), y + rand(-30, 30), { steps: Math.round(rand(8, 20)) });
    await page.mouse.move(x, y, { steps: Math.round(rand(5, 12)) });
  };
  const click = async (selector) => {
    const box = await page.locator(selector).boundingBox();
    await wander(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(rand(200, 600));
    await page.click(selector);
  };
  const type = async (selector, text) => {
    await click(selector);
    for (const [index, ch] of [...text].entries()) {
      await page.keyboard.type(ch);
      await page.waitForTimeout(rand(60, 300) + (ch === " " ? rand(150, 500) : 0));
      if (index === 4) { await page.keyboard.press("Backspace"); await page.waitForTimeout(rand(150, 350)); await page.keyboard.type(ch); }
    }
  };

  await click("#connect-wallet");
  await type("input[name=handle]", "maya builds");
  await type("textarea[name=why]", "a dex dashboard for our dao");
  await click("#profile-form button");
  for (const task of ["follow", "discord", "try"]) await click(`[data-task=${task}]`);
  await click("#claim");
  await page.waitForSelector("#result.paid, #result.pending", { timeout: 15000 });
  const paid = await page.isVisible("#result.paid");
  const session = await page.evaluate(() => window.neurosoc.sessionId);
  await browser.close();

  const actions = sent.map((e) => e.action);
  check(["session.start", "page.view", "wallet.connect", "campaign.join", "task.complete", "reward.claim"].every((a) => actions.includes(a)),
    `SDK sent the whole flow (${[...new Set(actions)].join(", ")})`);
  const keys = new Set(sent.flatMap((e) => e.telemetry?.events ?? []).map((t) => t.key).filter(Boolean));
  check([...keys].every((k) => ["char", "space", "backspace", "delete", "enter", "tab", "other"].includes(k)), `only key classes left the page (${[...keys].join(", ")})`);
  check(paid, "a person-like session was paid");
  return session;
}

async function lensScene() {
  // A page on :5174 (a Lens-enabled host) with CyreneAI's CSP shape.
  const csp = "default-src 'none'; script-src 'nonce-abc123'; connect-src 'self'; style-src 'unsafe-inline'";
  const server = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html", "Content-Security-Policy": csp });
    res.end(`<!doctype html><html><body><h1>CSP-locked page</h1><form id="f"><input name="q"><button>Go</button></form>
      <script nonce="abc123">document.getElementById("f").addEventListener("submit", (e) => e.preventDefault());</script></body></html>`);
  }).listen(5174);
  const extension = resolve("../extension");
  const context = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "lens-")), {
    channel, headless: false,
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`, "--headless=new"],
  });
  try {
    const page = await context.newPage();
    const blocked = [];
    page.on("console", (m) => { if (/Content Security Policy/i.test(m.text())) blocked.push(m.text()); });
    await page.goto("http://localhost:5174/");
    const started = await page.waitForFunction(() => window.neurosoc !== undefined, null, { timeout: 8000 }).then(() => true, () => false);
    check(started, "Lens started the SDK on a CSP-locked page");
    if (!started) return;
    await page.click("input[name=q]");
    await page.keyboard.type("hello", { delay: 120 });
    await page.click("button");
    await page.waitForTimeout(3500);
    const session = await page.evaluate(() => window.neurosoc.sessionId);
    const verdicts = await (await fetch(`${API}/api/v1/universal/verdicts/latest?limit=50`)).json();
    const mine = verdicts.verdicts.filter((v) => v.session_id === session);
    check(mine.length > 0, `events reached NeuroSOC through the extension despite connect-src 'self' (${mine.map((v) => v.event_action).join(", ")})`);
    check(blocked.length === 0, "no CSP violations from the SDK");
  } finally {
    await context.close();
    server.close();
  }
}

async function botScene(count = 6) {
  // Scripted browsers: fields filled programmatically, clicks without real pointer travel.
  const browser = await chromium.launch({ channel, headless: true });
  const results = [];
  for (let i = 0; i < count; i += 1) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto("http://localhost:5500");
    await page.waitForFunction(() => window.neurosoc !== undefined);
    await page.click("#connect-wallet");
    await page.fill("input[name=handle]", `user${i}`);
    await page.fill("textarea[name=why]", "airdrop");
    await page.click("#profile-form button");
    for (const task of ["follow", "discord", "try"]) await page.click(`[data-task=${task}]`);
    await page.click("#claim");
    await page.waitForSelector("#result.paid, #result.pending", { timeout: 15000 });
    results.push(await page.isVisible("#result.pending"));
    await context.close();
  }
  await browser.close();
  check(results.every(Boolean), `every scripted browser was held for review (${results.filter(Boolean).length}/${count})`);
}

const session = await humanScene();
await botScene();
const verdict = await (await fetch(`${API}/api/v1/universal/verdicts/latest?limit=50`)).json();
const claim = verdict.verdicts.find((v) => v.session_id === session && v.event_action === "reward.claim");
check(claim?.verdict === "ok", `engine verdict for the person: ${claim?.verdict} (humanity ${claim?.scores?.humanity})`);
await lensScene();
console.log(failures ? `\n${failures} check(s) failed` : "\nAll browser checks passed");
process.exit(failures ? 1 : 0);
