import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import PageTabs from "../components/PageTabs";
import StatsBar from "../components/StatsBar";
import ThreatMap from "../components/ThreatMap";
import { useDashboardStore } from "../store/dashboardStore";

function describeAction(level) {
  if (level === "high") return "Escalate to containment and isolate account activity.";
  if (level === "medium") return "Flag for analyst verification and monitor retries.";
  return "Monitor passively and append to entity baseline.";
}

export default function ResponseOpsPage() {
  const alerts = useDashboardStore((state) => state.alerts.items);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabs = [
    { key: "summary", label: "Summary" },
    { key: "incidents", label: "Incident queue" },
    { key: "threat-map", label: "Threat map" },
  ];
  const requestedTab = searchParams.get("view");
  const activeTab = tabs.some((tab) => tab.key === requestedTab) ? requestedTab : "summary";

  function setActiveTab(view) {
    const next = new URLSearchParams(searchParams);
    if (view === "summary") next.delete("view");
    else next.set("view", view);
    setSearchParams(next);
  }

  const queue = useMemo(
    () =>
      [...alerts]
        .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
        .slice(0, 6)
        .map((alert) => ({
          ...alert,
          action: describeAction(alert.severity),
        })),
    [alerts]
  );

  return (
    <div className="space-y-4">
      <header>
        <p className="soc-kicker">Response</p>
        <h1 className="soc-title mt-1">Incident response</h1>
        <p className="mt-1 max-w-2xl text-sm text-soc-muted">
          Review operational metrics, recent incidents, and the threat map.
        </p>
      </header>

      <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} idPrefix="response" label="Response sections" />

      <section id="response-panel" role="tabpanel" aria-labelledby={`response-tab-${activeTab}`} tabIndex={0} className="space-y-4 focus:outline-none">
        {activeTab === "summary" ? <StatsBar /> : null}
        {activeTab === "threat-map" ? <ThreatMap /> : null}

        {activeTab === "incidents" ? (
          <section className="soc-glass flex min-h-[390px] flex-col p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="soc-section-title">Recommended actions</h2>
                <p className="mt-0.5 text-xs text-soc-muted">Six most recent incidents</p>
              </div>
              <span className="rounded-md border border-soc-border bg-soc-panelSoft px-2.5 py-1 text-xs text-soc-muted">
                {queue.length} {queue.length === 1 ? "incident" : "incidents"}
              </span>
            </div>
            <div className="mt-4 flex-1 space-y-2 overflow-y-auto pr-1">
              {queue.length === 0 ? (
                <div className="rounded-md border border-dashed border-soc-border p-6 text-center text-sm text-soc-muted">
                  No incidents queued.
                </div>
              ) : null}

              {queue.map((item) => (
                <article key={item.id} className="rounded-md border border-soc-border/80 bg-soc-panelSoft/50 p-3">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span
                      className={`inline-flex items-center gap-1.5 capitalize ${
                        item.severity === "high" ? "text-soc-red" : item.severity === "medium" ? "text-soc-amber" : "text-soc-muted"
                      }`}
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-current" />
                      {item.severity}
                    </span>
                    <span className="soc-tabular font-mono text-soc-muted">{new Date(item.timestamp).toLocaleTimeString()}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-soc-text">{item.message}</p>
                  <p className="mt-1.5 text-xs text-soc-muted">
                    <span className="text-soc-text">Next step:</span> {item.action}
                  </p>
                </article>
              ))}
            </div>
          </section>
        ) : null}
      </section>
    </div>
  );
}
