import { useSearchParams } from "react-router-dom";
import PageTabs from "../components/PageTabs";
import AgentWatch from "../components/universal/AgentWatch";
import IntegrityPanel from "../components/universal/IntegrityPanel";
import LiveVerdicts from "../components/universal/LiveVerdicts";
import SitesPanel from "../components/universal/SitesPanel";
import { EmptyState } from "../components/universal/shared";
import { useUniversalVerdicts } from "../hooks/useUniversalVerdicts";

const TABS = [
  { key: "integrity", label: "Campaign integrity" },
  { key: "agents", label: "Agent watch" },
  { key: "live", label: "Live verdicts" },
  { key: "sites", label: "Sites" },
];

export default function ProtectionPage() {
  const { verdicts, status, error, replace } = useUniversalVerdicts();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("view");
  const activeTab = TABS.some((tab) => tab.key === requested) ? requested : "integrity";
  const flagged = verdicts.filter((v) => v.verdict !== "ok").length;

  function setActiveTab(view) {
    const next = new URLSearchParams(searchParams);
    if (view === "integrity") next.delete("view");
    else next.set("view", view);
    setSearchParams(next);
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="soc-kicker">SDK</p>
          <h1 className="soc-title mt-1">Behavioral protection</h1>
          <p className="mt-1 max-w-2xl text-sm text-soc-muted">
            People, wallets and AI agents on every site running the NeuroSOC SDK, scored against their own normal behavior.
          </p>
        </div>
        <p className="text-xs text-soc-muted" role="status">
          <span className={status === "connected" ? "text-soc-green" : "text-soc-amber"}>
            {status === "connected" ? "● Live" : "● Connecting"}
          </span>
          <span className="ml-2 soc-tabular">{verdicts.length} recent verdicts · {flagged} flagged</span>
        </p>
      </header>

      <PageTabs tabs={TABS} activeTab={activeTab} onChange={setActiveTab} idPrefix="protection" label="Protection sections" />

      <section id="protection-panel" role="tabpanel" aria-labelledby={`protection-tab-${activeTab}`} tabIndex={0} className="focus:outline-none">
        {error ? <EmptyState title="SDK engine unavailable">{error}</EmptyState> : null}
        {!error && activeTab === "integrity" ? <IntegrityPanel verdicts={verdicts} /> : null}
        {!error && activeTab === "agents" ? <AgentWatch verdicts={verdicts} onUpdated={replace} /> : null}
        {!error && activeTab === "live" ? <LiveVerdicts verdicts={verdicts} onUpdated={replace} /> : null}
        {!error && activeTab === "sites" ? <SitesPanel /> : null}
      </section>
    </div>
  );
}
