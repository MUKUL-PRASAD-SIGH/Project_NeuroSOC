import type { BrowserVerdict, SdkEvent, SiteConfig } from "./types";

/**
 * Batches events and posts them as a CORS "simple request" (text/plain body, key in the URL):
 * no preflight round trip, and the same request works from navigator.sendBeacon on page close.
 */
export class Transport {
  private queue: Array<{ event: SdkEvent; resolve: (v: BrowserVerdict | null) => void }> = [];
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private endpoint: string,
    private key: string,
    private flushIntervalMs: number,
    private maxBatch: number,
    private onVerdicts: (verdicts: BrowserVerdict[]) => void,
    private debug: boolean,
  ) {}

  private url(path: string): string {
    return `${this.endpoint.replace(/\/$/, "")}${path}?key=${encodeURIComponent(this.key)}`;
  }

  async config(): Promise<SiteConfig | null> {
    try {
      const response = await fetch(this.url("/api/v1/sdk/config"), { credentials: "omit" });
      return response.ok ? ((await response.json()) as SiteConfig) : null;
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
        const response = await fetch(this.url("/api/v1/sdk/events"), {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "text/plain;charset=UTF-8" },
          body: JSON.stringify({ events: batch.map((item) => item.event) }),
          keepalive: batch.length < 10,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = (await response.json()) as { verdicts: BrowserVerdict[] };
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
    const batch = this.queue.splice(0, this.maxBatch);
    const body = JSON.stringify({ events: batch.map((item) => item.event) });
    const sent = typeof navigator.sendBeacon === "function" &&
      navigator.sendBeacon(this.url("/api/v1/sdk/events"), new Blob([body], { type: "text/plain;charset=UTF-8" }));
    batch.forEach((item) => item.resolve(null));
    if (!sent && this.debug) console.warn("[neurosoc] beacon was not accepted");
  }
}
