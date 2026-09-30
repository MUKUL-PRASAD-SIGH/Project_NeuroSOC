import { useMemo, useState } from "react";
import { overrideVerdict } from "../../services/universalApi";
import { DecisionBadge, EmptyState, RiskMeter, VerdictBadge, decisionOf, fullTime, riskLevel, shortId, timeOf } from "./shared";

// The eight things an analyst needs on one line: which application, which agent, what it tried to do,
// to what, what NeuroSOC decided, how risky, why, and when.
function agentOf(v) {
  return v.agent_id || (v.entity ? `${v.entity.type} ${shortId(v.entity.id)}` : "-");
}

function LatestEvent({ verdict }) {
  const fields = [
    ["Application", verdict.site_name || "-"],
    ["Agent", agentOf(verdict)],
    ["Action", verdict.event_action],
    ["Resource", verdict.resource?.id || "-"],
    ["Risk", `${riskLevel(verdict.risk)} (${Number(verdict.risk).toFixed(2)})`],
    ["Timestamp", fullTime(verdict.timestamp)],
  ];
  return (
    <div className="soc-inset mt-4 p-4" role="status" aria-live="polite" aria-label="Latest security event">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="soc-kicker">{decisionOf(verdict) === "allowed" ? "Latest event" : "Latest security event"}</p>
        <span className="flex items-center gap-2"><DecisionBadge verdict={verdict} /><VerdictBadge verdict={verdict.verdict} /></span>
      </div>
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-soc-muted">{label}</dt>
            <dd className="mt-0.5 break-all font-mono text-soc-text">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-soc-muted">Reason</p>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-xs leading-snug text-soc-text">
        {(verdict.reasons || []).map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
    </div>
  );
}

export default function LiveVerdicts({ verdicts, onUpdated }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [application, setApplication] = useState("all");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const applications = useMemo(
    () => [...new Set(verdicts.map((v) => v.site_name).filter(Boolean))].sort(),
    [verdicts]
  );
  const visible = useMemo(
    () => verdicts.filter((v) => (!flaggedOnly || v.verdict !== "ok") && (application === "all" || v.site_name === application)),
    [verdicts, flaggedOnly, application]
  );
  const rows = visible.slice(0, 50);
  // Show the most recent thing worth looking at: the newest flagged event, else the newest event.
  const spotlight = visible.find((v) => v.verdict !== "ok") || visible[0];

  async function decide(verdict, decision) {
    setBusy(verdict.verdict_id);
    setError(null);
    try {
      onUpdated(await overrideVerdict(verdict.verdict_id, decision));
    } catch (err) {
      setError(err?.response?.data?.detail || "That action failed.");
    } finally {
      setBusy(null);
    }
  }

  if (!verdicts.length) {
    return (
      <EmptyState title="No SDK events yet">
        Add an application under <strong>Applications</strong>, then open the NovaTrust demo (or add the script tag to a site).
        Events appear here the moment they happen.
      </EmptyState>
    );
  }

  return (
    <section className="soc-glass p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="soc-section-title">Live verdicts</h2>
          <p className="text-xs text-soc-muted">Every action seen by the SDK, newest first, with the reason in plain words.</p>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs text-soc-muted">
          {applications.length > 1 ? (
            <label className="flex items-center gap-2">
              Application
              <select className="soc-inset px-2 py-1 text-soc-text" value={application} onChange={(e) => setApplication(e.target.value)}>
                <option value="all">All</option>
                {applications.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          ) : null}
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
            Flagged only
          </label>
        </div>
      </div>
      {error ? <p className="mt-3 text-xs text-soc-red" role="alert">{error}</p> : null}
      {spotlight ? <LatestEvent verdict={spotlight} /> : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[1040px] text-left text-sm">
          <caption className="sr-only">Live NeuroSOC verdicts</caption>
          <thead className="text-[11px] uppercase tracking-[0.08em] text-soc-muted">
            <tr className="border-b border-soc-border">
              <th scope="col" className="py-2 pr-3 font-medium">Time</th>
              <th scope="col" className="py-2 pr-3 font-medium">Application</th>
              <th scope="col" className="py-2 pr-3 font-medium">Agent</th>
              <th scope="col" className="py-2 pr-3 font-medium">Action</th>
              <th scope="col" className="py-2 pr-3 font-medium">Resource</th>
              <th scope="col" className="py-2 pr-3 font-medium">Decision</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Risk</th>
              <th scope="col" className="py-2 pr-3 font-medium">Reason</th>
              <th scope="col" className="py-2 font-medium"><span className="sr-only">Analyst action</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.verdict_id} className="border-b border-soc-border/60 align-top">
                <td className="py-2 pr-3 font-mono text-xs text-soc-muted soc-tabular" title={fullTime(v.timestamp)}>{timeOf(v.timestamp)}</td>
                <td className="py-2 pr-3 text-xs text-soc-text">{v.site_name || "-"}</td>
                <td className="py-2 pr-3 font-mono text-xs text-soc-text" title={v.agent_id || v.entity?.id}>
                  {agentOf(v)}
                  {v.tool ? <span className="block text-[11px] text-soc-muted">{v.tool}</span> : null}
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-soc-text">{v.event_action}</td>
                <td className="py-2 pr-3 font-mono text-xs text-soc-muted" title={v.resource?.id}>{shortId(v.resource?.id)}</td>
                <td className="py-2 pr-3"><DecisionBadge verdict={v} /></td>
                <td className="py-2 pr-3 text-right"><RiskMeter risk={v.risk} /></td>
                <td className="max-w-[340px] py-2 pr-3 text-xs leading-snug text-soc-muted">
                  {v.override ? <span className="text-soc-text">Analyst: {v.override.decision}. </span> : null}
                  {v.reasons?.length > 1 ? (
                    <details>
                      <summary className="cursor-pointer">{v.reasons[0]}</summary>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4">{v.reasons.slice(1).map((r) => <li key={r}>{r}</li>)}</ul>
                    </details>
                  ) : v.reasons?.[0]}
                </td>
                <td className="py-2 text-right">
                  {v.verdict !== "ok" && !v.override ? (
                    <div className="flex justify-end gap-1.5">
                      <button type="button" className="soc-btn" disabled={busy === v.verdict_id} onClick={() => decide(v, "restore")}>Restore</button>
                      <button type="button" className="soc-btn" disabled={busy === v.verdict_id} onClick={() => decide(v, "confirm")}>Confirm</button>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
