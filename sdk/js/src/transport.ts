import type { BrowserVerdict, SdkEvent, SiteConfig } from "./types";

/** A non-2xx answer from the NeuroSOC API. */
export class HttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

/** Sends one request to the NeuroSOC API and returns the parsed JSON body (or throws). */
export type Sender = (path: string, body: string | undefined, timeoutMs: number) => Promise<unknown>;

/**
 * Default sender: a CORS "simple request" (text/plain body, key in the URL), so there is no
 * preflight round trip, and the same request also works from navigator.sendBeacon on page close.
 */
export function fetchSender(endpoint: string, key: string): Sender {
  const base = endpoint.replace(/\/$/, "");
  return async (path, body, timeoutMs) => {
    const url = `${base}${path}?key=${encodeURIComponent(key)}`;
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const response = await fetch(url, body === undefined
        ? { credentials: "omit", signal: controller?.signal }
        : { method: "POST", credentials: "omit", headers: { "Content-Type": "text/plain;charset=UTF-8" },
            body, keepalive: body.length < 60_000, signal: controller?.signal });
      if (!response.ok) throw new HttpError(response.status);
      return await response.json();
    } finally {
      if (timer) clearTimeout(timer);
    }
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
    const data = event.data as { __neurosoc_reply?: string; ok?: boolean; body?: unknown; error?: string; status?: number };
    if (event.source !== window || !data?.__neurosoc_reply) return;
    const waiter = pending.get(data.__neurosoc_reply);
    if (!waiter) return;
    pending.delete(data.__neurosoc_reply);
    if (data.ok) waiter.resolve(data.body);
    else waiter.reject(data.status ? new HttpError(data.status) : new Error(data.error || "relay failed"));
  });
  return (path, body, timeoutMs) => new Promise((resolve, reject) => {
    const id = `nsoc_${Date.now()}_${counter++}`;
    pending.set(id, { resolve, reject });
    window.postMessage({ __neurosoc_request: id, path, body }, window.location.origin);
    setTimeout(() => {
      if (pending.delete(id)) reject(new Error("relay timed out"));
    }, timeoutMs);
  });
}

interface Item {
  event: SdkEvent;
  resolve: (verdict: BrowserVerdict | null) => void;
  urgent: boolean;
  attempts: number;
}

export interface TransportOptions {
  sender: Sender;
  beaconUrl: string | null;
  flushIntervalMs: number;
  maxBatch: number;
  timeoutMs: number;
  debug: boolean;
  onVerdicts: (verdicts: BrowserVerdict[]) => void;
}

const MAX_QUEUE = 500;
const MAX_ATTEMPTS = 5;
const BEACON_LIMIT = 58_000;
const AUTH_FAILURES_BEFORE_STOP = 3;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function retryable(error: unknown): boolean {
  if (error instanceof HttpError) return error.status >= 500 || error.status === 408 || error.status === 429;
  return true; // network failure, timeout, unreadable body
}

export class Transport {
  private queue: Item[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private authFailures = 0;
  private stopped = false;
  private warned = new Set<string>();
  private onlineHandler = () => { void this.flush(); };

  constructor(private o: TransportOptions) {
    if (typeof window !== "undefined") window.addEventListener("online", this.onlineHandler);
  }

  private warn(code: string, message: string, always = false): void {
    if (!always && !this.o.debug) return;
    if (this.warned.has(code)) return;
    this.warned.add(code);
    console.warn(`[neurosoc] ${message}`);
  }

  /** The site's mode and rules. Retries a couple of times so a brief outage at load is not permanent. */
  async config(): Promise<SiteConfig | null> {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (this.stopped) return null;
      try {
        const body = (await this.o.sender("/api/v1/sdk/config", undefined, this.o.timeoutMs)) as Partial<SiteConfig>;
        if (body && Array.isArray(body.rules) && (body.mode === "observe" || body.mode === "enforce")) return body as SiteConfig;
        return null;
      } catch (error) {
        if (error instanceof HttpError && (error.status === 401 || error.status === 403)) {
          this.warn("auth", `the site key or origin was rejected (HTTP ${error.status}); check the key and the site's registered origins`, true);
          return null;
        }
        if (!retryable(error)) return null;
        await sleep(1000 * 3 ** attempt);
      }
    }
    return null;
  }

  /** Queue an event; resolves with its verdict once the batch it rides in comes back. */
  send(event: SdkEvent, urgent = false): Promise<BrowserVerdict | null> {
    return new Promise((resolve) => {
      if (this.stopped) return resolve(null);
      this.queue.push({ event, resolve, urgent, attempts: 0 });
      while (this.queue.length > MAX_QUEUE) this.queue.shift()?.resolve(null);
      if (urgent || this.queue.length >= this.o.maxBatch) void this.flush();
      else this.arm(this.o.flushIntervalMs);
    });
  }

