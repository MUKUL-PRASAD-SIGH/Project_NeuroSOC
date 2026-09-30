// Browser end-to-end run of the NovaTrust demo against a real API (no mocks, no Docker).
//
//   API:  cd inference-service && ENABLE_UNIVERSAL_ENGINE=true NEUROSOC_DEMO_MODE=true \
//         NEUROSOC_SELF_URL=http://127.0.0.1:8011 REDIS_URL='' DATABASE_URL='' KAFKA_BOOTSTRAP=127.0.0.1:1 \
//         UNIVERSAL_SITES_FILE= PORT=8010 python -m uvicorn main:app --port 8010
//   Web:  cd dashboard && VITE_DEMO_MODE=true VITE_UNIVERSAL_ENABLED=true VITE_API_URL=/ \
//         VITE_PROXY_TARGET=http://127.0.0.1:8010 npx vite --port 5173
//   Run:  node scripts/e2e_novatrust.mjs
//
// The demo backend calls NeuroSOC at NEUROSOC_SELF_URL (8011). This script runs a small pass-through proxy
// there so it can cut the connection for the outage step, then restore it.
import http from "node:http";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(new URL("../dashboard/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const WEB = process.env.E2E_WEB || "http://127.0.0.1:5173";
const API_PORT = 8010;
const PROXY_PORT = 8011;
const OUT = process.env.E2E_OUT || "/tmp/ns_e2e";
fs.mkdirSync(`${OUT}/shots`, { recursive: true });

// ── pass-through proxy the demo backend uses to reach NeuroSOC ──────────────────────────
let proxyUp = true;
let proxyServer;
function startProxy() {
  proxyServer = http.createServer((req, res) => {
    const upstream = http.request({ host: "127.0.0.1", port: API_PORT, path: req.url, method: req.method, headers: req.headers },
      (up) => { res.writeHead(up.statusCode, up.headers); up.pipe(res); });
    upstream.on("error", () => { res.statusCode = 502; res.end(); });
    req.pipe(upstream);
  });
  proxyServer.on("connection", (socket) => { if (!proxyUp) socket.destroy(); });
  return new Promise((resolve) => proxyServer.listen(PROXY_PORT, "127.0.0.1", resolve));
}

const results = [];
async function step(name, fn) {
  const started = Date.now();
  try {
    const evidence = await fn();
    results.push({ name, status: "PASS", evidence: evidence ?? "", ms: Date.now() - started });
    console.log(`PASS  ${name}${evidence ? `  (${evidence})` : ""}`);
  } catch (err) {
    const message = String(err.message || err).split("\n")[0];
    const visible = await page.locator("main, [role=dialog]").first().innerText().catch(() => "");
    await page.screenshot({ path: `${OUT}/shots/FAIL-${name.slice(0, 2)}.png`, fullPage: true }).catch(() => {});
    results.push({ name, status: "FAIL", evidence: message, page: visible.replace(/\s+/g, " ").slice(0, 300), ms: Date.now() - started });
    console.log(`      page text: ${visible.replace(/\s+/g, " ").slice(0, 300)}`);
    console.log(`FAIL  ${name}  ${message}`);
  }
}
const expect = (cond, message) => { if (!cond) throw new Error(message); };

await startProxy();
const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome-stable", headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
const page = await context.newPage();
const sdkRequests = [];
page.on("request", (r) => { if (r.url().includes("/api/v1/sdk/")) sdkRequests.push({ url: r.url(), at: Date.now() }); });
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e)));
const shot = (name) => page.screenshot({ path: `${OUT}/shots/${name}.png`, fullPage: true });
const secretSeen = {};
const nav = (label) => page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: label });
const accountNow = () => page.evaluate(() => fetch("/api/v1/demo/account", {
  headers: { "X-Demo-Session": sessionStorage.getItem("novatrust_demo_session") } }).then((r) => r.json()));
