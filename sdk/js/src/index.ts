import { claimSessionStart, deviceHash, forgetIds, newEventId, persistIds, randomId, releaseSessionStart, sessionId, userAgentHash, visitorId } from "./identity";
import { findRule, toTrackInput } from "./rules";
import { Telemetry } from "./telemetry";
import { Transport, fetchSender, relaySender } from "./transport";
import type { BrowserVerdict, Entity, EntityType, InitOptions, Rule, SdkEvent, TrackInput } from "./types";
import { watchWallets } from "./wallet";

export type {
  BrowserVerdict, Entity, EntityType, InitOptions, Resource, Response, Result, Rule, SdkEvent,
  Sensitivity, SiteConfig, TelemetryEvent, TrackInput,
} from "./types";

declare const __SDK_VERSION__: string;
const VERSION = typeof __SDK_VERSION__ === "string" ? __SDK_VERSION__ : "dev";

// Actions a person performs through the UI: these carry the recent input-timing window so the
// engine can tell a person from a script. Everything else carries only a count.
const INTERACTIVE = new Set([
  "account.create", "auth.login", "wallet.connect", "campaign.join", "task.complete",
  "reward.claim", "referral.create", "form.submit", "token.buy", "token.sell", "token.transfer",
]);
const ENTITY_TYPES = new Set<string>(["human", "agent", "wallet", "service"]);
const CONFIG_WAIT_MS = 3000;

const clip = (value: unknown, max: number): string => String(value).slice(0, max);

