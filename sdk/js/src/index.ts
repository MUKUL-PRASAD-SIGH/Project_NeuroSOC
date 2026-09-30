import { deviceHash, newEventId, sessionId, userAgentHash, visitorId } from "./identity";
import { findRule, toTrackInput } from "./rules";
import { Telemetry } from "./telemetry";
import { Transport } from "./transport";
import type { BrowserVerdict, Entity, InitOptions, Rule, SdkEvent, TrackInput } from "./types";
import { watchWallets } from "./wallet";

export type * from "./types";

// Actions a person performs through the UI: these carry the recent input-timing window so the
// engine can tell a person from a script. Everything else carries only a count.
const INTERACTIVE = new Set([
  "account.create", "auth.login", "wallet.connect", "campaign.join", "task.complete",
  "reward.claim", "referral.create", "form.submit", "token.buy", "token.sell", "token.transfer",
]);

export class NeuroSOC {
  readonly sessionId: string;
  private telemetry = new Telemetry();
  private transport: Transport;
  private entity: Required<Entity>;
  private wallet: string | undefined;
  private context: Record<string, string> = {};
  private contextReady: Promise<void>;
  private rules: Rule[] = [];
  private mode: "observe" | "enforce" = "observe";
  private listeners: Array<(verdict: BrowserVerdict) => void> = [];
  private consented: boolean;
  private started = false;

  private constructor(private options: Required<InitOptions>) {
    this.sessionId = sessionId();
    this.entity = { id: visitorId(), type: "human" };
    this.consented = !options.waitForConsent;
    this.transport = new Transport(options.endpoint, options.publishableKey, options.flushIntervalMs,
      options.maxBatch, (verdicts) => verdicts.forEach((v) => this.listeners.forEach((l) => l(v))), options.debug);
    this.contextReady = Promise.all([deviceHash(), userAgentHash()])
      .then(([device, ua]) => { this.context.device_hash = device; this.context.user_agent_hash = ua; })
      .catch(() => undefined);
  }

  static init(options: InitOptions): NeuroSOC {
    if (!options.publishableKey?.startsWith("pk_")) throw new Error("NeuroSOC: a publishable key (pk_...) is required.");
    if (!options.endpoint) throw new Error("NeuroSOC: endpoint is required.");
    const client = new NeuroSOC({
      captureBehavior: true, autoCapture: true, tagForms: true, waitForConsent: false,
      flushIntervalMs: 2000, maxBatch: 20, debug: false, ...options,
    });
    if (client.consented) client.start();
    return client;
  }

  /** Say who is acting: a signed-in user id, a wallet address, an agent id. */
  identify(entity: Entity): void {
    this.entity = { id: String(entity.id).slice(0, 256), type: entity.type ?? "human" };
  }

  /** Turn capture on or off, e.g. from a cookie banner. Nothing is collected while off. */
  consent(granted: boolean): void {
    this.consented = granted;
    if (granted) this.start();
    else { this.telemetry.stop(); this.started = false; }
  }

  onVerdict(listener: (verdict: BrowserVerdict) => void): () => void {
    this.listeners.push(listener);
    return () => { this.listeners = this.listeners.filter((l) => l !== listener); };
  }

  /** Record an action. Resolves with the verdict for it (or null if it could not be delivered). */
  track(input: TrackInput, urgent = false): Promise<BrowserVerdict | null> {
    if (!this.consented) return Promise.resolve(null);
    return this.contextReady.then(() => this.transport.send(this.buildEvent(input), urgent));
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

  // ── internals ─────────────────────────────────────────────────────────────
  private buildEvent(input: TrackInput): SdkEvent {
    const entity = input.entity ? { id: input.entity.id, type: input.entity.type ?? "human" } : this.entity;
    const context: Record<string, string> = { ...this.context, page: location.pathname.slice(0, 256) };
    if (this.wallet) context.wallet = this.wallet;
    if (input.context) Object.entries(input.context).forEach(([k, v]) => { if (v) context[k] = String(v); });
    const event: SdkEvent = {
      event_id: newEventId(),
      timestamp: Date.now() / 1000,
      session_id: this.sessionId,
      entity: entity as Required<Entity>,
      action: input.action,
      resource: input.resource,
      result: input.result ?? "success",
      context,
    };
    if (input.value) event.value = input.value;
    if (this.options.captureBehavior) {
      event.telemetry = INTERACTIVE.has(input.action)
        ? this.telemetry.snapshot()
        : { event_count: this.telemetry.count() };
    }
    return event;
  }

  private start(): void {
    if (this.started) return;
    this.started = true;
    if (this.options.captureBehavior) this.telemetry.start();

    void this.transport.config().then((config) => {
      if (!config) return;
      this.rules = config.rules || [];
      this.mode = config.mode;
    });

    void this.track({ action: "session.start", resource: { id: location.hostname || "site", type: "site" } });
    this.pageView();
    this.watchNavigation();

    watchWallets((address) => {
      if (this.wallet === address) return;
      this.wallet = address;
      if (this.entity.id.startsWith("vis_")) this.entity = { id: address, type: "human" };
      void this.track({ action: "wallet.connect", resource: { id: location.hostname || "site", type: "site" } });
    });

    if (this.options.autoCapture) {
      document.addEventListener("click", (event) => this.autoTrack(event), { capture: true });
      document.addEventListener("submit", (event) => this.autoTrack(event), { capture: true });
    }
    if (this.options.tagForms) {
      document.addEventListener("submit", (event) => this.tagForm(event.target), { capture: true });
    }
    const leave = () => { if (document.visibilityState === "hidden") this.transport.beacon(); };
    document.addEventListener("visibilitychange", leave);
    window.addEventListener("pagehide", () => this.transport.beacon());
  }

  private autoTrack(event: Event): void {
    if (!this.consented || !this.rules.length) return;
    const found = findRule(this.rules, event, location);
    if (!found) return;
    const input = toTrackInput(found.rule, found.element, location);
    if (input) void this.track(input, input.action === "reward.claim" || event.type === "submit");
  }

  private tagForm(target: EventTarget | null): void {
    if (!(target instanceof HTMLFormElement)) return;
    let field = target.querySelector<HTMLInputElement>("input[name=neurosoc_session]");
    if (!field) {
      field = document.createElement("input");
      field.type = "hidden";
      field.name = "neurosoc_session";
      target.appendChild(field);
    }
    field.value = this.sessionId;
  }

  private pageView(): void {
    void this.track({ action: "page.view", resource: { id: (location.pathname || "/").slice(0, 256), type: "page" } });
  }

  private watchNavigation(): void {
    // Single-page apps change routes without reloading; count each route as a page view.
    let last = location.pathname;
    const check = () => {
      if (location.pathname !== last) { last = location.pathname; this.pageView(); }
    };
    for (const method of ["pushState", "replaceState"] as const) {
      const original = history[method];
      history[method] = function (this: History, ...args: Parameters<History["pushState"]>) {
        const result = original.apply(this, args);
        setTimeout(check, 0);
        return result;
      } as History["pushState"];
    }
    window.addEventListener("popstate", check);
  }
}

export default NeuroSOC;