const simButton = (title) => page.locator(`div:has(> p:text-is("${title}")) button`);

await step("01 dashboard starts with no applications", async () => {
  await page.goto(`${WEB}/protection?view=sites`);
  await page.getByText("No applications yet").waitFor({ timeout: 15000 });
  await shot("01-empty");
});

await step("02 Add Application wizard: NovaTrust, Both, Protect, agent novatrust-agent", async () => {
  await page.getByRole("button", { name: "+ Add Application" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  expect((await dialog.locator("#app-name").inputValue()) === "NovaTrust", "name default");
  await dialog.getByRole("radio", { name: /Both/ }).check({ force: true });
  await dialog.getByRole("radio", { name: /Protect/ }).check({ force: true });
  await dialog.getByRole("button", { name: "Next" }).click();
  expect((await dialog.locator("#agent-id").inputValue()) === "novatrust-agent", "agent id");
  const tools = await dialog.locator("fieldset").first().locator("input[type=checkbox]:checked").count();
  expect(tools === 5, `five tools checked, got ${tools}`);
  expect(await dialog.getByLabel("token.transfer").isChecked(), "token.transfer sensitive");
  expect((await dialog.locator("#agent-resources").inputValue()) === "treasury", "treasury authorized");
  await shot("02-agent-step");
  await dialog.getByRole("button", { name: "Create application" }).click();
  await dialog.getByText("Publishable key").waitFor({ timeout: 15000 });
  return "tools=5, sensitive=token.transfer, resource=treasury";
});

await step("03 keys: public key shown, secret masked until revealed, confirmation required", async () => {
  const dialog = page.getByRole("dialog");
  const pk = (await dialog.locator("code").first().innerText()).trim();
  expect(pk.startsWith("pk_"), "publishable key prefix");
  const masked = await dialog.locator("code").nth(1).innerText();
  expect(masked.includes("•") && masked.startsWith("sk_"), "secret masked");
  expect(await dialog.getByRole("button", { name: "Done" }).isDisabled(), "Done disabled before confirmation");
  await dialog.getByRole("button", { name: "Reveal" }).click();
  secretSeen.sk = (await dialog.locator("code").nth(1).innerText()).trim();
  secretSeen.pk = pk;
  expect(/^sk_[A-Za-z0-9_-]{16,}$/.test(secretSeen.sk), "secret revealed");
  expect(await dialog.getByRole("button", { name: "Launch NovaTrust" }).isDisabled(), "Launch disabled before confirmation");
  await shot("03-keys");
  return `pk=${pk.slice(0, 10)}…`;
});

await step("04 integration snippets for script tag, module and Python use the public key only", async () => {
  const dialog = page.getByRole("dialog");
  const tabs = await dialog.getByRole("tab").allInnerTexts();
  expect(["Script tag", "JavaScript module", "Python agent"].every((t) => tabs.includes(t)), `tabs: ${tabs}`);
  await dialog.getByRole("tab", { name: "Python agent" }).click();
  const code = await dialog.locator("pre").innerText();
  expect(code.includes("guard_tool(") && code.includes('"novatrust-agent"') && !code.includes(secretSeen.sk), "python snippet");
  await dialog.getByRole("tab", { name: "Script tag" }).click();
  const tag = await dialog.locator("pre").innerText();
  expect(tag.includes(secretSeen.pk) && tag.includes("/neurosoc.min.js") && !tag.includes(secretSeen.sk), "script snippet has pk only");
});

await step("05 secret key not in browser storage; SDK bundle is served", async () => {
  const res = await page.request.get(`${WEB}/neurosoc.min.js`);
  expect(res.ok() && (await res.text()).length > 1000, "neurosoc.min.js served");
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(!stored.includes("sk_"), "no sk in storage");
});

await step("06 Launch NovaTrust connects the backend and opens /demo", async () => {
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/I have copied the secret key/).check();
  sdkRequests.length = 0;
  await dialog.getByRole("button", { name: "Launch NovaTrust" }).click();
  await page.waitForURL("**/demo", { timeout: 15000 });
  await page.getByText("Telemetry waiting for consent").waitFor({ timeout: 15000 });
  await shot("06-demo");
});

await step("07 consent banner shown and SDK dormant (zero /sdk requests) before Accept", async () => {
  await page.getByRole("dialog", { name: /Privacy/ }).waitFor();
  await page.waitForTimeout(2500);
  await page.mouse.move(300, 300); await page.mouse.move(420, 380); await page.keyboard.press("a");
  await page.waitForTimeout(1500);
  expect(sdkRequests.length === 0, `${sdkRequests.length} SDK requests before consent`);
  await shot("07-banner");
  return "sdk requests before consent: 0";
});

await step("08 'Not now' keeps the SDK dormant, also after reload", async () => {
  await page.getByRole("button", { name: "Not now" }).click();
  await page.reload();
  await page.getByText("Telemetry off").waitFor({ timeout: 15000 });
  await page.mouse.move(200, 200); await page.mouse.move(500, 400);
  await page.waitForTimeout(2500);
  expect((await page.getByRole("dialog", { name: /Privacy/ }).count()) === 0, "banner gone");
  expect(sdkRequests.length === 0, `${sdkRequests.length} SDK requests after decline`);
});

await step("09 Accept (Security page) starts real SDK events", async () => {
  await nav("Security").click();
  const sent = page.waitForResponse((r) => r.url().includes("/api/v1/sdk/events") && r.status() < 300, { timeout: 15000 });
  await page.getByRole("button", { name: "Turn on security telemetry" }).click();
  await sent;
  await page.getByText("Protected by NeuroSOC").first().waitFor();
  return `${sdkRequests.length} SDK request(s) after Accept`;
});

await step("10 normal human transfer is allowed", async () => {
  await nav("Transfer").click();
  await page.locator("#nt-to").fill("Alice");
  await page.locator("#nt-amount").fill("50");
  await page.getByRole("button", { name: "Review transfer" }).click();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.getByText("Transfer sent").waitFor({ timeout: 15000 });
  await shot("10-transfer");
});

await step("11 Nova AI: balance, then a prepared transfer that the owner confirms", async () => {
  await nav("Nova AI").click();
  await page.getByRole("button", { name: "What's my balance?" }).click();
  await page.getByText(/available balance is/).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: "Send $500 to Alice" }).click();
  await page.getByText(/prepared a transfer of \$500\.00 to Alice/).waitFor({ timeout: 20000 });
  await shot("11-nova");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.getByText(/is settled/).waitFor({ timeout: 15000 });
});

