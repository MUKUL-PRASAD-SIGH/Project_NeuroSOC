// Small, dependency-free helpers for the demo's browser state.
const SESSION_KEY = "novatrust_demo_session";
const CONSENT_KEY = "novatrust_telemetry_consent";
export const SITE_KEY = "novatrust_demo_site";

function randomId() {
  const bytes = new Uint8Array(12);
  (globalThis.crypto || window.crypto).getRandomValues(bytes);
  return "demo-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// One id per browser tab: it keys the fake account on the server, so reloading keeps your balance.
export function getDemoSession() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = randomId();
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

// true = accepted, false = declined, null = not asked yet.
export function readConsent() {
  const value = localStorage.getItem(CONSENT_KEY);
  return value === null ? null : value === "true";
}

export function writeConsent(granted) {
  localStorage.setItem(CONSENT_KEY, granted ? "true" : "false");
}

export function clearConsent() {
  localStorage.removeItem(CONSENT_KEY);
}

// The application the dashboard wizard created for this demo: {site_id, publishable_key}. The publishable key
// is meant for browsers; the secret key never comes here (it stays on the server).
export function readSite() {
  try {
    const site = JSON.parse(localStorage.getItem(SITE_KEY) || "null");
    return site && /^pk_/.test(site.publishable_key || "") ? site : null;
  } catch {
    return null;
  }
}

export function writeSite(site) {
  if (site && /^pk_/.test(site.publishable_key || "")) {
    localStorage.setItem(SITE_KEY, JSON.stringify({ site_id: site.site_id, publishable_key: site.publishable_key }));
  }
}

export const money = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value) || 0);
