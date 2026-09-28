import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function TransactionVolumeChart({ data }) {
  return (
    <section className="soc-glass h-[300px] p-5">
      <h3 className="soc-section-title">Transaction volume</h3>
      <ResponsiveContainer width="100%" height="85%">
        <LineChart data={data} margin={{ top: 12, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#232c40" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="time" tick={{ fill: "#8a96ab", fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fill: "#8a96ab", fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
          <Tooltip
            cursor={{ stroke: "#2a3448" }}
            contentStyle={{ background: "#111726", border: "1px solid #232c40", borderRadius: 6, color: "#e6ebf4", fontSize: 12 }}
            labelStyle={{ color: "#8a96ab" }}
          />
          <Line type="monotone" dataKey="transactions" stroke="#4fa8f7" strokeWidth={1.75} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </section>
  );
}
