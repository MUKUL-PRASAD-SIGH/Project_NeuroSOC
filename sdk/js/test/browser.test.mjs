// Real-browser tests: the built script bundle runs in Chromium (Edge or Chrome) against the dummy
// "Orbit" website and a controllable fake NeuroSOC API. No engine needed.
//
//   npm run build && npm run test:browser            (uses Edge; --channel chrome for Chrome)
import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { startFakeApi } from "./browser/fake-api.mjs";
import { startSite } from "./site-server.mjs";

const channel = process.env.BROWSER_CHANNEL || "msedge";
let browser, api, site;

before(async () => {
  api = await startFakeApi(8700);
  site = await startSite({ apiUrl: api.url });
  browser = await chromium.launch({ channel, headless: true });
});
after(async () => {
  await browser?.close();
  await site?.close();
  await api?.close();
});
beforeEach(() => { api.reset(); Object.values(site.received).forEach((list) => { list.length = 0; }); });

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, { timeout = 6000, label = "condition" } = {}) {
  const end = Date.now() + timeout;
  for (;;) {
    const value = await fn();
    if (value) return value;
    if (Date.now() > end) throw new Error(`timed out waiting for ${label}`);
    await wait(40);
  }
}
/** Open a page of the dummy site in a fresh browser context; collects console and page errors. */
async function open(path = "/", { context: contextOptions = {}, init, initArg } = {}) {
  const context = await browser.newContext({ viewport: { width: 1100, height: 800 }, ...contextOptions });
  if (init) await context.addInitScript(init, initArg);
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (m) => { if (m.type() === "error" || /Content Security Policy/i.test(m.text())) problems.push(`console: ${m.text()}`); });
  await page.goto(site.url + path);
  return { page, context, problems, close: () => context.close() };
}
const sdkReady = (page) => page.waitForFunction(() => window.neurosoc !== undefined);
const sessionOf = (page) => page.evaluate(() => window.neurosoc.sessionId);
const eventsOf = (session, action) => api.events().filter((e) => (!session || e.session_id === session) && (!action || e.action === action));
const flush = (page) => page.evaluate(() => window.neurosoc.flush());
/** Start the SDK by hand with options the script tag cannot express. */
async function manualInit(page, options) {
  await page.addScriptTag({ url: "/neurosoc.min.js" });
  return page.evaluate((o) => { window.neurosoc = window.NeuroSOC.init({ publishableKey: "pk_test_dummy", endpoint: o.endpoint, ...o.extra }); return true; },
    { endpoint: api.url, extra: options });
}

// ── install ────────────────────────────────────────────────────────────────
test("one script tag: starts, sends session.start and page.view as simple requests", async () => {
  const { page, problems, close } = await open("/");
  await sdkReady(page);
  await until(() => eventsOf(null, "page.view").length, { label: "page.view" });
  assert.equal(eventsOf(null, "session.start").length, 1);
  const first = api.state.requests[0];
  assert.match(first.url, /^\/api\/v1\/sdk\/events\?key=pk_test_dummy$/);
  assert.match(first.contentType, /^text\/plain/);
  assert.ok(!api.state.preflights, "no CORS preflight");
  assert.equal(await page.textContent("#status"), "SDK: active");
  assert.deepEqual(problems, []);
  await close();
});

test("exposes the client, version and ready(), and getMode() reflects the site settings", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  const info = await page.evaluate(async () => { await window.neurosoc.ready; return { mode: window.neurosoc.getMode(), version: window.NeuroSOC.version }; });
  assert.equal(info.mode, "enforce");
  assert.match(info.version, /^\d+\.\d+\.\d+/);
  await close();
});

test("a script tag without a key or endpoint warns instead of throwing", async () => {
  const { page, problems, close } = await open("/?nokey=1");
  const warned = [];
  page.on("console", (m) => warned.push(m.text()));
  await page.reload();
  await until(() => warned.some((t) => /needs both data-key and data-endpoint/.test(t)), { label: "warning" });
  assert.equal(await page.evaluate(() => window.neurosoc), undefined);
  assert.ok(!problems.some((p) => p.startsWith("pageerror")));
  await close();
});

