import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMemo } from "react";

const SERIES = [
  { key: "HACKER", label: "Threat", color: "#ef5b67" },
  { key: "FORGETFUL_USER", label: "Review", color: "#e9a93b" },
  { key: "LEGITIMATE", label: "Normal", color: "#4fa8f7" },
];

const AXIS = { fill: "#8a96ab", fontSize: 11 };

export default function VerdictTimeline({ data }) {
  const rows = Array.isArray(data) ? data : [];
  const totals = useMemo(
    () =>
      SERIES.reduce((acc, series) => {
        acc[series.key] = rows.reduce((sum, row) => sum + (Number(row[series.key]) || 0), 0);
        return acc;
      }, {}),
    [rows]
  );

  return (
    <section className="soc-glass p-5">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="soc-section-title">Verdicts over time</h2>
          <p className="mt-0.5 text-xs text-soc-muted">Classifier outcomes per interval</p>
        </div>
        <div className="flex gap-5">
          {SERIES.map((series) => (
            <div key={series.key} className="min-w-[64px]">
              <div className="flex items-center gap-1.5 text-xs text-soc-muted">
                <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: series.color }} />
                {series.label}
              </div>
              <p className="soc-tabular mt-1 text-lg font-semibold text-soc-text">{totals[series.key].toLocaleString()}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="h-[340px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <defs>
              {SERIES.map((series) => (
                <linearGradient key={series.key} id={`gradient-${series.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={series.color} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={series.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke="#232c40" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="time"
              tickFormatter={(value) =>
                new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
              }
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              minTickGap={24}
            />
            <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              cursor={{ stroke: "#2a3448" }}
              contentStyle={{
                background: "#111726",
                border: "1px solid #232c40",
                borderRadius: "6px",
                color: "#e6ebf4",
                fontSize: 12,
              }}
              labelStyle={{ color: "#8a96ab", marginBottom: 4 }}
              formatter={(value, name) => [value, SERIES.find((s) => s.key === name)?.label || name]}
              labelFormatter={(value) => new Date(value).toLocaleString()}
            />
            {SERIES.map((series) => (
              <Area
                key={series.key}
                type="monotone"
                dataKey={series.key}
                stroke={series.color}
                fill={`url(#gradient-${series.key})`}
                strokeWidth={1.75}
                dot={false}
                activeDot={{ r: 3 }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
