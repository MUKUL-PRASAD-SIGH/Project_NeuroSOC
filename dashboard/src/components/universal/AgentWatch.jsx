import { useMemo, useState } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { overrideVerdict } from "../../services/universalApi";
import { EmptyState, VerdictBadge, shortId, timeOf } from "./shared";

const ALLOWED = "#4fa8f7";
const BLOCKED = "#ef5b67";

function PointTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-soc-border bg-soc-panel px-3 py-2 text-xs shadow-panel">
      <p className="text-soc-muted">{timeOf(p.ts)}</p>
      <p className="font-mono text-soc-text">{p.amount.toLocaleString()} {p.asset || ""} → {shortId(p.destination)}</p>
      <p className={p.blocked ? "text-soc-red" : "text-soc-muted"}>{p.blocked ? "Blocked before execution" : "Allowed"}</p>
    </div>
  );
}

export default function AgentWatch({ verdicts, onUpdated }) {
  const agents = useMemo(() => [...new Set(verdicts.filter((v) => v.entity.type === "agent").map((v) => v.entity.id))], [verdicts]);
  const [selected, setSelected] = useState(null);
  const agent = selected && agents.includes(selected) ? selected : agents[0];
  const [busy, setBusy] = useState(false);

  const history = useMemo(
    () => verdicts.filter((v) => v.entity.type === "agent" && v.entity.id === agent).sort((a, b) => a.timestamp - b.timestamp),
    [verdicts, agent]
  );
  const points = history.filter((v) => v.value?.amount != null).map((v) => ({
    ts: v.timestamp,
    amount: Math.max(Number(v.value.amount), 0.01),
    asset: v.value.asset,
    destination: v.value.destination,
    blocked: v.action === "pause_agent",
  }));
  const allowed = points.filter((p) => !p.blocked);
  const blocked = points.filter((p) => p.blocked);
  const incident = [...history].reverse().find((v) => v.verdict === "agent_anomaly");

  async function decide(decision) {
    if (!incident) return;
    setBusy(true);
    try {
      onUpdated(await overrideVerdict(incident.verdict_id, decision));
    } finally {
      setBusy(false);
    }
  }

  if (!agent) {
    return (
      <EmptyState title="No agents reporting yet">
        Wrap an agent's tools with <code>@soc.guard_tool(...)</code> from the Python SDK, or run <code>python attack_patterns/agent_hijack.py</code>.
      </EmptyState>
    );
  }

  return (
    <section className="soc-glass p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="soc-section-title">Agent watch</h2>
          <p className="text-xs text-soc-muted">Every value-moving tool call, scored before it runs. Amounts on a log scale so routine moves and outliers fit together.</p>
        </div>
        {agents.length > 1 ? (
          <select className="soc-btn" value={agent} onChange={(e) => setSelected(e.target.value)} aria-label="Agent">
            {agents.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        ) : <span className="font-mono text-xs text-soc-muted">{agent}</span>}
      </div>

      {incident ? (
        <div className="mt-4 rounded-md border border-soc-red/40 bg-soc-red/10 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <VerdictBadge verdict="agent_anomaly" />
              <span className="text-sm text-soc-text">
                {Number(incident.value?.amount || 0).toLocaleString()} {incident.value?.asset || ""} to {shortId(incident.value?.destination)} was stopped at {timeOf(incident.timestamp)}
              </span>
            </div>
            {incident.override ? (
              <span className="text-xs text-soc-muted">Owner decision: {incident.override.decision}</span>
            ) : (
              <div className="flex gap-2">
                <button type="button" className="soc-btn" disabled={busy} onClick={() => decide("confirm")}>Keep blocked</button>
                <button type="button" className="soc-btn" disabled={busy} onClick={() => decide("restore")}>Resume agent</button>
              </div>
            )}
          </div>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-soc-text">
            {incident.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      ) : null}

      <div className="mt-4 flex items-center gap-4 text-xs text-soc-muted">
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: ALLOWED }} />Allowed ({allowed.length})</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: BLOCKED }} />Blocked ({blocked.length})</span>
      </div>
      <div className="mt-2 h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
            <CartesianGrid stroke="#232c40" strokeDasharray="3 3" />
            <XAxis dataKey="ts" type="number" domain={["dataMin", "dataMax"]} tickFormatter={timeOf}
              tick={{ fill: "#8a96ab", fontSize: 11 }} tickLine={false} axisLine={false} name="Time" />
            <YAxis dataKey="amount" type="number" scale="log" domain={[(min) => Math.max(min / 2, 0.01), (max) => max * 3]}
              tickFormatter={(v) => Number(v).toLocaleString()} tick={{ fill: "#8a96ab", fontSize: 11 }}
              tickLine={false} axisLine={false} width={64} name="Amount" />
            <ZAxis range={[64, 64]} />
            <Tooltip content={<PointTooltip />} cursor={{ stroke: "#2a3448" }} />
            <Scatter name="Allowed" data={allowed} fill={ALLOWED} stroke="#111726" strokeWidth={2} isAnimationActive={false} />
            <Scatter name="Blocked" data={blocked} fill={BLOCKED} stroke="#111726" strokeWidth={2} isAnimationActive={false} shape="diamond" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