// ── rules and actions ──────────────────────────────────────────────────────
test("rules turn clicks and submits into actions with the right resource and value", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  await page.click("#connect-wallet");
  await page.fill("#handle", "maya");
  await page.fill("#why", "a dex dashboard");
  await page.click("#signup-form button");
  for (const task of ["follow", "discord", "try"]) await page.click(`[data-task=${task}]`);
  await page.click("#claim");
  await until(() => page.evaluate(() => window.__lastVerdict), { label: "claim verdict" });
  const session = await sessionOf(page);
  const seen = new Set(eventsOf(session).map((e) => e.action));
  for (const action of ["wallet.connect", "account.create", "task.complete", "reward.claim"]) assert.ok(seen.has(action), `missing ${action} (saw ${[...seen]})`);
  assert.equal(eventsOf(session, "task.complete").length, 3);
  const claim = eventsOf(session, "reward.claim")[0];
  assert.deepEqual(claim.resource, { id: "early-access", type: "campaign", sensitivity: "medium" });
  assert.deepEqual(claim.value, { amount: 25 });
  assert.ok(claim.telemetry.events.length > 0, "interactive action carries the timing window");
  const visible = await page.evaluate(() => window.__lastVerdict);
  assert.deepEqual(Object.keys(visible).sort(), ["action", "enforced", "event_id", "session_id", "verdict_id"]);
  await close();
});

test("a click that lands before the rules arrive is still matched", async () => {
  api.state.configDelayMs = 700;
  const { page, close } = await open("/");
  await sdkReady(page);
  await page.click("[data-task=follow]"); // config is still in flight
  await until(() => eventsOf(null, "task.complete").length, { label: "early click tracked" });
  await close();
});

test("text rules: buy/swap buttons match, a long block that mentions them does not", async () => {
  const { page, close } = await open("/app");
  await sdkReady(page);
  await page.waitForSelector("#buy-orb");
  await page.click("#buy-orb");
  await page.click("#swap-nova");
  await page.click("#long-card p");
  await page.click("#long-card h2");
  await flush(page);
  await until(() => eventsOf(null, "token.buy").length >= 2, { label: "buys" });
  const buys = eventsOf(null, "token.buy");
  assert.equal(buys.length, 2, "only the two real buttons");
  assert.deepEqual(buys.map((b) => [b.resource.id, b.value.amount]).sort(), [["NOVA", 12], ["ORB", 50]]);
  assert.equal(buys[0].resource.sensitivity, "high");
  await close();
});

test("autoCapture can be turned off from the tag; manual track() still works", async () => {
  const { page, close } = await open("/?nocapture=1");
  await sdkReady(page);
  await page.click("[data-task=follow]");
  await page.evaluate(() => window.neurosoc.track({ action: "task.complete", resource: { id: "manual", type: "campaign" } }));
  await flush(page);
  const tasks = eventsOf(null, "task.complete");
  assert.deepEqual(tasks.map((t) => t.resource.id), ["manual"]);
  await close();
});

// ── privacy ────────────────────────────────────────────────────────────────
test("typed text never leaves the page: only key classes and timing", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  const secret = "hunter2-secret-handle";
  await page.click("#handle");
  await page.keyboard.type(secret, { delay: 15 });
  await page.keyboard.press("Backspace");
  await page.fill("#why", "my private idea");
  await page.click("#signup-form button");
  await page.click("#connect-wallet");
  await flush(page);
  const raw = JSON.stringify(api.state.requests);
  assert.ok(!raw.includes("hunter2") && !raw.includes("private idea") && !raw.includes(secret), "no typed content in any request");
  const keys = new Set(eventsOf().flatMap((e) => e.telemetry?.events ?? []).map((t) => t.key).filter(Boolean));
  assert.deepEqual([...keys].sort(), ["backspace", "char"]);
  await close();
});

