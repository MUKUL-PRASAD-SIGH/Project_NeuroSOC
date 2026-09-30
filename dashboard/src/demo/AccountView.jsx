import { Card, Pill } from "./ui";

export default function AccountView({ account }) {
  const rows = [
    ["Name", account?.user_name], ["Email", account?.email], ["Account ID", account?.account_id], ["Currency", account?.currency],
  ];
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
      <Card title="Profile">
        <dl className="divide-y divide-slate-100 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 py-3">
              <dt className="text-slate-500">{label}</dt><dd className="font-medium text-slate-900">{value || "-"}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card title="Linked services">
        <ul className="divide-y divide-slate-100 text-sm">
          {[["Acme Corp payroll", "Connected"], ["Stripe payouts", "Connected"], ["AWS billing", "Connected"]].map(([name, state]) => (
            <li key={name} className="flex items-center justify-between py-3"><span className="text-slate-700">{name}</span><Pill tone="good">{state}</Pill></li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
