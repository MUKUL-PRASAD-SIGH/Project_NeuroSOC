import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function RiskDistributionChart({ data }) {
  return (
    <section className="soc-glass h-[300px] p-5">
      <h3 className="soc-section-title">Risk distribution</h3>
      <ResponsiveContainer width="100%" height="85%">
        <BarChart data={data} margin={{ top: 12, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#232c40" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="bucket" tick={{ fill: "#8a96ab", fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fill: "#8a96ab", fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
          <Tooltip
            cursor={{ fill: "rgba(79,168,247,0.06)" }}
            contentStyle={{ background: "#111726", border: "1px solid #232c40", borderRadius: 6, color: "#e6ebf4", fontSize: 12 }}
            labelStyle={{ color: "#8a96ab" }}
          />
          <Bar dataKey="count" fill="#4fa8f7" radius={[3, 3, 0, 0]} maxBarSize={36} />
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}