test("the device hash is sent and is stable; it also works where crypto.subtle is missing (plain http)", async () => {
  const a = await open("/");
  await sdkReady(a.page);
  await until(() => eventsOf(null, "page.view").length);
  const hashed = eventsOf(null, "page.view")[0].context;
  assert.match(hashed.device_hash, /^[0-9a-f]{32}$/);
  assert.match(hashed.user_agent_hash, /^[0-9a-f]{32}$/);
  await a.close();
  api.reset();
  const b = await open("/", { init: () => { Object.defineProperty(crypto, "subtle", { value: undefined, configurable: true }); } });
  await sdkReady(b.page);
  await until(() => eventsOf(null, "page.view").length, { label: "events without crypto.subtle" });
  assert.match(eventsOf(null, "page.view")[0].context.device_hash, /^[0-9a-f]{32}$/);
  assert.deepEqual(b.problems, []);
  await b.close();
});

test("consent: nothing is sent or stored until accepted, and withdrawing removes it again", async () => {
  const { page, close } = await open("/?wait=1");
  await sdkReady(page);
  await page.click("[data-task=follow]");
  await wait(400);
  assert.equal(api.state.requests.length, 0, "nothing sent before consent");
  assert.deepEqual(await page.evaluate(() => [...Object.keys(localStorage), ...Object.keys(sessionStorage)].filter((k) => k.startsWith("nsoc_"))), [], "nothing stored before consent");

  await page.click("#consent-yes");
  await until(() => eventsOf(null, "session.start").length, { label: "session.start after consent" });
  assert.ok((await page.evaluate(() => Object.keys(localStorage))).includes("nsoc_vid"));
  await page.click("[data-task=discord]");
  await until(() => eventsOf(null, "task.complete").length === 1, { label: "one task after consent" });
  const countAfterAccept = api.events().length;

  await page.evaluate(() => window.neurosoc.consent(false));
  await page.click("[data-task=try]");
  await page.keyboard.type("abc");
  await wait(2600);
  assert.equal(api.events().length, countAfterAccept, "nothing sent after withdrawal");
  assert.deepEqual(await page.evaluate(() => Object.keys(localStorage).concat(Object.keys(sessionStorage)).filter((k) => k.startsWith("nsoc_"))), [], "storage cleared");

  // Regrant: capture resumes with no duplicated listeners (one click, one event).
  await page.evaluate(() => window.neurosoc.consent(true));
  await until(() => eventsOf(null, "session.start").length === 2, { label: "fresh session.start" });
  api.state.requests.length = 0;
  await page.click("[data-task=follow]");
  await flush(page);
  await until(() => eventsOf(null, "task.complete").length, { label: "task after regrant" });
  assert.equal(eventsOf(null, "task.complete").length, 1, "exactly one event per click after regrant");
  assert.equal(eventsOf(null, "page.view").length <= 1, true);
  await close();
});

test("consent choice remembered by the site: banner hidden, capture starts on load", async () => {
  const { page, close } = await open("/?wait=1");
  await sdkReady(page);
  await page.click("#consent-yes");
  await until(() => eventsOf(null, "session.start").length);
  api.reset();
  await page.reload();
  await sdkReady(page);
  await until(() => eventsOf(null, "page.view").length, { label: "page.view after reload" });
  assert.equal(await page.isHidden("#consent"), true);
  await close();
});

// ── forms ──────────────────────────────────────────────────────────────────
test("session id is added to same-origin POST forms (fetch + native), never to GET or cross-origin forms", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  const session = await sessionOf(page);

  await page.fill("#handle", "x"); await page.fill("#why", "y");
  await page.click("#signup-form button");
  await until(() => site.received.signups.length, { label: "signup" });
  assert.equal(site.received.signups[0].neurosoc_session, session, "fetch(new FormData(form)) carries the session");

  await page.fill("#external-form input", "hi");
  const popupGone = page.waitForURL(/8711/);
  await page.click("#external-form button");
  await popupGone;
  assert.ok(site.received.partner.length, "partner got the form");
  assert.equal(site.received.partner[0].fields.neurosoc_session, undefined, "session id never leaves for another origin");

  await page.goto(site.url + "/");
  await sdkReady(page);
  await page.fill("#search-form input", "a@b.co");
  await page.click("#search-form button");
  await page.waitForURL(/email=/);
  assert.ok(!page.url().includes("neurosoc_session"), "GET form URL stays clean");
  await close();
});

