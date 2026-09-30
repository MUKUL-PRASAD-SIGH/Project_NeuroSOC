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
