import type { BrowserVerdict, SdkEvent, SiteConfig } from "./types";

/** Sends one request to the NeuroSOC API and returns the parsed JSON body (or throws). */
export type Sender = (path: string, body?: string) => Promise<unknown>;

/**
 * Default sender: a CORS "simple request" (text/plain body, key in the URL), so there is no
 * preflight round trip, and the same request also works from navigator.sendBeacon on page close.
 */
export function fetchSender(endpoint: string, key: string): Sender {
  return async (path, body) => {
    const url = `${endpoint.replace(/\/$/, "")}${path}?key=${encodeURIComponent(key)}`;
    const response = await fetch(url, body === undefined ? { credentials: "omit" } : {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body,
      keepalive: body.length < 60_000,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
}

/**
 * Relay sender for the Lens extension: pages with a strict Content Security Policy block calls to
 * other hosts, so the SDK hands each request to the extension (window.postMessage), whose
 * background worker makes the call and posts the answer back.
 */
export function relaySender(): Sender {
  let counter = 0;
  const pending = new Map<string, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  window.addEventListener("message", (event) => {
    const data = event.data as { __neurosoc_reply?: string; ok?: boolean; body?: unknown; error?: string };
    if (event.source !== window || !data?.__neurosoc_reply) return;
    const waiter = pending.get(data.__neurosoc_reply);
    if (!waiter) return;
    pending.delete(data.__neurosoc_reply);
    if (data.ok) waiter.resolve(data.body);
    else waiter.reject(new Error(data.error || "relay failed"));
  });
  return (path, body) => new Promise((resolve, reject) => {
    const id = `nsoc_${Date.now()}_${counter++}`;
    pending.set(id, { resolve, reject });
    window.postMessage({ __neurosoc_request: id, path, body }, window.location.origin);
    setTimeout(() => {
      if (pending.delete(id)) reject(new Error("relay timed out"));
    }, 10_000);
  });
}

export class Transport {
  private queue: Array<{ event: SdkEvent; resolve: (v: BrowserVerdict | null) => void }> = [];
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private sender: Sender,
    private beaconUrl: string | null,
    private flushIntervalMs: number,
    private maxBatch: number,
    private onVerdicts: (verdicts: BrowserVerdict[]) => void,
    private debug: boolean,
  ) {}

  async config(): Promise<SiteConfig | null> {
    try {
      return (await this.sender("/api/v1/sdk/config")) as SiteConfig;
    } catch {
      return null;
    }
  }

  /** Queue an event; resolves with its verdict once the batch it rides in comes back. */
  send(event: SdkEvent, urgent = false): Promise<BrowserVerdict | null> {
    return new Promise((resolve) => {
      this.queue.push({ event, resolve });
      if (urgent || this.queue.length >= this.maxBatch) void this.flush();
      else if (!this.timer) this.timer = setTimeout(() => void this.flush(), this.flushIntervalMs);
    });
  }

  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    while (this.queue.length) {
      const batch = this.queue.splice(0, this.maxBatch);
      try {
        const body = (await this.sender("/api/v1/sdk/events",
          JSON.stringify({ events: batch.map((item) => item.event) }))) as { verdicts: BrowserVerdict[] };
        const byEvent = new Map(body.verdicts.map((v) => [v.event_id, v]));
        batch.forEach((item) => item.resolve(byEvent.get(item.event.event_id) ?? null));
        this.onVerdicts(body.verdicts);
      } catch (error) {
        if (this.debug) console.warn("[neurosoc] event delivery failed", error);
        batch.forEach((item) => item.resolve(null));
      }
    }
  }

  /** Last-chance delivery when the page is hidden or closed. */
  beacon(): void {
    if (!this.queue.length) return;
    if (!this.beaconUrl || typeof navigator.sendBeacon !== "function") {
      void this.flush();
      return;
    }
    const batch = this.queue.splice(0, this.maxBatch);
    const body = JSON.stringify({ events: batch.map((item) => item.event) });
    const sent = navigator.sendBeacon(this.beaconUrl, new Blob([body], { type: "text/plain;charset=UTF-8" }));
    batch.forEach((item) => item.resolve(null));
    if (!sent && this.debug) console.warn("[neurosoc] beacon was not accepted");
  }
}
