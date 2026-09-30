import type { Rule, TrackInput } from "./types";

/** "*campaign*" style globs against the page path (and full URL when the glob has a scheme). */
export function urlMatches(glob: string | undefined, location: Location): boolean {
  if (!glob || glob === "*") return true;
  const subject = glob.includes("://") ? location.href : location.pathname + location.search;
  const pattern = "^" + glob.split("*").map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$";
  return new RegExp(pattern, "i").test(subject);
}

function visibleText(element: Element): string {
  const own = (element as HTMLElement).innerText ?? element.textContent ?? "";
  const aria = element.getAttribute("aria-label") ?? "";
  const value = element instanceof HTMLInputElement ? element.value : "";
  return `${own} ${aria} ${value}`.replace(/\s+/g, " ").trim().toLowerCase();
}

const CLICKABLE = "button, a, [role=button], input[type=submit], input[type=button], [data-task], [onclick]";

function textMatches(element: Element, text: string | string[] | undefined): boolean {
  if (!text) return true;
  const wanted = (Array.isArray(text) ? text : [text]).map((t) => t.toLowerCase());
  const label = visibleText(element);
  // Short labels only: a whole card that happens to contain "buy" somewhere is not a buy button.
  if (!label || label.length > 60) return false;
  return wanted.some((word) => label === word || label.startsWith(word + " ") || label.includes(word));
}

/** The element a rule is about: the clicked control, or the submitted form. */
export function findRule(rules: Rule[], event: Event, location: Location): { rule: Rule; element: Element } | null {
  const kind = event.type === "submit" ? "submit" : "click";
  const origin = event.target instanceof Element ? event.target : null;
  if (!origin) return null;
  for (const rule of rules) {
    const match = rule.match || {};
    if ((match.event || "click") !== kind) continue;
    if (!urlMatches(match.url, location)) continue;
    let element: Element | null = kind === "submit" ? origin.closest("form") : origin.closest(CLICKABLE);
    if (!element) continue;
    if (match.selector) {
      element = kind === "submit" ? (element.matches(match.selector) ? element : null) : origin.closest(match.selector);
      if (!element) continue;
    }
    if (match.has && !element.querySelector(match.has)) continue;
    if (!textMatches(element, match.text)) continue;
    return { rule, element };
  }
  return null;
}

function resolve(spec: string | undefined, element: Element, location: Location): string | null {
  if (!spec) return location.pathname || "/";
  const [kind, ...rest] = spec.split(":");
  const arg = rest.join(":");
  if (kind === "const") return arg;
  if (kind === "attr") {
    const holder = element.closest(`[${CSS.escape(arg)}]`) || document.querySelector(`[${CSS.escape(arg)}]`);
    return holder?.getAttribute(arg) ?? null;
  }
  if (kind === "url") {
    if (arg === "path" || arg === "") return location.pathname || "/";
    const segments = location.pathname.split("/").filter(Boolean);
    const index = Number(arg) - 1;
    return Number.isInteger(index) && segments[index] ? segments[index] : location.pathname || "/";
  }
  return null;
}

export function toTrackInput(rule: Rule, element: Element, location: Location): TrackInput | null {
  const id = resolve(rule.resource.id_from, element, location);
  if (!id) return null;
  const input: TrackInput = {
    action: rule.action,
    resource: { id: id.slice(0, 256), type: rule.resource.type, ...(rule.resource.sensitivity ? { sensitivity: rule.resource.sensitivity } : {}) },
  };
  if (rule.value_from) {
    const amount = Number(resolve(rule.value_from, element, location));
    if (Number.isFinite(amount) && amount >= 0) input.value = { amount };
  }
  return input;
}
