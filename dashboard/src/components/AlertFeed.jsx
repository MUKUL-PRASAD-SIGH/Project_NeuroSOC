import { useMemo, useState } from "react";
import { useDashboardStore } from "../store/dashboardStore";

const verdictTone = {
  HACKER: "border-soc-red/40 bg-soc-red/10 text-soc-red",
  FORGETFUL_USER: "border-soc-amber/40 bg-soc-amber/10 text-soc-amber",
  LEGITIMATE: "border-soc-green/40 bg-soc-green/10 text-soc-green",
  INCONCLUSIVE: "border-soc-border bg-soc-panelSoft text-soc-muted",
};

const verdictRail = {
  HACKER: "border-l-soc-red",
  FORGETFUL_USER: "border-l-soc-amber",
  LEGITIMATE: "border-l-soc-green",
  INCONCLUSIVE: "border-l-soc-border",
};

const verdictBar = {
  HACKER: "bg-soc-red",
  FORGETFUL_USER: "bg-soc-amber",
  LEGITIMATE: "bg-soc-green",
  INCONCLUSIVE: "bg-soc-muted",
};

const verdictLabel = {
  HACKER: "Threat",
  FORGETFUL_USER: "Review",
  LEGITIMATE: "Normal",
  INCONCLUSIVE: "Monitoring",
};

const pct = (value) => Math.round((Number(value) || 0) * 100);

const verdictSummary = {
  HACKER: (a) =>
    `Session from ${a.sourceIp}${a.locationLabel ? ` (${a.locationLabel})` : ""} classified as an attacker. Diverted to sandbox.`,
  FORGETFUL_USER: (a) =>
    `${a.userName || a.sourceIp} showed unusual behaviour without matching an attack pattern. Likely a locked-out user.`,
  LEGITIMATE: (a) => `${a.userName || a.sourceIp} passed all checks. No action needed.`,
  INCONCLUSIVE: (a) => `Insufficient signal for ${a.sourceIp}. Session remains under observation.`,
};

const ALERT_CAP = 50;

function formatAlertTime(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function AlertCard({ alert, onOpen }) {
  const [showRaw, setShowRaw] = useState(false);
  const verdict = alert.verdict || "INCONCLUSIVE";
  const summary = (verdictSummary[verdict] || verdictSummary.INCONCLUSIVE)(alert);

  const risk = pct(alert.score);

  return (
    <div
      className={`rounded-md border border-l-[3px] border-soc-border/80 bg-soc-panelSoft/50 p-3.5 transition-colors hover:bg-soc-panelSoft ${
        verdictRail[verdict] || verdictRail.INCONCLUSIVE
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${
              verdictTone[verdict] || verdictTone.INCONCLUSIVE
            }`}
          >
            {verdictLabel[verdict] || verdict.replace(/_/g, " ")}
          </span>
          <span className="truncate text-sm font-medium text-soc-text">{alert.userName || alert.sourceIp}</span>
        </div>
        <span className="soc-tabular shrink-0 font-mono text-[11px] text-soc-muted">{formatAlertTime(alert.timestamp)}</span>
      </div>

      {showRaw ? (
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-soc-bg p-3 font-mono text-[11px] leading-relaxed text-soc-muted">
          {JSON.stringify(alert, null, 2)}
        </pre>
      ) : (
        <p className="mt-2 text-[13px] leading-relaxed text-soc-muted">{summary}</p>
      )}

      <div className="mt-3 flex items-center gap-3">
        <div className="flex flex-1 items-center gap-2">
          <div className="h-1 flex-1 rounded-full bg-soc-border/70">
            <div
              className={`h-1 rounded-full ${verdictBar[verdict] || verdictBar.INCONCLUSIVE}`}
              style={{ width: `${Math.min(Math.max(risk, 2), 100)}%` }}
            />
          </div>
          <span className="soc-tabular w-16 text-right font-mono text-[11px] text-soc-muted">risk {risk}%</span>
        </div>
        <div className="flex gap-1.5">
          <button type="button" onClick={() => setShowRaw((v) => !v)} className="soc-btn px-2 py-1 text-[11px]">
            {showRaw ? "Summary" : "JSON"}
          </button>
          <button type="button" onClick={() => onOpen(alert)} className="soc-btn-primary px-2 py-1 text-[11px]">
            Inspect
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AlertFeed({ maxItems = null, showHeader = true, items: alertItems = null }) {
  const storedAlerts = useDashboardStore((state) => state.alerts.items);
  const alerts = alertItems ?? storedAlerts;
  const loading = useDashboardStore((state) => state.alerts.loading);
  const status = useDashboardStore((state) => state.alerts.status);
  const openUserModal = useDashboardStore((state) => state.openUserModal);

  const sortedAlerts = useMemo(() => {
    const next = [...alerts].sort((a, b) => {
      const tA = new Date(a.timestamp).getTime() || 0;
      const tB = new Date(b.timestamp).getTime() || 0;
      return tB - tA;
    });
    const capped = next.slice(0, ALERT_CAP);
    return maxItems ? capped.slice(0, maxItems) : capped;
  }, [alerts, maxItems]);

  return (
    <section className="soc-glass flex h-full min-h-[360px] flex-col p-5">
      {showHeader && (
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="soc-section-title">Alert queue</h2>
            <p className="mt-0.5 text-xs text-soc-muted">
              {sortedAlerts.length} most recent · newest first
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 text-xs capitalize text-soc-muted">
            <span className={status === "connected" ? "soc-live-dot" : "inline-block h-2 w-2 rounded-full bg-soc-amber"} />
            {loading ? "Loading" : status || "Idle"}
          </span>
        </div>
      )}

      <div className="max-h-[520px] flex-1 space-y-2 overflow-y-auto pr-1">
        {loading && sortedAlerts.length === 0 &&
          [0, 1, 2].map((i) => <div key={i} className="h-[104px] animate-pulse rounded-md bg-soc-panelSoft/60" />)}
        {!loading && sortedAlerts.length === 0 && (
          <div className="rounded-md border border-dashed border-soc-border p-6 text-center text-sm text-soc-muted">
            No alerts yet. New verdicts will appear here as they arrive.
          </div>
        )}
        {sortedAlerts.map((alert) => (
          <AlertCard
            key={`${alert.id}-${alert.timestamp}`}
            alert={alert}
            onOpen={openUserModal}
          />
        ))}
      </div>
    </section>
  );
}