test("native multi-page login form is tagged so the backend can look up the verdict", async () => {
  const { page, close } = await open("/legacy");
  await sdkReady(page);
  const session = await sessionOf(page);
  await page.fill("#u", "maya");
  await Promise.all([page.waitForNavigation(), page.click("#login-form button")]);
  assert.equal(site.received.logins[0].neurosoc_session, session);
  await close();
});

test("tagForms can be disabled from the tag", async () => {
  const { page, close } = await open("/?notag=1");
  await sdkReady(page);
  await page.fill("#handle", "x"); await page.fill("#why", "y");
  await page.click("#signup-form button");
  await until(() => site.received.signups.length);
  assert.equal(site.received.signups[0].neurosoc_session, undefined);
  await close();
});

// ── navigation ─────────────────────────────────────────────────────────────
test("multi-page site: one session across pages, session.start once, a page.view per page", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  const session = await sessionOf(page);
  const visitor = await page.evaluate(() => localStorage.getItem("nsoc_vid"));
  await page.click("nav a[href='/legacy']"); await page.waitForURL(/legacy$/); await sdkReady(page);
  await page.click("nav a[href='/legacy2']"); await page.waitForURL(/legacy2$/); await sdkReady(page);
  assert.equal(await sessionOf(page), session);
  await flush(page);
  await until(() => eventsOf(session, "page.view").length >= 3, { label: "three page views" });
  assert.deepEqual(eventsOf(session, "page.view").map((e) => e.resource.id), ["/", "/legacy", "/legacy2"]);
  assert.equal(eventsOf(session, "session.start").length, 1, "session.start only on the first page");
  assert.ok(new Set(api.events().map((e) => e.entity.id)).size === 1 && api.events()[0].entity.id === visitor, "same anonymous visitor throughout");
  await close();
});

test("single-page app: pushState, back button and hash routes each count once", async () => {
  const { page, close } = await open("/app/markets");
  await sdkReady(page);
  await until(() => eventsOf(null, "page.view").length === 1);
  await page.click("a[href='/app/portfolio']");
  await page.click("a[href='#/settings']");
  await page.goBack();
  await page.goBack();
  await flush(page);
  await until(() => eventsOf(null, "page.view").length >= 5, { label: "5 views" });
  assert.deepEqual(eventsOf(null, "page.view").map((e) => e.resource.id),
    ["/app/markets", "/app/portfolio", "/app/portfolio#/settings", "/app/portfolio", "/app/markets"]);
  await page.evaluate(() => { history.replaceState({}, "", location.pathname); history.pushState({}, "", location.pathname); });
  await wait(300); await flush(page);
  assert.equal(eventsOf(null, "page.view").length, 5, "the same route again is not a new view");
  await close();
});

test("two tabs: separate sessions, same visitor", async () => {
  const a = await open("/");
  await sdkReady(a.page);
  const b = await a.context.newPage();
  await b.goto(site.url + "/");
  await sdkReady(b);
  assert.notEqual(await sessionOf(a.page), await sessionOf(b));
  assert.equal(await a.page.evaluate(() => localStorage.getItem("nsoc_vid")), await b.evaluate(() => localStorage.getItem("nsoc_vid")));
  await a.close();
});

// ── identity and wallets ───────────────────────────────────────────────────
test("identify() sets the entity; bad input is ignored; reset() starts a fresh session", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  const before = await sessionOf(page);
  await page.evaluate(() => { window.neurosoc.identify({ id: "user_42", type: "human" }); window.neurosoc.identify({ id: "" }); window.neurosoc.identify({}); });
  await page.evaluate(() => window.neurosoc.track({ action: "form.submit", resource: { id: "f", type: "form" } }));
  await flush(page);
  assert.equal(eventsOf(before, "form.submit")[0].entity.id, "user_42");
  await page.evaluate(() => window.neurosoc.reset());
  const after = await sessionOf(page);
  assert.notEqual(after, before);
  await until(() => eventsOf(after, "session.start").length, { label: "session.start after reset" });
  assert.notEqual(eventsOf(after, "session.start")[0].entity.id, "user_42", "signed-out entity is anonymous again");
  await close();
});