  private arm(ms: number): void {
    if (this.timer || this.stopped) return;
    this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, ms);
  }

  private disarm(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  async flush(): Promise<void> {
    this.disarm();
    const batches: Item[][] = [];
    while (this.queue.length) batches.push(this.queue.splice(0, this.o.maxBatch));
    await Promise.all(batches.map((batch) => this.deliver(batch)));
  }

  private async post(batch: Item[]): Promise<BrowserVerdict[]> {
    const body = (await this.o.sender("/api/v1/sdk/events",
      JSON.stringify({ events: batch.map((item) => item.event) }), this.o.timeoutMs)) as { verdicts?: BrowserVerdict[] };
    if (!body || !Array.isArray(body.verdicts)) throw new Error("unexpected response");
    return body.verdicts;
  }

  private async deliver(batch: Item[]): Promise<void> {
    const urgent = batch.some((item) => item.urgent);
    let failure: unknown;
    for (let attempt = 0; attempt < (urgent ? 2 : 1); attempt += 1) {
      if (attempt) await sleep(250);
      try {
        const verdicts = await this.post(batch);
        this.authFailures = 0;
        const byEvent = new Map(verdicts.map((v) => [v.event_id, v]));
        batch.forEach((item) => item.resolve(byEvent.get(item.event.event_id) ?? null));
        this.o.onVerdicts(verdicts);
        return;
      } catch (error) {
        failure = error;
        if (!retryable(error)) break;
      }
    }
    await this.handleFailure(batch, failure);
  }

  private async handleFailure(batch: Item[], error: unknown): Promise<void> {
    if (this.stopped) {
      batch.forEach((item) => item.resolve(null));
      return;
    }
    if (error instanceof HttpError) {
      if (error.status === 401 || error.status === 403) {
        this.warn("auth", `events were rejected (HTTP ${error.status}); check the site key and the site's registered origins`, true);
        batch.forEach((item) => item.resolve(null));
        this.authFailures += 1;
        if (this.authFailures >= AUTH_FAILURES_BEFORE_STOP) this.close();
        return;
      }
      if (error.status === 422 && batch.length > 1) {
        // One malformed event makes the server reject the whole batch: send them one by one so
        // only the bad one is lost.
        await Promise.all(batch.map((item) => this.deliver([item])));
        return;
      }
    }
    if (!retryable(error)) {
      this.warn(`drop-${(error as HttpError)?.status}`, `events were not accepted (${(error as Error)?.message}) and were dropped`);
      batch.forEach((item) => item.resolve(null));
      return;
    }
    this.warn("net", `event delivery failed (${(error as Error)?.message}); will retry`);
    const keep: Item[] = [];
    for (const item of batch) {
      item.resolve(null); // a waiting guard() gets null now; the event itself is still delivered later
      item.urgent = false;
      item.attempts += 1;
      if (item.attempts < MAX_ATTEMPTS) keep.push(item);
    }
    this.queue.unshift(...keep);
    while (this.queue.length > MAX_QUEUE) this.queue.shift();
    if (keep.length) this.arm(Math.min(30_000, 1000 * 2 ** Math.max(...keep.map((item) => item.attempts))));
  }

  /** Last-chance delivery when the page is closed. */
  beacon(): void {
    this.disarm();
    const items = this.queue.splice(0);
    if (!items.length) return;
    let chunk: Item[] = [];
    let size = 0;
    const send = () => {
      if (!chunk.length) return;
      const body = JSON.stringify({ events: chunk.map((item) => item.event) });
      let sent = false;
      if (this.o.beaconUrl && typeof navigator.sendBeacon === "function") {
        sent = navigator.sendBeacon(this.o.beaconUrl, new Blob([body], { type: "text/plain;charset=UTF-8" }));
      }
      if (!sent) void this.o.sender("/api/v1/sdk/events", body, this.o.timeoutMs).catch(() => undefined);
      chunk = [];
      size = 0;
    };
    for (const item of items) {
      item.resolve(null);
      // An event carrying a long timing window can alone exceed the beacon limit; shorten the window.
      let encoded = JSON.stringify(item.event);
      if (encoded.length > BEACON_LIMIT && item.event.telemetry?.events) {
        const events = item.event.telemetry.events;
        item.event.telemetry.events = events.slice(-Math.max(20, Math.floor(events.length * BEACON_LIMIT / encoded.length / 2)));
        encoded = JSON.stringify(item.event);
      }
      if (size + encoded.length > BEACON_LIMIT) send();
      chunk.push(item);
      size += encoded.length;
    }
    send();
  }

  /** Stop sending and drop whatever is queued (consent withdrawn, or the client was destroyed). */
  close(): void {
    this.stopped = true;
    this.disarm();
    this.queue.splice(0).forEach((item) => item.resolve(null));
    if (typeof window !== "undefined") window.removeEventListener("online", this.onlineHandler);
  }

  /** Start sending again after close() (consent granted again). */
  reopen(): void {
    this.stopped = false;
    this.authFailures = 0;
    if (typeof window !== "undefined") window.addEventListener("online", this.onlineHandler);
  }

  get isStopped(): boolean {
    return this.stopped;
  }
}