/** The page's route: the path, plus the hash when the app routes with "#/..." URLs. */
function route(): string {
  const { pathname, hash } = location;
  return (pathname || "/") + (/^#!?\//.test(hash) ? hash : "");
}

let current: NeuroSOC | null = null;

export class NeuroSOC {
  static readonly version = VERSION;

  private sid: string;
  private vid: string;
  private telemetry = new Telemetry();
  private transport: Transport;
  private entity: Required<Entity>;
  private entityFromWallet = false;
  private wallet: string | undefined;
  private context: Record<string, string> = {};
  private contextReady: Promise<void> = Promise.resolve();
  private rules: Rule[] = [];
  private mode: "observe" | "enforce" = "observe";
  private listeners: Array<(verdict: BrowserVerdict) => void> = [];
  private consented: boolean;
  private running = false;
  private destroyed = false;
  private configLoaded = false;
  private configFailed = false;
  private configPromise: Promise<void> | null = null;
  private teardown: Array<() => void> = [];

  /** Resolves once the site's mode and rules have been fetched (or the attempt has failed). */
  ready: Promise<void> = Promise.resolve();

  private constructor(private options: Required<InitOptions>, private inert: boolean) {
    this.consented = !options.waitForConsent;
    this.sid = inert ? "ses_inert" : sessionId(this.consented);
    this.vid = inert ? "vis_inert" : visitorId(this.consented);
    this.entity = { id: this.vid, type: "human" };
    const base = options.endpoint.replace(/\/$/, "");
    this.transport = new Transport({
      sender: inert ? async () => null : options.relay ? relaySender() : fetchSender(options.endpoint, options.publishableKey),
      beaconUrl: options.relay ? null : `${base}/api/v1/sdk/events?key=${encodeURIComponent(options.publishableKey)}`,
      flushIntervalMs: options.flushIntervalMs,
      maxBatch: options.maxBatch,
      timeoutMs: options.timeoutMs,
      debug: options.debug,
      onVerdicts: (verdicts) => verdicts.forEach((v) => this.listeners.forEach((l) => {
        try { l(v); } catch (error) { if (options.debug) console.warn("[neurosoc] verdict listener threw", error); }
      })),
    });
    if (!inert) {
      this.contextReady = Promise.all([deviceHash(), userAgentHash()])
        .then(([device, ua]) => { this.context.device_hash = device; this.context.user_agent_hash = ua; })
        .catch(() => undefined);
    }
  }

  /**
   * Start the SDK. Safe to call twice (a second call returns the running client) and safe on the
   * server: with no browser around it returns an inert client whose methods do nothing, so the same
   * component can render under SSR.
   */
  static init(options: InitOptions): NeuroSOC {
    if (!options?.publishableKey?.startsWith("pk_")) throw new Error("NeuroSOC: a publishable key (pk_...) is required.");
    if (!options.endpoint) throw new Error("NeuroSOC: endpoint is required.");
    if (current && !current.destroyed) {
      if (options.debug) console.warn("[neurosoc] init() called again; returning the running client");
      return current;
    }
    const inert = typeof window === "undefined" || typeof document === "undefined";
    const maxBatch = Math.min(50, Math.max(1, Math.floor(options.maxBatch ?? 20)));
    const client = new NeuroSOC({
      captureBehavior: true, autoCapture: true, tagForms: true, waitForConsent: false,
      flushIntervalMs: 2000, timeoutMs: 8000, debug: false, relay: false,
      ...options, maxBatch,
    }, inert);
    if (!inert) current = client;
    if (client.consented) client.start();
    return client;
  }

  /** The tab session id, also written into every same-origin POST form as neurosoc_session. */
  get sessionId(): string {
    return this.sid;
  }

  /** Say who is acting: a signed-in user id, a wallet address, an agent id. */
  identify(entity: Entity): void {
    const id = entity?.id === undefined || entity.id === null ? "" : String(entity.id).trim();
    if (!id) {
      if (this.options.debug) console.warn("[neurosoc] identify() needs an id; ignored");
      return;
    }
    const type = entity.type && ENTITY_TYPES.has(entity.type) ? entity.type : "human";
    this.entity = { id: clip(id, 256), type };
    this.entityFromWallet = false;
  }

  /** Sign-out: forget who was acting and start a fresh session. */
  reset(): void {
    if (this.inert || this.destroyed) return;
    this.entity = { id: this.vid, type: "human" };
    this.entityFromWallet = false;
    this.wallet = undefined;
    if (!this.consented) return;
    releaseSessionStart();
    this.sid = randomId("ses_");
    persistIds(this.sid, this.vid);
    claimSessionStart(true);
    this.startSession();
  }

  /** Turn capture on or off, e.g. from a cookie banner. Nothing is collected or stored while off. */
  consent(granted: boolean): void {
    if (this.inert || this.destroyed || granted === this.consented) return;
    this.consented = granted;
    if (granted) {
      this.sid = randomId("ses_");
      persistIds(this.sid, this.vid);
      this.transport.reopen();
      this.start();
    } else {
      this.stop();
      this.transport.close();
      forgetIds();
      this.sid = randomId("ses_");
      this.vid = randomId("vis_");
      this.entity = { id: this.vid, type: "human" };
      this.entityFromWallet = false;
      this.wallet = undefined;
    }
  }

  onVerdict(listener: (verdict: BrowserVerdict) => void): () => void {
    this.listeners.push(listener);
    return () => { this.listeners = this.listeners.filter((l) => l !== listener); };
  }

  /** Record an action. Resolves with the verdict for it (or null if it could not be delivered). */
  track(input: TrackInput, urgent = false): Promise<BrowserVerdict | null> {
    if (this.inert || this.destroyed || !this.consented) return Promise.resolve(null);
    const event = this.contextReady.then(() => this.buildEvent(input));
    return event.then((built) => (built ? this.transport.send(built, urgent) : null));
  }

  /** Record an action and wait for its verdict before continuing, e.g. before showing a reward. */
  guard(input: TrackInput): Promise<BrowserVerdict | null> {
    return this.track(input, true);
  }

  /** Current mode from the site's settings: observe (report only) or enforce. */
  getMode(): "observe" | "enforce" {
    return this.mode;
  }

  flush(): Promise<void> {
    return this.transport.flush();
  }

  /** Remove every listener and stop sending. For single-page apps that unmount the SDK. */
  destroy(): void {
    if (this.destroyed) return;
    this.stop();
    this.transport.close();
    this.destroyed = true;
    this.listeners = [];
    if (current === this) current = null;
  }

  // ── internals ─────────────────────────────────────────────────────────────
  private warn(message: string): void {
    if (this.options.debug) console.warn(`[neurosoc] ${message}`);
  }

  private buildEvent(input: TrackInput): SdkEvent | null {
    if (!input || typeof input.action !== "string" || !input.action
      || !input.resource || !input.resource.id || !input.resource.type) {
      this.warn("track() needs an action and a resource with id and type; event dropped");
      return null;
    }
    const entity = input.entity?.id
      ? { id: clip(input.entity.id, 256), type: (input.entity.type && ENTITY_TYPES.has(input.entity.type) ? input.entity.type : "human") as EntityType }
      : this.entity;
    const context: Record<string, string> = {
      ...this.context, page: clip(location.pathname, 256), page_origin: clip(location.origin, 256),
    };
    if (this.wallet) context.wallet = clip(this.wallet, 128);
    // The server rejects unknown context keys, so only the documented ones go through.
    for (const [key, max] of [["wallet", 128], ["funded_by", 128], ["geo", 8]] as const) {
      const value = input.context?.[key];
      if (value) context[key] = clip(value, max);
    }
    const resource = {
      id: clip(input.resource.id, 256), type: clip(input.resource.type, 64),
      ...(input.resource.sensitivity ? { sensitivity: input.resource.sensitivity } : {}),
    };
    const event: SdkEvent = {
      event_id: newEventId(),
      timestamp: Date.now() / 1000,
      session_id: this.sid,
      entity: entity as Required<Entity>,
      action: input.action,
      resource,
      result: input.result ?? "success",
      context,
    };
    const amount = Number(input.value?.amount);
    if (input.value && Number.isFinite(amount) && amount >= 0) {
      event.value = { amount };
      if (input.value.asset) event.value.asset = clip(input.value.asset, 32);
      if (input.value.destination) event.value.destination = clip(input.value.destination, 256);
    } else if (input.value) {
      this.warn("value.amount must be a number of 0 or more; value dropped");
    }
    if (this.options.captureBehavior) {
      event.telemetry = INTERACTIVE.has(input.action)
        ? this.telemetry.snapshot()
        : { event_count: this.telemetry.count() };
    }
    return event;
  }

  private on<T extends EventTarget>(target: T, type: string, handler: (event: Event) => void, options?: AddEventListenerOptions): void {
    target.addEventListener(type, handler, options);
    this.teardown.push(() => target.removeEventListener(type, handler, options));
  }

  private start(): void {
    if (this.running || this.destroyed || this.inert) return;
    this.running = true;

    if (this.options.captureBehavior) {
      this.telemetry.start();
      this.teardown.push(() => this.telemetry.stop());
    }

    if (!this.configPromise || this.configFailed) {
      this.configFailed = false;
      this.configLoaded = false;
      this.configPromise = this.loadConfig();
    }
    this.ready = this.configPromise;

    if (claimSessionStart(this.consented)) this.startSession();
    else this.pageView();
    this.watchNavigation();

    const stopWallets = watchWallets(
      (address) => {
        if (this.wallet === address) return;
        this.wallet = address;
        if (this.entity.id === this.vid || this.entityFromWallet) {
          this.entity = { id: address, type: "human" };
          this.entityFromWallet = true;
        }
        void this.track({ action: "wallet.connect", resource: { id: location.hostname || "site", type: "site" } });
      },
      () => {
        if (!this.wallet) return;
        if (this.entityFromWallet) this.entity = { id: this.vid, type: "human" };
        this.entityFromWallet = false;
        this.wallet = undefined;
      });
    this.teardown.push(stopWallets);

    if (this.options.autoCapture) {
      this.on(document, "click", (event) => this.autoTrack(event), { capture: true });
      this.on(document, "submit", (event) => this.autoTrack(event), { capture: true });
    }
    if (this.options.tagForms) {
      // Covers native submit, requestSubmit() and fetch(new FormData(form)) without touching the DOM...
      this.on(document, "formdata", (event) => {
        const form = event.target;
        if (this.shouldTag(form)) (event as FormDataEvent).formData.set("neurosoc_session", this.sid);
      });
      // ...and the hidden field covers form.submit() and browsers without the formdata event.
      this.on(document, "submit", (event) => this.tagForm(event.target), { capture: true });
    }
    // Hidden tab: send now but keep waiting callers' verdicts. Page closing: beacon what is left.
    this.on(document, "visibilitychange", () => { if (document.visibilityState === "hidden") void this.transport.flush(); });
    this.on(window, "pagehide", () => this.transport.beacon());
  }

  private stop(): void {
    if (!this.running) return;
    this.running = false;
    this.teardown.splice(0).forEach((undo) => undo());
  }

  private startSession(): void {
    void this.track({ action: "session.start", resource: { id: location.hostname || "site", type: "site" } });
    this.pageView();
  }

  private loadConfig(): Promise<void> {
    const load = this.transport.config().then((config) => {
      if (config) {
        this.rules = config.rules;
        this.mode = config.mode;
      } else {
        this.configFailed = true;
        this.warn("site config unavailable; rule-mapped actions are off for this page");
      }
    }).catch(() => undefined).then(() => { this.configLoaded = true; });
    return load;
  }

  private autoTrack(event: Event): void {
    if (!this.consented || !this.running || !(event.target instanceof Element)) return;
    const kind = event.type === "submit" ? "submit" : "click";
    const target = event.target;
    const run = () => {
      if (!this.consented || !this.running || !this.rules.length) return;
      const found = findRule(this.rules, kind, target, location);
      if (!found) return;
      const input = toTrackInput(found.rule, found.element, location);
      if (input) void this.track(input, input.action === "reward.claim" || kind === "submit");
    };
    if (this.configLoaded) run();
    else {
      // A click that lands before the rules arrive is matched once they do, not lost.
      const wait = Promise.race([this.configPromise, new Promise((resolve) => setTimeout(resolve, CONFIG_WAIT_MS))]);
      void wait.then(run);
    }
  }

  /** Only forms that post back to this site get the session id: never leak it to a third party. */
  private shouldTag(target: EventTarget | null): target is HTMLFormElement {
    if (!(target instanceof Element) || target.tagName !== "FORM") return false;
    // getAttribute, not form.action: an <input name="action"> would shadow the property.
    const method = (target.getAttribute("method") || "get").toLowerCase();
    if (method !== "post") return false;
    try {
      return new URL(target.getAttribute("action") || location.href, location.href).origin === location.origin;
    } catch {
      return false;
    }
  }

  private tagForm(target: EventTarget | null): void {
    if (!this.shouldTag(target)) return;
    let field = target.querySelector<HTMLInputElement>("input[name=neurosoc_session]");
    if (!field) {
      field = document.createElement("input");
      field.type = "hidden";
      field.name = "neurosoc_session";
      target.appendChild(field);
    }
    field.value = this.sid;
  }

  private pageView(): void {
    void this.track({ action: "page.view", resource: { id: route(), type: "page" } });
  }

  private watchNavigation(): void {
    // Single-page apps change routes without reloading; count each route as a page view.
    let last = route();
    let active = true;
    const check = () => {
      if (active && route() !== last) { last = route(); this.pageView(); }
    };
    const restore: Array<() => void> = [];
    for (const method of ["pushState", "replaceState"] as const) {
      const original = history[method];
      const wrapped = function (this: History, ...args: Parameters<History["pushState"]>) {
        const result = original.apply(this, args);
        if (active) setTimeout(check, 0);
        return result;
      } as History["pushState"];
      history[method] = wrapped;
      // Put the original back only if nobody patched on top of ours; otherwise just go quiet.
      restore.push(() => { if (history[method] === wrapped) history[method] = original; });
    }
    this.on(window, "popstate", check);
    this.on(window, "hashchange", check);
    this.teardown.push(() => { active = false; restore.forEach((undo) => undo()); });
  }
}

export default NeuroSOC;