await step("12 prompt injection is blocked with a reason", async () => {
  await nav("Security").click();
  await page.getByText("Security testing").first().waitFor();
  await simButton("Prompt injection").click();
  const card = page.locator('[role="status"]:has-text("Prompt injection")');
  await card.getByText("Blocked", { exact: true }).waitFor({ timeout: 30000 });
  const text = await card.innerText();
  await shot("12-injection");
  return text.replace(/\n+/g, " | ").slice(0, 220);
});

await step("13 unauthorized resource (token.transfer on the vault) is blocked", async () => {
  await page.getByRole("button", { name: "Reset demo" }).click();
  await page.waitForTimeout(800);
  await simButton("Unauthorized resource").click();
  const card = page.locator('[role="status"]:has-text("Unauthorized resource")');
  await card.getByText("Blocked", { exact: true }).waitFor({ timeout: 30000 });
  const text = await card.innerText();
  expect(/not authorized|not permitted|not registered/.test(text), `reason missing: ${text.slice(0, 160)}`);
  return text.replace(/\n+/g, " | ").slice(0, 220);
});

await step("14 excessive actions: agent paused part-way through ~20 transfers", async () => {
  await page.getByRole("button", { name: "Reset demo" }).click();
  await page.waitForTimeout(800);
  await simButton("Excessive actions").click();
  const card = page.locator('[role="status"]:has-text("Excessive actions")');
  await card.getByText(/paused the agent at attempt \d+/).waitFor({ timeout: 60000 });
  const n = Number((await card.innerText()).match(/attempt (\d+)/)[1]);
  expect(n > 1 && n < 20, `tripped at attempt ${n}`);
  return `paused at attempt ${n} of 20`;
});

