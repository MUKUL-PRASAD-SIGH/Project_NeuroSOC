import { useEffect, useState } from "react";
import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import { OIDC_REQUIRED } from "../lib/auth";
import { DEMO_DATA_ENABLED } from "../lib/featureFlags";
import { getSandboxReplay, submitAlertDecision } from "../services/dashboardApi";
import { useDashboardStore } from "../store/dashboardStore";

const RESPONSE_ROLES = new Set(["operator", "admin"]);

const DECISION_OPTIONS = [
  { value: "confirm_threat", label: "Confirm threat", tone: "border-soc-red/50 text-soc-red hover:bg-soc-red/10" },
  { value: "false_positive", label: "False positive", tone: "border-soc-green/50 text-soc-green hover:bg-soc-green/10" },
  { value: "restore_access", label: "Restore access", tone: "border-soc-amber/50 text-soc-amber hover:bg-soc-amber/10" },
  { value: "escalate", label: "Escalate", tone: "border-soc-electric/50 text-soc-electric hover:bg-soc-electric/10" },
];

const statusLabel = {
  new: "Awaiting review",
  triaged: "Triaged",
  closed: "Closed",
};

function DecisionPanel({ alert }) {
  const applyAlertDecision = useDashboardStore((state) => state.applyAlertDecision);
  const { roles } = useDashboardStore((state) => state.auth);
  const canDecide = !OIDC_REQUIRED || roles.some((role) => RESPONSE_ROLES.has(role));
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);

  async function handleDecision(decision) {
    setPending(decision);
    setError(null);
    try {
      const result = await submitAlertDecision(alert.id, decision);
      applyAlertDecision(alert.id, { status: result.status, decision: result.decision });
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not record this decision. Try again.");
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="mt-5 rounded-2xl border border-soc-border/80 bg-soc-panelSoft/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-soc-muted">Analyst decision</p>
        <span className="rounded-full border border-soc-border/60 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.14em] text-soc-muted">
          {statusLabel[alert.status] || "Awaiting review"}
        </span>
      </div>
      {alert.decision ? (
        <p className="mt-2 text-xs text-soc-muted">
          Last decision: <span className="text-soc-text">{alert.decision.replace(/_/g, " ")}</span>
        </p>
      ) : null}
      {canDecide ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {DECISION_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={pending !== null}
              onClick={() => handleDecision(option.value)}
              className={`rounded-xl border px-3 py-1.5 text-xs font-medium transition disabled:opacity-50 ${option.tone}`}
            >
              {pending === option.value ? "Saving…" : option.label}
            </button>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-soc-muted">Sign in with an operator or admin role to record a decision.</p>
      )}
      {error ? <p className="mt-2 text-xs text-soc-red">{error}</p> : null}
    </section>
  );
}

const verdictTone = {
  HACKER: "text-soc-red",
  FORGETFUL_USER: "text-soc-amber",
  LEGITIMATE: "text-soc-green",
  INCONCLUSIVE: "text-soc-muted",
};

const verdictBadge = {
  HACKER: "border-soc-red/50 bg-soc-red/12 text-soc-red",
  FORGETFUL_USER: "border-soc-amber/50 bg-soc-amber/12 text-soc-amber",
  LEGITIMATE: "border-soc-green/45 bg-soc-green/12 text-soc-green",
  INCONCLUSIVE: "border-soc-border bg-soc-panelSoft/40 text-soc-muted",
};

const verdictHeadline = {
  HACKER: "Threat",
  FORGETFUL_USER: "Review — unusual sign-in pattern",
  LEGITIMATE: "Normal",
  INCONCLUSIVE: "Insufficient Signal",
};

