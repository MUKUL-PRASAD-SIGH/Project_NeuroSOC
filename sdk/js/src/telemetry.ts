import type { TelemetryEvent } from "./types";

// Timing only: keys are reduced to a class, so nothing typed ever leaves the page.
function keyClass(key: string): TelemetryEvent["key"] {
  switch (key) {
    case " ":
    case "Spacebar":
      return "space";
    case "Backspace":
      return "backspace";
    case "Delete":
      return "delete";
    case "Enter":
      return "enter";
    case "Tab":
      return "tab";
    default:
      return key.length === 1 ? "char" : "other";
  }
}

const MOUSE_SAMPLE_MS = 16;
const BUFFER_LIMIT = 600;

/** Rolling buffer of input timing, attached to interactive actions (claims, submits). */
export class Telemetry {
  private buffer: TelemetryEvent[] = [];
  private lastMouse = 0;
  private total = 0;
  private detach: Array<() => void> = [];

  start(): void {
    if (this.detach.length) return;
    const on = <K extends keyof DocumentEventMap>(type: K, handler: (event: DocumentEventMap[K]) => void) => {
      document.addEventListener(type, handler as EventListener, { capture: true, passive: true });
      this.detach.push(() => document.removeEventListener(type, handler as EventListener, { capture: true }));
    };
    on("keydown", (e) => this.push({ type: "keydown", timestamp: Date.now(), key: keyClass(e.key) }));
    on("keyup", (e) => this.push({ type: "keyup", timestamp: Date.now(), key: keyClass(e.key) }));
    on("mousemove", (e) => {
      const now = Date.now();
      if (now - this.lastMouse < MOUSE_SAMPLE_MS) return;
      this.lastMouse = now;
      this.push({ type: "mousemove", timestamp: now, x: Math.round(e.clientX), y: Math.round(e.clientY) });
    });
    on("click", (e) => this.push({ type: "click", timestamp: Date.now(), x: Math.round(e.clientX), y: Math.round(e.clientY) }));
    on("touchstart", () => this.push({ type: "touchstart", timestamp: Date.now() }));
    on("paste", () => this.push({ type: "paste", timestamp: Date.now() }));
    const onScroll = () => this.push({ type: "scroll", timestamp: Date.now(), y: Math.round(window.scrollY) });
    window.addEventListener("scroll", onScroll, { passive: true });
    this.detach.push(() => window.removeEventListener("scroll", onScroll));
  }

  stop(): void {
    this.detach.forEach((undo) => undo());
    this.detach = [];
    this.buffer = [];
  }

  private push(event: TelemetryEvent): void {
    this.total += 1;
    this.buffer.push(event);
    if (this.buffer.length > BUFFER_LIMIT) this.buffer.splice(0, this.buffer.length - BUFFER_LIMIT);
  }

  /** Input events since the page loaded (count) and the recent window (events). */
  snapshot(): { events: TelemetryEvent[]; event_count: number } {
    return { events: this.buffer.slice(), event_count: this.total };
  }

  count(): number {
    return this.total;
  }
}
