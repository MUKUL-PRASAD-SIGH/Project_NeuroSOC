// A controllable stand-in for the NeuroSOC API, for browser tests that need failures the real
// engine will not produce on demand (slow, 5xx, 401, a poisoned batch, connection drops).
import { createServer } from "node:http";

export const PRESET_RULES = [
  { match: { url: "*", event: "click", selector: "#connect-wallet" }, action: "wallet.connect", resource: { type: "campaign", id_from: "attr:data-campaign" } },
  { match: { url: "*", event: "click", selector: "[data-task]" }, action: "task.complete", resource: { type: "campaign", id_from: "attr:data-campaign" } },
  { match: { url: "*", event: "submit", selector: "#signup-form" }, action: "account.create", resource: { type: "site", id_from: "const:orbit" } },
  { match: { url: "/app*", event: "click", text: ["buy", "swap"] }, action: "token.buy", resource: { type: "token", id_from: "attr:data-token", sensitivity: "high" }, value_from: "attr:data-amount" },
  { match: { url: "*", event: "click", selector: "#claim" }, action: "reward.claim", resource: { type: "campaign", id_from: "attr:data-campaign", sensitivity: "medium" }, value_from: "attr:data-reward" },
];
const ACTIONS = new Set(["session.start", "page.view", "wallet.connect", "task.complete", "account.create", "token.buy", "reward.claim",
  "campaign.join", "auth.login", "form.submit", "token.sell", "token.transfer", "referral.create"]);

export function startFakeApi(port = 8700) {
  const state = {
    allowedOrigins: null, // null = any origin
    mode: "enforce",
    rules: PRESET_RULES,
    behavior: "ok", // ok | slow | fail500 | fail401 | drop | flaky
    delayMs: 0,
    configDelayMs: 0,
    failuresLeft: 0,
    verdictFor: (event) => (event.action === "reward.claim" ? "allow" : "allow"),
    requests: [], // every POST to /events: { url, headers, origin, events, at }
    configHits: 0,
    beacons: 0,
  };
  const server = createServer((req, res) => {
    const origin = req.headers.origin;
    const cors = { "Access-Control-Allow-Origin": origin || "*", Vary: "Origin" };
    const url = new URL(req.url, "http://x");
    if (req.method === "OPTIONS") {
      res.writeHead(204, { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "content-type, x-neurosoc-key" });
      state.preflights = (state.preflights ?? 0) + 1;
      return res.end();
    }
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", async () => {
      const send = (status, body) => { res.writeHead(status, { ...cors, "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
      if (state.behavior === "drop") return req.socket.destroy();
      if (state.delayMs) await new Promise((r) => setTimeout(r, state.delayMs));
      if (state.allowedOrigins && !state.allowedOrigins.includes(origin)) return send(403, { detail: "origin" });
      if (state.behavior === "fail401") return send(401, { detail: "key" });
      if (state.failuresLeft > 0 && state.behavior === "flaky") { state.failuresLeft -= 1; return send(503, { detail: "flaky" }); }
      if (state.behavior === "fail500") return send(500, { detail: "boom" });
      if (url.pathname === "/api/v1/sdk/config") { state.configHits += 1; if (state.configDelayMs) await new Promise((r) => setTimeout(r, state.configDelayMs)); return send(200, { site_id: "dummy", mode: state.mode, rules: state.rules }); }
      if (url.pathname === "/api/v1/sdk/events") {
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { return send(422, { detail: "json" }); }
        const bad = body.events.some((e) => !ACTIONS.has(e.action));
        if (bad) return send(422, { detail: "action" });
        state.requests.push({ url: req.url, contentType: req.headers["content-type"], origin, events: body.events, at: Date.now() });
        return send(200, { mode: state.mode, verdicts: body.events.map((e) => ({ verdict_id: "v_" + e.event_id, session_id: e.session_id, event_id: e.event_id, action: state.verdictFor(e), enforced: state.mode === "enforce" })) });
      }
      send(404, { detail: "nope" });
    });
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve({
    state, url: `http://127.0.0.1:${port}`,
    events: () => state.requests.flatMap((r) => r.events),
    reset() { state.requests = []; state.behavior = "ok"; state.delayMs = 0; state.configDelayMs = 0; state.failuresLeft = 0; state.configHits = 0; state.allowedOrigins = null; state.verdictFor = () => "allow"; state.rules = PRESET_RULES; },
    close: () => new Promise((r) => { server.closeAllConnections?.(); server.close(r); }),
  })));
}
