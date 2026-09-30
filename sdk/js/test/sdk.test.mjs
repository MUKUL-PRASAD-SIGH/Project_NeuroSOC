// Runs the built ES module inside jsdom with a fake NeuroSOC endpoint.
import { test } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { JSDOM } from "jsdom";

const PAGE = `<!doctype html><html><body>
  <main data-campaign="campaign-7" data-reward="25">
    <button id="connect-wallet">Connect wallet</button>
    <button data-task="follow">Follow</button>
    <form id="profile-form"><input name="handle"><button type="submit">Save</button></form>
    <button id="claim">Claim reward</button>
    <div class="card">A long marketing card that mentions buy somewhere in a sentence of text</div>
  </main></body></html>`;

function setup({ rules, verdictAction = "allow" } = {}) {
  const dom = new JSDOM(PAGE, { url: "https://launchpad.example/campaigns/campaign-7", pretendToBeVisual: true });
  const sent = [];
  const g = globalThis;
  for (const key of ["window", "document", "location", "history", "navigator", "screen", "HTMLElement",
    "HTMLFormElement", "HTMLInputElement", "HTMLScriptElement", "Element", "Event", "CSS", "Blob", "TextEncoder"]) {
    Object.defineProperty(g, key, { value: dom.window[key] ?? g[key], configurable: true, writable: true });
  }
  Object.defineProperty(g, "crypto", { value: webcrypto, configurable: true });
  Object.defineProperty(g, "CSS", { value: { escape: (s) => s }, configurable: true, writable: true });
  dom.window.sessionStorage.clear();
  g.fetch = async (url, init = {}) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/config")) {
      return { ok: true, json: async () => ({ site_id: "s", mode: "enforce", rules }) };
    }
    const body = JSON.parse(init.body);
    sent.push({ url, init, events: body.events });
    return {
      ok: true,
      json: async () => ({ verdicts: body.events.map((e) => ({ verdict_id: "v-" + e.event_id, session_id: e.session_id,
        event_id: e.event_id, action: e.action === "reward.claim" ? verdictAction : "allow", enforced: true })) }),
    };
  };
  return { dom, sent };
}

const tick = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));
const preset = JSON.parse(await (await import("node:fs/promises")).readFile(
  new URL("../../presets/rewards-campaign.json", import.meta.url), "utf8")).rules;

test("script-tag style init sends session.start and page.view without preflight headers", async () => {
  const { sent } = setup({ rules: preset });
  const { NeuroSOC } = await import(`../dist/index.mjs?${Math.random()}`);
  const soc = NeuroSOC.init({ publishableKey: "pk_test", endpoint: "https://api.example", flushIntervalMs: 5 });
  await tick(60);
  await soc.flush();
  const actions = sent.flatMap((s) => s.events.map((e) => e.action));
  assert.ok(actions.includes("session.start"));
  assert.ok(actions.includes("page.view"));
  const request = sent[0];
  assert.match(request.url, /\/api\/v1\/sdk\/events\?key=pk_test$/);
  assert.equal(request.init.headers["Content-Type"], "text/plain;charset=UTF-8");
  assert.equal(request.init.credentials, "omit");
});

test("rules map clicks and submits to actions with resource and value from the page", async () => {
  const { dom, sent } = setup({ rules: preset, verdictAction: "shadow" });
  const { NeuroSOC } = await import(`../dist/index.mjs?${Math.random()}`);
  const soc = NeuroSOC.init({ publishableKey: "pk_test", endpoint: "https://api.example", flushIntervalMs: 5 });
  const verdicts = [];
  soc.onVerdict((v) => verdicts.push(v.action));
  await tick(60);
  const doc = dom.window.document;
  doc.querySelector("[data-task]").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  doc.querySelector("#profile-form").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
  doc.querySelector("#claim").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await tick(80);
  await soc.flush();
  const events = sent.flatMap((s) => s.events);
  const claim = events.find((e) => e.action === "reward.claim");
  assert.ok(events.find((e) => e.action === "task.complete"));
  assert.ok(events.find((e) => e.action === "campaign.join"));
  assert.ok(claim, "claim tracked");
  assert.deepEqual(claim.resource, { id: "campaign-7", type: "campaign", sensitivity: "medium" });
  assert.deepEqual(claim.value, { amount: 25 });
  assert.ok(Array.isArray(claim.telemetry.events), "interactive actions carry the timing window");
  assert.ok(verdicts.includes("shadow"));
  assert.equal(doc.querySelector("input[name=neurosoc_session]").value, soc.sessionId, "forms are tagged");
});

test("typed characters never leave the page, only key classes", async () => {
  const { dom, sent } = setup({ rules: preset });
  const { NeuroSOC } = await import(`../dist/index.mjs?${Math.random()}`);
  const soc = NeuroSOC.init({ publishableKey: "pk_test", endpoint: "https://api.example", flushIntervalMs: 5 });
  await tick(40);
  const input = dom.window.document.querySelector("input[name=handle]");
  for (const key of ["s", "e", "c", "r", "e", "t", " ", "Backspace"]) {
    input.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key, bubbles: true }));
    input.dispatchEvent(new dom.window.KeyboardEvent("keyup", { key, bubbles: true }));
  }
  await soc.guard({ action: "form.submit", resource: { id: "profile", type: "form" } });
  const payload = JSON.stringify(sent.flatMap((s) => s.events));
  assert.ok(!/"key":"[a-z]"/.test(payload), "no raw characters");
  const keys = new Set(sent.flatMap((s) => s.events).flatMap((e) => e.telemetry?.events ?? []).map((t) => t.key).filter(Boolean));
  assert.deepEqual([...keys].sort(), ["backspace", "char", "space"]);
});

test("consent(false) stops all tracking", async () => {
  const { sent } = setup({ rules: preset });
  const { NeuroSOC } = await import(`../dist/index.mjs?${Math.random()}`);
  const soc = NeuroSOC.init({ publishableKey: "pk_test", endpoint: "https://api.example", waitForConsent: true });
  const result = await soc.track({ action: "page.view", resource: { id: "/", type: "page" } });
  assert.equal(result, null);
  await tick(40);
  assert.equal(sent.length, 0);
});

test("text rules ignore long blocks that merely mention the word", async () => {
  const { dom, sent } = setup({ rules: [{ match: { event: "click", text: ["buy"] }, action: "token.buy",
    resource: { type: "token", id_from: "url:path" } }] });
  const { NeuroSOC } = await import(`../dist/index.mjs?${Math.random()}`);
  const soc = NeuroSOC.init({ publishableKey: "pk_test", endpoint: "https://api.example", flushIntervalMs: 5 });
  await tick(40);
  dom.window.document.querySelector(".card").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await tick(40);
  await soc.flush();
  assert.ok(!sent.flatMap((s) => s.events).some((e) => e.action === "token.buy"));
});

test("init rejects secret keys in the browser", async () => {
  setup({ rules: [] });
  const { NeuroSOC } = await import(`../dist/index.mjs?${Math.random()}`);
  assert.throws(() => NeuroSOC.init({ publishableKey: "sk_live_oops", endpoint: "https://api.example" }), /publishable key/);
});
