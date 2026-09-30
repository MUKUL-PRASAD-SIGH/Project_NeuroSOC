import { useEffect, useRef, useState } from "react";
// Shared bits for the SDK protection page. Status colors always travel with a text label.
export const VERDICT_STYLE = {
  ok: { label: "OK", className: "border-soc-green/40 bg-soc-green/10 text-soc-green", icon: "✓" },
  review: { label: "Review", className: "border-soc-amber/40 bg-soc-amber/10 text-soc-amber", icon: "!" },
  suspected_bot: { label: "Suspected bot", className: "border-soc-red/40 bg-soc-red/10 text-soc-red", icon: "✕" },
  bot_farm: { label: "Bot farm", className: "border-soc-red/40 bg-soc-red/10 text-soc-red", icon: "✕" },
  agent_anomaly: { label: "Agent paused", className: "border-soc-red/40 bg-soc-red/10 text-soc-red", icon: "■" },
};

export function VerdictBadge({ verdict }) {
  const style = VERDICT_STYLE[verdict] || { label: verdict, className: "border-soc-border text-soc-muted", icon: "·" };
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-2 py-0.5 text-[11px] font-medium ${style.className}`}>
      <span aria-hidden="true">{style.icon}</span>
      {style.label}
    </span>
  );
}

// What actually happened to the action. A flagged action on a site in Monitor mode was recorded, not stopped.
export const DECISION_STYLE = {
  allowed: { label: "Allowed", className: "border-soc-green/40 bg-soc-green/10 text-soc-green", icon: "✓" },
  flagged: { label: "Flagged (monitor)", className: "border-soc-amber/40 bg-soc-amber/10 text-soc-amber", icon: "!" },
  blocked: { label: "Blocked", className: "border-soc-red/40 bg-soc-red/10 text-soc-red", icon: "■" },
  shadowed: { label: "Shadowed", className: "border-soc-red/40 bg-soc-red/10 text-soc-red", icon: "✕" },
  step_up: { label: "Step-up required", className: "border-soc-amber/40 bg-soc-amber/10 text-soc-amber", icon: "!" },
};

export function decisionOf(verdict) {
  if (!verdict || verdict.action === "allow" || !verdict.action) return "allowed";
  if (verdict.enforced === false) return "flagged";
  return { pause_agent: "blocked", shadow: "shadowed", step_up: "step_up" }[verdict.action] || "flagged";
}

export function DecisionBadge({ verdict }) {
  const style = DECISION_STYLE[decisionOf(verdict)];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-2 py-0.5 text-[11px] font-medium ${style.className}`}>
      <span aria-hidden="true">{style.icon}</span>
      {style.label}
    </span>
  );
}

export function riskLevel(risk) {
  const value = Number(risk) || 0;
  return value >= 0.6 ? "High" : value >= 0.3 ? "Medium" : "Low";
}

export function RiskMeter({ risk }) {
  const value = Math.max(0, Math.min(1, Number(risk) || 0));
  const level = riskLevel(value);
  return (
    <span className="inline-flex items-center justify-end gap-2" title={`Risk ${value.toFixed(2)}`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-soc-border" aria-hidden="true">
        <span className="block h-full rounded-full bg-soc-electric" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="w-[4.5rem] text-left font-mono text-xs text-soc-text soc-tabular">{value.toFixed(2)} {level}</span>
    </span>
  );
}

export function fullTime(seconds) {
  return new Date(Number(seconds) * 1000).toLocaleString();
}

export function shortId(id) {
  const text = String(id || "");
  return text.length > 14 ? `${text.slice(0, 6)}…${text.slice(-4)}` : text;
}

export function timeOf(seconds) {
  return new Date(Number(seconds) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function StatTile({ label, value, tone = "text-soc-text", hint }) {
  return (
    <div className="soc-inset px-4 py-3">
      <p className="soc-kicker">{label}</p>
      <p className={`mt-1 font-mono text-2xl font-semibold soc-tabular ${tone}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-soc-muted">{hint}</p> : null}
    </div>
  );
}

export function EmptyState({ title, children }) {
  return (
    <div className="soc-glass p-6 text-sm text-soc-muted">
      <p className="soc-section-title">{title}</p>
      <div className="mt-2 max-w-2xl leading-relaxed">{children}</div>
    </div>
  );
}

export function CopyButton({ value, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button type="button" className="soc-btn" onClick={copy} aria-label={`${label} to clipboard`}>
      {copied ? "Copied" : label}
    </button>
  );
}

export function CodeBlock({ code, label }) {
  return (
    <div className="soc-inset relative">
      <div className="absolute right-2 top-2"><CopyButton value={code} label="Copy" /></div>
      <pre className="overflow-x-auto p-4 pr-20 text-xs leading-relaxed text-soc-text" aria-label={label}><code>{code}</code></pre>
    </div>
  );
}

// An accessible modal: role=dialog, labelled, Escape closes, focus moves in and is restored, Tab is trapped.
export function Modal({ title, onClose, children, closeLabel = "Close" }) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose; // a fresh onClose must not re-run the focus effect below
  useEffect(() => {
    const previous = document.activeElement;
    const node = ref.current;
    const focusable = () => node.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    (focusable()[0] || node).focus();
    function onKey(event) {
      if (event.key === "Escape") { event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const items = [...focusable()].filter((el) => !el.disabled);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    node.addEventListener("keydown", onKey);
    return () => { node.removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, []);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm">
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby="modal-title" tabIndex={-1}
        className="soc-glass my-8 w-full max-w-3xl p-6 outline-none">
        <div className="flex items-start justify-between gap-4">
          <h2 id="modal-title" className="soc-section-title">{title}</h2>
          <button type="button" className="soc-btn" onClick={onClose}>{closeLabel}</button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
