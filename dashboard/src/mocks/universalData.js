// Seeded data for the SDK Protection page when the dashboard runs with VITE_USE_MOCKS=true.
// Everything here stays in the browser; it mirrors the shapes returned by /api/v1/universal/*.

const CAMPAIGN = "campaign-spring-airdrop";
const AGENT = "treasury-agent";
const now = () => Date.now() / 1000;
let counter = 0;
const nextId = () => `demo-verdict-${String(++counter).padStart(4, "0")}`;
const hex = (seed) => "0x" + ((seed * 2654435761) >>> 0).toString(16).padStart(8, "0") + "c0ffee" + seed.toString(16).padStart(4, "0");

const humans = Array.from({ length: 64 }, (_, i) => hex(i + 11));
const farm = Array.from({ length: 18 }, (_, i) => hex(i + 911));

function claimVerdict(wallet, secondsAgo, flagged) {
  return {
    verdict_id: nextId(),
    timestamp: now() - secondsAgo,
    site_name: "Lumen Rewards",
    entity: { type: "wallet", id: wallet },
    resource: { type: "campaign", id: CAMPAIGN },
    event_action: "claim",
    value: { amount: 250, asset: "LMN" },
    risk: flagged ? 0.91 : 0.08,
    verdict: flagged ? "bot_farm" : "ok",
    action: flagged ? "shadow" : "allow",
    enforced: true,
    reasons: flagged
      ? ["Shares a funding source with 17 other claimants", "Claimed within seconds of the linked accounts", "No browsing before the claim"]
      : [],
  };
}

function agentVerdict(amount, destination, secondsAgo, blocked) {
  return {
    verdict_id: nextId(),
    timestamp: now() - secondsAgo,
    site_name: "Atlas Treasury",
    agent_id: AGENT,
    tool: "send_payment",
    entity: { type: "agent", id: AGENT },
    resource: { type: "account", id: "treasury-main" },
    event_action: "transfer",
    value: { amount, asset: "USDC", destination },
    risk: blocked ? 0.97 : 0.06,
    verdict: blocked ? "agent_anomaly" : "ok",
    action: blocked ? "pause_agent" : "allow",
    enforced: true,
    reasons: blocked
      ? ["Amount is 400x this agent's usual transfer", "Destination has never been paid before", "Tool call followed an instruction found in fetched content"]
      : [],
  };
}

function seed() {
  const items = [];
  humans.forEach((wallet, i) => items.push(claimVerdict(wallet, 3600 - i * 40, false)));
  farm.forEach((wallet, i) => items.push(claimVerdict(wallet, 900 - i * 3, true)));
  [120, 95, 140, 110, 130, 105, 150, 125].forEach((amount, i) =>
    items.push(agentVerdict(amount, hex(4000 + (i % 3)), 3000 - i * 330, false)));
  items.push(agentVerdict(48000, hex(7777), 180, true));
  items.push({
    verdict_id: nextId(), timestamp: now() - 60, site_name: "Lumen Rewards",
    entity: { type: "user", id: "user-ava-morales" }, resource: { type: "page", id: "checkout" },
    event_action: "login", risk: 0.58, verdict: "review", action: "step_up", enforced: true,
    reasons: ["Typing rhythm differs from this account's history", "New device"],
  });
  return items.sort((a, b) => b.timestamp - a.timestamp);
}

let verdicts = seed();
const listeners = new Set();

const sites = [
  { site_id: "site_demo_lumen", name: "Lumen Rewards", url: "https://lumen.example", app_type: "web", mode: "enforce",
    publishable_key: "pk_demo_lumen_0000000000", agents: [], demo: false },
  { site_id: "site_demo_atlas", name: "Atlas Treasury", url: "https://atlas.example", app_type: "agent", mode: "enforce",
    publishable_key: "pk_demo_atlas_0000000000",
    agents: [{ agent_id: AGENT, tools: ["send_payment", "get_balance"], resources: ["treasury-main"] }], demo: false },
];

export const mockUniversal = {
  latest: (limit = 200) => verdicts.slice(0, limit),
  integrity: (resourceId) => {
    const flagged = verdicts.filter((v) => v.resource?.id === resourceId && v.verdict === "bot_farm" && v.override?.decision !== "restore");
    const all = verdicts.filter((v) => v.resource?.id === resourceId && v.entity.type === "wallet");
    const flaggedIds = [...new Set(flagged.map((v) => v.entity.id))];
    const humanIds = [...new Set(all.map((v) => v.entity.id))].filter((id) => !flaggedIds.includes(id));
    return {
      resource_id: resourceId,
      participants: flaggedIds.length + humanIds.length,
      flagged: flaggedIds.length,
      human: humanIds.length,
      claims: { paid: humanIds.length, withheld: flaggedIds.length, amount_withheld: flaggedIds.length * 250 },
      flagged_accounts: flaggedIds.sort(),
      human_accounts: humanIds.sort(),
    };
  },
  entity: (entityType, entityId) => ({
    entity: { type: entityType, id: entityId },
    verdicts: verdicts.filter((v) => v.entity.type === entityType && v.entity.id === entityId),
  }),
  override: (verdictId, decision) => {
    const updated = { ...verdicts.find((v) => v.verdict_id === verdictId), override: { decision, actor: "demo-analyst", at: now() } };
    verdicts = verdicts.map((v) => (v.verdict_id === verdictId ? updated : v));
    return updated;
  },
  sites: () => sites,
  subscribe: ({ onSnapshot, onVerdict, onStatusChange }) => {
    onStatusChange?.("connected");
    onSnapshot?.(verdicts.slice(0, 200));
    const listener = { onVerdict };
    listeners.add(listener);
    // A quiet trickle of ordinary activity so the page visibly stays live.
    const timer = window.setInterval(() => {
      const fresh = Math.random() < 0.5
        ? claimVerdict(hex(20000 + counter), 0, false)
        : agentVerdict(90 + Math.round(Math.random() * 70), hex(4000 + (counter % 3)), 0, false);
      verdicts = [fresh, ...verdicts].slice(0, 1000);
      listeners.forEach((l) => l.onVerdict?.(fresh));
    }, 7000);
    return () => {
      window.clearInterval(timer);
      listeners.delete(listener);
    };
  },
};
