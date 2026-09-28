import { useMemo } from "react";
import { useDashboardStore } from "../store/dashboardStore";

function StatCard({ label, value, hint, accent }) {
  return (
    <article className="soc-glass flex flex-col justify-between px-5 py-4">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${accent}`} />
        <p className="text-xs font-medium text-soc-muted">{label}</p>
      </div>
      <p className="soc-tabular mt-3 text-[28px] font-semibold leading-none tracking-tight text-soc-text">{value}</p>
      <p className="mt-2 text-xs text-soc-muted">{hint}</p>
    </article>
  );
}

export default function StatsBar() {
  const stats = useDashboardStore((state) => state.stats.data);

  const cards = useMemo(
    () => [
      {
        label: "Sessions analysed",
        value: Number(stats.totalTransactions || 0).toLocaleString(),
        hint: "Scored by the decision layer",
        accent: "bg-soc-electric",
      },
      {
        label: "Confirmed threats",
        value: Number(stats.hackerDetections || 0).toLocaleString(),
        hint: "Routed to sandbox isolation",
        accent: "bg-soc-red",
      },
      {
        label: "Average risk",
        value: Number(stats.avgRiskScore || 0).toFixed(2),
        hint: "Mean confidence, 0 to 1",
        accent: "bg-soc-amber",
      },
      {
        label: "Open alerts",
        value: Number(stats.liveAlerts || 0).toLocaleString(),
        hint: "Awaiting analyst review",
        accent: "bg-soc-green",
      },
    ],
    [stats]
  );

  return (
    <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
      {cards.map((card) => (
        <StatCard key={card.label} {...card} />
      ))}
    </section>
  );
}
