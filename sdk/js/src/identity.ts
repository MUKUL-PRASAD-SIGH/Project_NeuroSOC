// Session and device identifiers. Storage can be blocked (private windows, strict settings), so
// every access is guarded and falls back to an in-memory value. Nothing is written to storage
// until the caller says the visitor has consented (persist = true).

const SESSION_KEY = "nsoc_sid";
const VISITOR_KEY = "nsoc_vid";
const STARTED_KEY = "nsoc_started";

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function randomId(prefix: string): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return prefix + bytesToHex(bytes);
}

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string): void {
  try {
    storage().setItem(key, value);
  } catch {
    /* blocked storage: the in-memory id still works for this page */
  }
}

const session = () => window.sessionStorage;
const local = () => window.localStorage;

/** One id per browser tab session; the site's backend uses it to ask for the verdict. */
export function sessionId(persist: boolean): string {
  const existing = read(session, SESSION_KEY);
  if (existing) return existing;
  const value = randomId("ses_");
  if (persist) write(session, SESSION_KEY, value);
  return value;
}

/** A stable anonymous visitor id, used as the entity until identify() or a wallet says who it is. */
export function visitorId(persist: boolean): string {
  const existing = read(local, VISITOR_KEY);
  if (existing) return existing;
  const value = randomId("vis_");
  if (persist) write(local, VISITOR_KEY, value);
  return value;
}

export function persistIds(sid: string, vid: string): void {
  write(session, SESSION_KEY, sid);
  write(local, VISITOR_KEY, vid);
}

/** Consent withdrawn: remove everything the SDK stored. */
export function forgetIds(): void {
  for (const [storage, key] of [[session, SESSION_KEY], [session, STARTED_KEY], [local, VISITOR_KEY]] as const) {
    try {
      storage().removeItem(key);
    } catch {
      /* nothing to remove */
    }
  }
}

/** True the first time it is called in this tab session, so session.start is sent once, not per page. */
export function claimSessionStart(persist: boolean): boolean {
  if (read(session, STARTED_KEY)) return false;
  if (persist) write(session, STARTED_KEY, "1");
  return true;
}

export function releaseSessionStart(): void {
  try {
    session().removeItem(STARTED_KEY);
  } catch {
    /* nothing to remove */
  }
}

/**
 * Non-cryptographic 128-bit hash for pages where crypto.subtle does not exist (plain http, some
 * embedded webviews). It only has to be stable, so accounts from one device still link up.
 */
function fallbackHash(text: string): string {
  const h = [0x243f6a88, 0x85a308d3, 0x13198a2e, 0x03707344];
  for (let i = 0; i < text.length; i += 1) {
    const c = text.charCodeAt(i);
    for (let k = 0; k < 4; k += 1) {
      h[k] = Math.imul(h[k] ^ c, 0x9e3779b1 + k * 2);
      h[k] ^= h[k] >>> 15;
      h[k] = Math.imul(h[k], 0x85ebca6b);
      h[k] ^= h[k] >>> 13;
    }
  }
  for (let k = 0; k < 4; k += 1) h[k] = Math.imul(h[k] ^ h[(k + 1) % 4], 0xc2b2ae35) ^ (h[k] >>> 16);
  return h.map((x) => (x >>> 0).toString(16).padStart(8, "0")).join("");
}

async function sha256(text: string): Promise<string> {
  const subtle = typeof crypto !== "undefined" ? crypto.subtle : undefined;
  if (!subtle) return fallbackHash(text);
  try {
    const digest = await subtle.digest("SHA-256", new TextEncoder().encode(text));
    return bytesToHex(new Uint8Array(digest)).slice(0, 32);
  } catch {
    return fallbackHash(text);
  }
}

/**
 * A coarse device fingerprint from stable, non-identifying properties, hashed in the page.
 * It links accounts that come from one machine (a bot farm); it is not used to track people
 * across sites, and only the hash is sent.
 */
export async function deviceHash(): Promise<string> {
  const nav = navigator as Navigator & { deviceMemory?: number };
  let timeZone = "";
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    /* Intl unavailable */
  }
  const parts = [
    nav.userAgent,
    nav.language,
    (nav.languages || []).join(","),
    String(nav.hardwareConcurrency || ""),
    String(nav.deviceMemory || ""),
    `${screen.width}x${screen.height}x${screen.colorDepth}`,
    String(window.devicePixelRatio || 1),
    timeZone,
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
  const hex = bytesToHex(bytes);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
