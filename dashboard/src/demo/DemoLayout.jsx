import { Link } from "react-router-dom";
import { Pill } from "./ui";

export const VIEWS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "transfer", label: "Transfer" },
  { id: "assistant", label: "Nova AI" },
  { id: "account", label: "Account" },
  { id: "security", label: "Security" },
];

function protectionChip({ connected, active, consent }) {
  if (!connected) return { tone: "neutral", text: "No application connected" };
  if (active) return { tone: "good", text: "Protected by NeuroSOC" };
  return { tone: "warn", text: consent === false ? "Telemetry off" : "Telemetry waiting for consent" };
}

export default function DemoLayout({ view, onView, views = VIEWS, connected, active, consent, children }) {
  const chip = protectionChip({ connected, active, consent });
  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900 antialiased">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-xs font-bold text-white" aria-hidden="true">NT</span>
              <span className="text-[15px] font-semibold tracking-tight">NovaTrust</span>
            </div>
            <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
              {views.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onView(item.id)}
                  aria-current={view === item.id ? "page" : undefined}
                  className={`rounded-lg px-3 py-1.5 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    view === item.id ? "bg-slate-100 font-medium text-slate-900" : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"}`}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <Pill tone="info" className="hidden sm:inline-flex">DEMO ENVIRONMENT</Pill>
            <Pill tone={chip.tone}>
              <span className={`h-1.5 w-1.5 rounded-full ${chip.tone === "good" ? "bg-emerald-500" : chip.tone === "warn" ? "bg-amber-500" : "bg-slate-400"}`} aria-hidden="true" />
              {chip.text}
            </Pill>
          </div>
        </div>
        <nav aria-label="Primary (mobile)" className="flex gap-1 overflow-x-auto border-t border-slate-100 px-3 py-2 md:hidden">
          {views.map((item) => (
            <button key={item.id} type="button" onClick={() => onView(item.id)} aria-current={view === item.id ? "page" : undefined}
              className={`whitespace-nowrap rounded-md px-3 py-1 text-sm ${view === item.id ? "bg-slate-100 font-medium" : "text-slate-500"}`}>
              {item.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
      <footer className="mx-auto max-w-6xl px-5 pb-10 pt-2 text-xs text-slate-400">
        NovaTrust is a fictional company used to demonstrate NeuroSOC. All balances and people are made up.{" "}
        <Link className="underline underline-offset-2 hover:text-slate-600" to="/protection?view=live">Open the NeuroSOC dashboard</Link>
      </footer>
    </div>
  );
}