test("track() sanitizes input: unknown context keys, oversized values and bad amounts cannot poison an event", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  await page.evaluate(() => window.neurosoc.track({
    action: "token.buy", resource: { id: "x".repeat(400), type: "token" },
    value: { amount: 5, asset: "A".repeat(80) }, context: { geo: "US", secret_extra: "nope", wallet: "w" } }));
  await page.evaluate(() => window.neurosoc.track({ action: "token.sell", resource: { id: "r", type: "token" }, value: { amount: -3 } }));
  await page.evaluate(() => window.neurosoc.track({ action: "", resource: {} }));
  await flush(page);
  const buy = eventsOf(null, "token.buy")[0];
  assert.equal(buy.resource.id.length, 256);
  assert.equal(buy.value.asset.length, 32);
  assert.equal(buy.context.geo, "US");
  assert.equal(buy.context.secret_extra, undefined);
  assert.equal(eventsOf(null, "token.sell")[0].value, undefined, "negative amount dropped, event kept");
  assert.equal(api.events().filter((e) => !e.action).length, 0);
  await close();
});

const evmProvider = (initial) => ({ init: (initial) => {
  const handlers = {};
  window.__evm = {
    accounts: initial,
    on(event, fn) { (handlers[event] ||= []).push(fn); },
    removeListener(event, fn) { handlers[event] = (handlers[event] || []).filter((f) => f !== fn); },
    async request({ method }) {
      if (method === "eth_accounts") return window.__evm.accounts;
      if (method === "eth_requestAccounts") { window.__evm.accounts = ["0xAbC0000000000000000000000000000000000001"]; (handlers.accountsChanged || []).forEach((f) => f(window.__evm.accounts)); return window.__evm.accounts; }
      throw new Error("unsupported " + method);
    },
    emit(event, ...args) { (handlers[event] || []).forEach((f) => f(...args)); },
    handlerCount: () => Object.values(handlers).flat().length,
  };
  window.ethereum = window.__evm;
}, initArg: initial });

test("EVM wallet: connecting reports wallet.connect with the lowercased address and becomes the entity", async () => {
  const { page, close } = await open("/", evmProvider([]));
  await sdkReady(page);
  await page.click("#connect-wallet");
  await until(() => eventsOf(null, "wallet.connect").some((e) => e.context.wallet), { label: "wallet.connect with wallet" });
  const event = eventsOf(null, "wallet.connect").find((e) => e.context.wallet);
  assert.equal(event.context.wallet, "0xabc0000000000000000000000000000000000001");
  await page.evaluate(() => window.neurosoc.track({ action: "form.submit", resource: { id: "f", type: "form" } }));
  await flush(page);
  assert.equal(eventsOf(null, "form.submit")[0].entity.id, "0xabc0000000000000000000000000000000000001", "anonymous visitor became the wallet");
  await close();
});

test("EVM wallet already authorised earlier is detected on load without any prompt", async () => {
  const { page, close } = await open("/", evmProvider(["0xDeaDbeef00000000000000000000000000000002"]));
  await sdkReady(page);
  await until(() => eventsOf(null, "wallet.connect").length, { label: "wallet.connect from eth_accounts" });
  assert.equal(eventsOf(null, "wallet.connect")[0].context.wallet, "0xdeadbeef00000000000000000000000000000002");
  const calls = await page.evaluate(() => window.__evm.accounts.length);
  assert.equal(calls, 1);
  await close();
});

