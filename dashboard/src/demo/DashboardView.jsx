import { Button, Card, Pill, Skeleton } from "./ui";
import { money } from "./session";

function Stat({ label, value, note, loading }) {
  return (
    <Card>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      {loading ? <Skeleton className="mt-3 h-9 w-40" /> : <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>}
      {note ? <p className="mt-1 text-xs text-slate-400">{note}</p> : null}
    </Card>
  );
}

const STATUS_TONE = { settled: "good", pending: "warn", cancelled: "neutral" };

export default function DashboardView({ account, loading, onOpenAssistant, onOpenTransfer }) {
  const firstName = (account?.user_name || "Alex").split(" ")[0];
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Welcome back, {firstName}</h1>
          <p className="mt-1 text-sm text-slate-500">Here is where your money stands today.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onOpenAssistant}>Ask Nova AI</Button>
          <Button onClick={onOpenTransfer}>Send money</Button>
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Stat label="Portfolio value" value={money(account?.portfolio_value)} note="Across all holdings" loading={loading} />
        <Stat label="Available balance" value={money(account?.available_balance)} note="Ready to send" loading={loading} />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card title="Recent activity" className="lg:col-span-3">
          {loading ? (
            <div className="space-y-3"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
          ) : (account?.transactions || []).length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">No activity yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {account.transactions.slice(0, 7).map((tx) => (
                <li key={tx.id} className="flex items-center justify-between gap-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-900">{tx.counterparty}</p>
                    <p className="text-xs text-slate-400">{tx.date} · {tx.id}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {tx.status !== "settled" ? <Pill tone={STATUS_TONE[tx.status] || "neutral"}>{tx.status}</Pill> : null}
                    <span className={`text-sm font-medium tabular-nums ${tx.type === "credit" ? "text-emerald-600" : "text-slate-900"}`}>
                      {tx.type === "credit" ? "+" : "-"}{money(tx.amount)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Portfolio" className="lg:col-span-2">
          {loading ? <Skeleton className="h-40" /> : (
            <ul className="space-y-4">
              {(account?.portfolio_allocation || []).map((row) => (
                <li key={row.asset}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="text-slate-700">{row.asset}</span>
                    <span className="font-medium tabular-nums">{money(row.value)}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                    <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, row.allocation)}%` }} />
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{row.allocation}% · {row.change} today</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
