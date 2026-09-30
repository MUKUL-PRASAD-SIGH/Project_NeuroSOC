// Session and device identifiers. Storage can be blocked (private windows, strict settings),
// so every access is guarded and falls back to an in-memory value.

function randomId(prefix: string): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return prefix + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function stored(storage: () => Storage, key: string, make: () => string): string {
  try {
    const existing = storage().getItem(key);
    if (existing) return existing;
    const value = make();
    storage().setItem(key, value);
    return value;
  } catch {
    return make();
  }
}

/** One id per browser tab session; the site's backend uses it to ask for the verdict. */
export function sessionId(): string {
  return stored(() => window.sessionStorage, "nsoc_sid", () => randomId("ses_"));
}

/** A stable anonymous visitor id, used as the entity until identify() or a wallet says who it is. */
export function visitorId(): string {
  return stored(() => window.localStorage, "nsoc_vid", () => randomId("vis_"));
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

/**
 * A coarse device fingerprint from stable, non-identifying properties, hashed in the page.
 * It links accounts that come from one machine (a bot farm); it is not used to track people
 * across sites, and only the hash is sent.
 */
export async function deviceHash(): Promise<string> {
  const nav = navigator as Navigator & { deviceMemory?: number };
  const parts = [
    nav.userAgent,
    nav.language,
    (nav.languages || []).join(","),
    String(nav.hardwareConcurrency || ""),
    String(nav.deviceMemory || ""),
    `${screen.width}x${screen.height}x${screen.colorDepth}`,
    String(window.devicePixelRatio || 1),
    Intl.DateTimeFormat().resolvedOptions().timeZone || "",
    String(nav.maxTouchPoints || 0),
  ];
  return sha256(parts.join("|"));
}

export async function userAgentHash(): Promise<string> {
  return sha256(navigator.userAgent);
}

export function newEventId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