test("wallet disconnect clears the wallet; destroy() removes the provider listeners", async () => {
  const { page, close } = await open("/", evmProvider(["0xDeaDbeef00000000000000000000000000000002"]));
  await sdkReady(page);
  await until(() => eventsOf(null, "wallet.connect").length);
  await page.evaluate(() => window.__evm.emit("accountsChanged", []));
  await page.evaluate(() => window.neurosoc.track({ action: "form.submit", resource: { id: "f", type: "form" } }));
  await flush(page);
  assert.equal(eventsOf(null, "form.submit")[0].context.wallet, undefined);
  assert.equal(eventsOf(null, "form.submit")[0].entity.id.startsWith("vis_"), true, "entity falls back to the visitor");
  assert.ok(await page.evaluate(() => window.__evm.handlerCount()) > 0);
  await page.evaluate(() => window.neurosoc.destroy());
  assert.equal(await page.evaluate(() => window.__evm.handlerCount()), 0);
  await close();
});

test("Solana (Phantom-style) wallet connect event, and a provider injected after load", async () => {
  const { page, close } = await open("/", { init: () => {
    setTimeout(() => {
      const handlers = {};
      window.solana = { isPhantom: true, publicKey: null, on(e, f) { (handlers[e] ||= []).push(f); }, removeListener() {}, emit(e, ...a) { (handlers[e] || []).forEach((f) => f(...a)); } };
    }, 700);
  } });
  await sdkReady(page);
  await page.waitForFunction(() => window.solana, null, { timeout: 4000 });
  await wait(1700); // the SDK rescans after load (500ms / 1.5s / 4s)
  await page.evaluate(() => window.solana.emit("connect", { toString: () => "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU" }));
  await until(() => eventsOf(null, "wallet.connect").some((e) => e.context.wallet), { label: "solana connect" });
  assert.equal(eventsOf(null, "wallet.connect").find((e) => e.context.wallet).context.wallet, "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU");
  await close();
});

test("EIP-6963 announced wallets are picked up", async () => {
  const { page, close } = await open("/", { init: () => {
    const provider = { on() {}, removeListener() {}, request: async ({ method }) => (method === "eth_accounts" ? ["0xEip6963000000000000000000000000000000003"] : []) };
    window.addEventListener("eip6963:requestProvider", () => window.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail: { info: { name: "t" }, provider } })));
  } });
  await sdkReady(page);
  await until(() => eventsOf(null, "wallet.connect").length, { label: "EIP-6963 wallet" });
  assert.equal(eventsOf(null, "wallet.connect")[0].context.wallet, "0xeip6963000000000000000000000000000000003");
  await close();
});

// ── delivery under bad conditions ──────────────────────────────────────────
test("server errors: events are retried with backoff and delivered exactly once", async () => {
  api.state.behavior = "flaky";
  api.state.failuresLeft = 2;
  const { page, close } = await open("/");
  await sdkReady(page);
  await until(() => eventsOf(null, "session.start").length, { timeout: 12000, label: "delivery after retries" });
  const ids = api.events().map((e) => e.event_id);
  assert.equal(new Set(ids).size, ids.length, "no duplicate delivery");
  await close();
});

test("guard() resolves null (never hangs, never throws) when the API is down, slow, or dropping connections", async () => {
  const { page, close } = await open("/?nosdk=1");
  await manualInit(page, { timeoutMs: 700, flushIntervalMs: 50 });
  const guard = () => page.evaluate(async () => { const t = Date.now(); const v = await window.neurosoc.guard({ action: "reward.claim", resource: { id: "c", type: "campaign" } }); return { v, ms: Date.now() - t }; });
  for (const behavior of ["fail500", "drop", "slow"]) {
    api.state.behavior = behavior === "slow" ? "ok" : behavior;
    api.state.delayMs = behavior === "slow" ? 3000 : 0;
    const result = await guard();
    assert.equal(result.v, null, `${behavior}: null verdict`);
    assert.ok(result.ms < 4500, `${behavior}: gave up in ${result.ms}ms`);
  }
  api.reset();
  const ok = await guard();
  assert.equal(ok.v.action, "allow", "recovers when the API is back");
  await close();
});