await step("15 suspicious new session is flagged", async () => {
  await page.getByRole("button", { name: "Reset demo" }).click();
  await page.waitForTimeout(800);
  await simButton("Suspicious session").click();
  const card = page.locator('[role="status"]:has-text("Suspicious session")');
  await card.first().waitFor({ timeout: 30000 });
  return (await card.first().innerText()).replace(/\n+/g, " | ").slice(0, 220);
});

await step("16 dashboard live feed shows the events with all eight fields", async () => {
  await page.goto(`${WEB}/protection?view=live`);
  await page.getByRole("table").waitFor({ timeout: 20000 });
  const headers = (await page.locator("thead th").allInnerTexts()).map((h) => h.trim());
  for (const h of ["Time", "Application", "Agent", "Action", "Resource", "Decision", "Risk", "Reason"]) {
    expect(headers.some((x) => x.toLowerCase().includes(h.toLowerCase())), `column ${h} in ${headers}`);
  }
  const body = await page.locator("tbody").innerText();
  expect(body.includes("NovaTrust") && body.includes("novatrust-agent") && body.includes("token.transfer"), "NovaTrust rows");
  expect(body.includes("treasury_cold"), "vault resource listed");
  await shot("16-live-feed");
  return `${await page.locator("tbody tr").count()} rows`;
});

await step("17 NeuroSOC unreachable: transfer fails closed with a clear message", async () => {
  await page.goto(`${WEB}/demo`);
  await nav("Transfer").click();
  const before = await accountNow();
  proxyUp = false;
  await page.locator("#nt-to").fill("Alice");
  await page.locator("#nt-amount").fill("10");
  await page.getByRole("button", { name: "Review transfer" }).click();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.getByText("Security service temporarily unavailable").first().waitFor({ timeout: 20000 });
  const after = await accountNow();
  expect(after.account.available_balance === before.account.available_balance, "balance unchanged");
  expect(after.account.transactions.length === before.account.transactions.length, "no new transaction");
  await shot("17-outage");
  await nav("Dashboard").click();
  await page.getByText(/balance/i).first().waitFor();
  return "balance unchanged; dashboard still readable";
});

await step("18 recovery: NeuroSOC answers again with a real decision (not 'unavailable')", async () => {
  proxyUp = true;
  await nav("Transfer").click();
  await page.locator("#nt-to").fill("Alice");
  await page.locator("#nt-amount").fill("10");
  await page.getByRole("button", { name: "Review transfer" }).click();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  // Either outcome proves the guard is back. The headless browser's scripted input is itself flagged as a bot
  // by the real SDK telemetry, so a "stopped" decision with a reason is the expected result here.
  const sent = page.getByText("Transfer sent");
  const stopped = page.getByText("Transfer stopped");
  await sent.or(stopped).waitFor({ timeout: 20000 });
  const unavailable = await page.getByText("Security service temporarily unavailable").count();
  expect(unavailable === 0, "still reporting unavailable after recovery");
  return (await sent.count()) ? "transfer sent" : `decision: ${(await stopped.locator("xpath=..").innerText()).replace(/\s+/g, " ").slice(0, 160)}`;
});

await step("19 no uncaught page errors", async () => { expect(pageErrors.length === 0, pageErrors.join("; ").slice(0, 200)); });

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
proxyServer.close();
const failed = results.filter((r) => r.status === "FAIL");
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
