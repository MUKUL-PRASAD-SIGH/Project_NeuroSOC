import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function SeverityTrendChart({ data }) {
  return (
    <section className="soc-glass flex h-full min-h-[320px] flex-col p-5">
      <h3 className="soc-section-title">Severity trend</h3>
      <p className="mt-0.5 text-xs text-soc-muted">Weighted alert severity per minute</p>
      <div className="mt-4 min-h-[240px] flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <defs>
              <linearGradient id="severity-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#e6edff" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#e6edff" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1a2233" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="time" tick={{ fill: "#8a93a8", fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} tick={{ fill: "#8a93a8", fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              cursor={{ stroke: "#2a3450" }}
              contentStyle={{ background: "#0a0e18", border: "1px solid #1a2233", borderRadius: 6, color: "#eef2fa", fontSize: 12 }}
              labelStyle={{ color: "#8a93a8" }}
              formatter={(value) => [value, "Severity"]}
            />
            <Area type="monotone" dataKey="high" stroke="#e6edff" fill="url(#severity-fill)" strokeWidth={1.75} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