test("a rejected key warns once, loudly, and stops hammering the API", async () => {
  api.state.behavior = "fail401";
  const logs = [];
  const { page, close } = await open("/?nosdk=1");
  page.on("console", (m) => logs.push(m.text()));
  await manualInit(page, { timeoutMs: 500, flushIntervalMs: 50 });
  for (let i = 0; i < 6; i += 1) { await page.evaluate(() => window.neurosoc.guard({ action: "form.submit", resource: { id: "f", type: "form" } })); }
  assert.equal(logs.filter((t) => /rejected/.test(t)).length, 1, "one warning");
  const hits = api.state.requests.length;
  assert.equal(hits, 0, "401 bodies are not recorded as accepted");
  await close();
});

test("one invalid event in a batch only loses itself", async () => {
  const { page, close } = await open("/?nosdk=1");
  await manualInit(page, { flushIntervalMs: 60_000 });
  await page.evaluate(() => {
    const soc = window.neurosoc;
    soc.track({ action: "form.submit", resource: { id: "a", type: "form" } });
    soc.track({ action: "not.in.taxonomy", resource: { id: "b", type: "form" } });
    soc.track({ action: "form.submit", resource: { id: "c", type: "form" } });
  });
  await flush(page);
  await until(() => eventsOf(null, "form.submit").length === 2, { label: "valid events survive a 422 batch" });
  assert.deepEqual(eventsOf(null, "form.submit").map((e) => e.resource.id).sort(), ["a", "c"]);
  await close();
});

test("offline: events queue and are delivered when the connection returns", async () => {
  const { page, context, close } = await open("/?nosdk=1");
  await manualInit(page, { flushIntervalMs: 100, timeoutMs: 800 });
  await until(() => eventsOf(null, "session.start").length, { label: "online start" });
  await context.setOffline(true);
  await page.evaluate(() => { window.neurosoc.track({ action: "form.submit", resource: { id: "offline-1", type: "form" } }); });
  await wait(1500);
  assert.equal(eventsOf(null, "form.submit").length, 0);
  await context.setOffline(false);
  await until(() => eventsOf(null, "form.submit").length === 1, { timeout: 9000, label: "delivery after reconnect" });
  await close();
});

test("closing the tab delivers what is still queued (sendBeacon)", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  await until(() => eventsOf(null, "session.start").length);
  await page.evaluate(() => { window.neurosoc.track({ action: "form.submit", resource: { id: "last-words", type: "form" } }); });
  assert.equal(eventsOf(null, "form.submit").length, 0, "still queued (2s flush interval)");
  await page.goto("about:blank");
  await until(() => eventsOf(null, "form.submit").length === 1, { label: "beacon delivery" });
  await close();
});

test("many heavy events at page close are split into beacon-sized chunks, none lost", async () => {
  const { page, close } = await open("/?nosdk=1");
  await manualInit(page, { flushIntervalMs: 60_000, maxBatch: 50 });
  await page.evaluate(async () => {
    for (let i = 0; i < 4000; i += 1) document.dispatchEvent(new MouseEvent("mousemove", { clientX: i % 900, clientY: i % 700, bubbles: true }));
    for (let i = 0; i < 5; i += 1) window.neurosoc.track({ action: "task.complete", resource: { id: "heavy-" + i, type: "campaign" } });
  });
  await page.goto("about:blank");
  await until(() => eventsOf(null, "task.complete").length === 5, { label: "all heavy events delivered" });
  await close();
});

test("the timing window is bounded: a long session never produces a huge payload", async () => {
  const { page, close } = await open("/");
  await sdkReady(page);
  await page.evaluate(() => { for (let i = 0; i < 3000; i += 1) document.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true })); });
  await page.evaluate(() => window.neurosoc.guard({ action: "reward.claim", resource: { id: "c", type: "campaign" } }));
  const claim = eventsOf(null, "reward.claim")[0];
  assert.ok(claim.telemetry.events.length <= 600);
  assert.ok(claim.telemetry.event_count > 600, "count still reflects everything seen");
  await close();
});