const verdictExplain = {
  HACKER: (a) =>
    `This session was flagged as a likely threat with a ${Math.round((a.score || 0) * 100)}% risk score. ` +
    `Review the available event evidence and record a decision. Captured sandbox activity appears below when available.`,
  FORGETFUL_USER: (a) =>
    `This session was flagged for review with a ${Math.round((a.score || 0) * 100)}% risk score. ` +
    `Review the available sign-in evidence before choosing whether to restore access or escalate.`,
  LEGITIMATE: (a) =>
    `This session was classified as normal with a ${Math.round((a.score || 0) * 100)}% risk score. ` +
    `Review the returned event details if you need to override the result.`,
  INCONCLUSIVE: (a) =>
    `The returned evidence is not enough to classify this session confidently (${Math.round((a.score || 0) * 100)}% risk). ` +
    `Keep it under review until more signal is available.`,
};

function ModelBreakdown({ raw }) {
  if (!raw) return null;
  const rows = [
    {
      label: "SNN Spike Score",
      value: `${Math.round((raw.snn_score || 0) * 100)}%`,
      note: raw.snn_score > 0.5 ? "Anomalous burst detected" : "No spike anomaly",
      bad: raw.snn_score > 0.5,
    },
    {
      label: "LNN Behaviour Class",
      value: raw.lnn_class || "—",
      note: raw.lnn_class === "BENIGN" ? "Matches known profile" : "Deviates from baseline",
      bad: raw.lnn_class !== "BENIGN",
    },
    {
      label: "XGBoost Traffic Class",
      value: raw.xgb_class || "—",
      note: raw.xgb_class === "BENIGN" ? "Normal traffic pattern" : "Flagged traffic type",
      bad: raw.xgb_class !== "BENIGN",
    },
    {
      label: "Behavioural Drift",
      value: `${Math.round((raw.behavioral_delta || 0) * 100)}%`,
      note: raw.behavioral_delta > 0.3 ? "High drift from user baseline" : "Within normal range",
      bad: raw.behavioral_delta > 0.3,
    },
    {
      label: "Final Confidence",
      value: `${Math.round((raw.confidence || 0) * 100)}%`,
      note: "Weighted fusion of all three models",
      bad: false,
    },
  ];

  return (
    <div className="mt-4 space-y-2">
      {rows.map((row) => (
        <div
          key={row.label}
          className="flex items-center justify-between rounded-xl border border-soc-border/60 bg-soc-panel/50 px-3 py-2"
        >
          <div>
            <p className="text-xs font-medium text-soc-text">{row.label}</p>
            <p className="text-[11px] text-soc-muted">{row.note}</p>
          </div>
          <span
            className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
              row.bad
                ? "bg-soc-red/15 text-soc-red"
                : "bg-soc-green/15 text-soc-green"
            }`}
          >
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function TopFeatures({ explanation }) {
  const features = explanation?.topFeatures;
  if (!features?.length) return null;
  const maxAbsImpact = Math.max(...features.map((item) => Math.abs(item.impact)), 0.0001);

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-soc-muted">
          Top contributing features {explanation.method === "shap" ? "(SHAP)" : "(by magnitude)"}
        </p>
      </div>
      <div className="mt-2 space-y-1.5">
        {features.map((item) => (
          <div key={item.feature} className="flex items-center gap-2 text-xs">
            <span className="w-28 shrink-0 truncate  text-[11px] text-soc-text" title={item.feature}>
              {item.feature}
            </span>
            <div className="h-1.5 flex-1 rounded-full bg-soc-panelSoft">
              <div
                className={`h-1.5 rounded-full ${item.impact >= 0 ? "bg-soc-red" : "bg-soc-electric"}`}
                style={{ width: `${Math.max((Math.abs(item.impact) / maxAbsImpact) * 100, 4)}%` }}
              />
            </div>
            <span className="soc-tabular w-14 shrink-0 text-right  text-[11px] text-soc-muted">
              {item.value.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function VerdictHistory({ recentVerdicts }) {
  if (!recentVerdicts?.length) return null;
  return (
    <div className="mt-4 space-y-2">
      {recentVerdicts.map((item, i) => (
        <div
          key={item.id || i}
          className="flex items-center justify-between rounded-xl border border-soc-border/60 bg-soc-panel/50 px-3 py-2"
        >
          <div className="flex items-center gap-2">
            <span className={`text-sm font-medium ${verdictTone[item.verdict] || "text-soc-muted"}`}>
              {item.verdict?.replace(/_/g, " ") || "UNKNOWN"}
            </span>
            <span className="text-[11px] text-soc-muted">
              {new Date(item.timestamp).toLocaleString([], {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
          <span className="text-xs text-soc-muted">
            {Math.round((item.score || 0) * 100)}% risk
          </span>
        </div>
      ))}
    </div>
  );
}

const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function describeSandboxAction(action) {
  const body = action.body || {};
  if (body.event === "diverted_to_sandbox") {
    return {
      title: "Session diverted to decoy vault",
      detail: `${body.failed_logins} failed sign-ins with ${body.distinct_passwords} different passwords; attacker was shown a successful login.`,
      tone: "text-soc-amber",
    };
  }
  if (action.path?.includes("/transfer")) {
    return {
      title: `Transfer attempt · ${currency.format(Number(body.amount) || 0)}`,
      detail: `To ${body.destination || "unknown account"}. Confirmed to the attacker; no funds moved.`,
      tone: "text-soc-red",
    };
  }
  if (action.path?.includes("web-attack")) {
    return { title: `Web attack · ${body.attack_type || "payload"}`, detail: body.payload || "", tone: "text-soc-red" };
  }
  if (action.path?.includes("honeypot")) {
    return { title: "Honeypot field touched", detail: `Source: ${body.source || "form"}`, tone: "text-soc-red" };
  }
  return { title: `${action.method} ${action.path}`, detail: "", tone: "text-soc-muted" };
}

function SandboxActivity({ sessionId }) {
  const [replay, setReplay] = useState(undefined);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const data = await getSandboxReplay(sessionId);
      if (!cancelled) setReplay(data);
    };
    load();
    // Keep the timeline live while the attacker is still inside the decoy.
    const timer = window.setInterval(load, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId]);

  const actions = replay?.actions || [];

  return (
    <section className="mt-5 rounded-2xl border border-soc-red/30 bg-soc-red/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-soc-muted">Sandbox activity</p>
        {replay?.sandbox_token ? (
          <span className=" text-[11px] text-soc-muted">{replay.sandbox_token}</span>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-soc-muted">Everything this session did inside the decoy environment.</p>
      {replay === undefined ? (
        <p className="mt-4 text-sm text-soc-muted">Loading captured activity…</p>
      ) : actions.length ? (
        <ol className="mt-4 space-y-3">
          {actions.map((action, index) => {
            const item = describeSandboxAction(action);
            return (
              <li key={`${action.timestamp}-${index}`} className="flex gap-3">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-soc-red/80" />
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${item.tone}`}>
                    {item.title}
                    <span className="ml-2 text-xs font-normal text-soc-muted">
                      {new Date(Number(action.timestamp) * 1000).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                  </p>
                  {item.detail ? <p className="mt-0.5 break-words text-xs text-soc-muted">{item.detail}</p> : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="mt-4 text-sm text-soc-muted">No sandbox activity captured for this session.</p>
      )}
    </section>
  );
}

export default function UserProfileModal() {
  const modal = useDashboardStore((state) => state.modal);
  const closeUserModal = useDashboardStore((state) => state.closeUserModal);
  const [showRaw, setShowRaw] = useState(false);
  const alert = modal.selectedAlert;

  if (!modal.open || !alert) return null;

  const verdict = alert.verdict || "INCONCLUSIVE";
  const explain = alert.explanation?.summary || (verdictExplain[verdict] || verdictExplain.INCONCLUSIVE)(alert);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="soc-glass max-h-[92vh] w-full max-w-5xl overflow-y-auto p-5 md:p-6">

        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="soc-kicker">Session Analysis</p>
            <h2 className="mt-2 text-2xl font-medium text-soc-text">
              {alert.userName || alert.userId || alert.sourceIp}
            </h2>
            <p className="mt-1 text-sm text-soc-muted">
              {alert.sourceIp} · {alert.locationLabel}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowRaw((v) => !v)}
              className="rounded-full border border-soc-border/60 bg-soc-panelSoft/40 px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] text-soc-muted transition hover:border-soc-electric/40 hover:text-soc-text"
            >
              {showRaw ? "Summary" : "JSON"}
            </button>
            <button
              type="button"
              onClick={closeUserModal}
              className="rounded-full border border-soc-border/80 bg-soc-panelSoft/60 px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] text-soc-muted transition hover:border-soc-electric/40 hover:text-soc-text"
            >
              Close
            </button>
          </div>
        </div>

        {/* JSON mode */}
        {showRaw ? (
          <pre className="mt-5 max-h-[60vh] overflow-auto rounded-xl border border-soc-border/60 bg-soc-panel/80 p-4 text-[11px] leading-relaxed text-soc-muted">
            {JSON.stringify(alert, null, 2)}
          </pre>
        ) : (
          <>
            {/* Verdict summary banner */}
            <div className="mt-5 rounded-xl border border-soc-border/60 bg-soc-panelSoft/40 p-4">
              <div className="flex items-center gap-3">
                <span
                  className={`rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] ${
                    verdictBadge[verdict] || verdictBadge.INCONCLUSIVE
                  }`}
                >
                  {verdictHeadline[verdict] || verdict.replace(/_/g, " ")}
                </span>
                <span className="text-sm text-soc-muted">
                  Risk score: <span className="font-medium text-soc-text">{Math.round((alert.score || 0) * 100)}%</span>
                </span>
                {alert.modelVersion && (
                  <span className="text-xs text-soc-muted">Model: {alert.modelVersion}</span>
                )}
              </div>
              <p className="mt-3 text-sm leading-relaxed text-soc-text">{explain}</p>
            </div>

            <div className="mt-5 grid gap-5 xl:grid-cols-[1.25fr_0.95fr]">

              {/* Left — radar + model breakdown */}
              <section className="rounded-2xl border border-soc-border/80 bg-soc-panelSoft/40 p-4">
                <p className="text-xs font-medium text-soc-muted">
                  {DEMO_DATA_ENABLED ? "Illustrative Signal Profile" : "Behavioural Signal Radar"}
                </p>
                <p className="mt-1 text-xs text-soc-muted">
                  {DEMO_DATA_ENABLED
                    ? "Sample values show where session signals will appear; these are not Colab model outputs."
                    : "Normalised signals returned with this session. Higher values are more anomalous."}
                </p>
                <div className="mt-3 h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={alert.dimensions}>
                      <PolarGrid stroke="rgba(94, 120, 163, 0.2)" />
                      <PolarAngleAxis dataKey="subject" tick={{ fill: "#8a93a8", fontSize: 10 }} />
                      <Radar
                        name="Behavior"
                        dataKey="value"
                        stroke="#5b93ff"
                        fill="#5b93ff"
                        fillOpacity={0.3}
                      />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>

                <p className="mt-4 text-xs font-medium text-soc-muted">
                  Model Breakdown
                </p>
                {DEMO_DATA_ENABLED && !alert.raw ? (
                  <p className="mt-2 text-xs leading-relaxed text-soc-muted">
                    Model-level scores will appear here when the Colab inference output is connected.
                  </p>
                ) : <ModelBreakdown raw={alert.raw} />}
                <TopFeatures explanation={alert.explanation} />
              </section>

              {/* Right — verdict history */}
              <section className="rounded-2xl border border-soc-border/80 bg-soc-panelSoft/40 p-4">
                <p className="text-xs font-medium text-soc-muted">
                  Recent Session History
                </p>
                <p className="mt-1 text-xs text-soc-muted">
                  Last {alert.recentVerdicts?.length || 0} verdicts for this user.
                </p>
                {alert.recentVerdicts?.length ? (
                  <VerdictHistory recentVerdicts={alert.recentVerdicts} />
                ) : (
                  <p className="mt-4 text-sm text-soc-muted">No history available for this session.</p>
                )}
              </section>
            </div>

            {verdict === "HACKER" ? <DecisionPanel alert={alert} /> : null}
            {verdict === "HACKER" ? <SandboxActivity sessionId={alert.id} /> : null}
          </>
        )}
      </div>
    </div>
  );
}
