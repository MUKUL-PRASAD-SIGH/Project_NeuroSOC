import { useMemo, useState } from "react";
import { overrideVerdict } from "../../services/universalApi";
import { EmptyState, VerdictBadge, shortId, timeOf } from "./shared";

export default function LiveVerdicts({ verdicts, onUpdated }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const rows = useMemo(
    () => verdicts.filter((v) => !flaggedOnly || v.verdict !== "ok").slice(0, 50),
    [verdicts, flaggedOnly]
  );

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
        Add the script tag to a site, or run <code>python attack_patterns/human_seed.py</code> against the example campaign.
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
        <label className="flex items-center gap-2 text-xs text-soc-muted">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
          Flagged only
        </label>
      </div>
      {error ? <p className="mt-3 text-xs text-soc-red">{error}</p> : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-[0.08em] text-soc-muted">
            <tr className="border-b border-soc-border">
              <th className="py-2 pr-3 font-medium">Time</th>
              <th className="py-2 pr-3 font-medium">Entity</th>
              <th className="py-2 pr-3 font-medium">Action</th>
              <th className="py-2 pr-3 font-medium">Resource</th>
              <th className="py-2 pr-3 font-medium">Verdict</th>
              <th className="py-2 pr-3 text-right font-medium">Risk</th>
              <th className="py-2 pr-3 font-medium">Why</th>
              <th className="py-2 font-medium"><span className="sr-only">Decision</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.verdict_id} className="border-b border-soc-border/60 align-top">
                <td className="py-2 pr-3 font-mono text-xs text-soc-muted soc-tabular">{timeOf(v.timestamp)}</td>
                <td className="py-2 pr-3 font-mono text-xs text-soc-text" title={v.entity.id}>
                  <span className="text-soc-muted">{v.entity.type} </span>{shortId(v.entity.id)}
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-soc-text">{v.event_action}</td>
                <td className="py-2 pr-3 text-xs text-soc-muted" title={v.resource.id}>{shortId(v.resource.id)}</td>
                <td className="py-2 pr-3"><VerdictBadge verdict={v.verdict} /></td>
                <td className="py-2 pr-3 text-right font-mono text-xs text-soc-text soc-tabular">{Number(v.risk).toFixed(2)}</td>
                <td className="max-w-[360px] py-2 pr-3 text-xs leading-snug text-soc-muted">
                  {v.override ? <span className="text-soc-text">Analyst: {v.override.decision}. </span> : null}
                  {v.reasons?.[0]}
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
