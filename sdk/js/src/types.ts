export type EntityType = "human" | "agent" | "wallet" | "service";
export type Result = "success" | "failure" | "denied";
export type Sensitivity = "low" | "medium" | "high" | "critical";
export type Response = "allow" | "step_up" | "shadow" | "pause_agent";

export interface Entity {
  id: string;
  type?: EntityType;
}

export interface Resource {
  id: string;
  type: string;
  sensitivity?: Sensitivity;
}

export interface TelemetryEvent {
  type: "keydown" | "keyup" | "mousemove" | "click" | "scroll" | "touchstart" | "paste";
  timestamp: number;
  key?: "char" | "space" | "backspace" | "delete" | "enter" | "tab" | "other";
  x?: number;
  y?: number;
  page?: string;
}

export interface TrackInput {
  action: string;
  resource: Resource;
  result?: Result;
  value?: { amount: number; asset?: string; destination?: string };
  entity?: Entity;
  context?: { wallet?: string; funded_by?: string; geo?: string };
}

export interface SdkEvent {
  event_id: string;
  timestamp: number;
  session_id: string;
  entity: Required<Entity>;
  action: string;
  resource: Resource;
  result: Result;
  value?: TrackInput["value"];
  context: Record<string, string>;
  telemetry?: { events?: TelemetryEvent[]; event_count: number };
}

export interface BrowserVerdict {
  verdict_id: string;
  session_id: string;
  event_id: string;
  action: Response;
  enforced: boolean;
}

export interface Rule {
  match: {
    url?: string;
    event?: "click" | "submit";
    selector?: string;
    text?: string | string[];
    has?: string;
  };
  action: string;
  resource: { type: string; id_from?: string; sensitivity?: Sensitivity };
  value_from?: string;
}

export interface SiteConfig {
  site_id: string;
  mode: "observe" | "enforce";
  rules: Rule[];
}

export interface InitOptions {
  publishableKey: string;
  endpoint: string;
  /** Capture typing and mouse timing (never content). Default true. */
  captureBehavior?: boolean;
  /** Map clicks and submits to actions with the site's rules. Default true. */
  autoCapture?: boolean;
  /** Add a hidden neurosoc_session field to forms so the backend can check the verdict. Default true. */
  tagForms?: boolean;
  /** Start without capturing until consent(true) is called. Default false. */
  waitForConsent?: boolean;
  flushIntervalMs?: number;
  maxBatch?: number;
  debug?: boolean;
  /** Send through the Lens extension instead of fetch (pages whose CSP blocks outside hosts). */
  relay?: boolean;
}