// ── lifecycle and environments ─────────────────────────────────────────────
test("destroy() removes every listener and restores history; a second init returns the same client", async () => {
  const { page, close } = await open("/app/markets");
  await sdkReady(page);
  const same = await page.evaluate(() => window.NeuroSOC.init({ publishableKey: "pk_test_dummy", endpoint: "http://x" }) === window.neurosoc);
  assert.equal(same, true);
  const nativeBefore = await page.evaluate(() => history.pushState.toString().includes("[native code]"));
  assert.equal(nativeBefore, false, "pushState is wrapped while running");
  await page.evaluate(() => window.neurosoc.destroy());
  assert.equal(await page.evaluate(() => history.pushState.toString().includes("[native code]")), true, "pushState restored");
  api.state.requests.length = 0;
  await page.click("a[href='/app/portfolio']");
  await page.keyboard.type("abc");
  await page.evaluate(() => window.neurosoc.track({ action: "form.submit", resource: { id: "f", type: "form" } }));
  await wait(2500);
  assert.equal(api.events().length, 0, "silent after destroy");
  await close();
});

test("works under a strict Content Security Policy (no eval, no inline script, one API host)", async () => {
  const { page, problems, close } = await open("/?csp=1");
  await sdkReady(page);
  await page.click("[data-task=follow]");
  await flush(page);
  await until(() => eventsOf(null, "task.complete").length, { label: "events under CSP" });
  assert.deepEqual(problems, []);
  await close();
});

test("an unreachable endpoint never breaks the host page", async () => {
  const { page, problems, close } = await open("/?endpoint=" + encodeURIComponent("http://127.0.0.1:9"));
  await sdkReady(page);
  await page.fill("#handle", "x"); await page.fill("#why", "y");
  await page.click("#signup-form button");
  await page.click("#connect-wallet");
  for (const task of ["follow", "discord", "try"]) await page.click(`[data-task=${task}]`);
  await page.click("#claim");
  await until(() => page.evaluate(() => window.__lastVerdict === null), { label: "claim finished with a null verdict" });
  assert.equal(await page.isVisible("#result.paid"), true, "the site decides; unreachable NeuroSOC means no verdict, not a crash");
  assert.ok(!problems.some((p) => p.startsWith("pageerror")), problems.join("\n"));
  await close();
});

test("touch devices: taps are captured and rules still match", async () => {
  const { page, close } = await open("/", { context: { hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } } });
  await sdkReady(page);
  await page.tap("[data-task=follow]");
  await page.tap("[data-task=discord]");
  await page.evaluate(() => window.neurosoc.guard({ action: "reward.claim", resource: { id: "c", type: "campaign" } }));
  const types = new Set(eventsOf(null, "reward.claim")[0].telemetry.events.map((t) => t.type));
  assert.ok(types.has("touchstart"), `touch captured (${[...types]})`);
  assert.equal(eventsOf(null, "task.complete").length, 2);
  await close();
});

test("verdict listeners get every verdict; a throwing listener does not stop the others", async () => {
  api.state.verdictFor = (e) => (e.action === "reward.claim" ? "shadow" : "allow");
  const { page, problems, close } = await open("/");
  await sdkReady(page);
  await page.evaluate(() => {
    window.__seen = [];
    window.neurosoc.onVerdict(() => { throw new Error("bad listener"); });
    window.neurosoc.onVerdict((v) => window.__seen.push(v.action));
  });
  const verdict = await page.evaluate(() => window.neurosoc.guard({ action: "reward.claim", resource: { id: "c", type: "campaign" } }));
  assert.equal(verdict.action, "shadow");
  assert.ok((await page.evaluate(() => window.__seen)).includes("shadow"));
  assert.ok(!problems.some((p) => p.startsWith("pageerror")));
  await close();
});

test("importing the package on the server is safe: init returns an inert client", async () => {
  const { NeuroSOC } = await import("../dist/index.mjs");
  const soc = NeuroSOC.init({ publishableKey: "pk_test", endpoint: "https://api.example" });
  assert.equal(await soc.track({ action: "page.view", resource: { id: "/", type: "page" } }), null);
  assert.equal(await soc.guard({ action: "reward.claim", resource: { id: "c", type: "campaign" } }), null);
  soc.identify({ id: "u" }); soc.consent(false); soc.destroy();
  assert.throws(() => NeuroSOC.init({ publishableKey: "sk_live_x", endpoint: "https://api.example" }), /publishable key/);
});
