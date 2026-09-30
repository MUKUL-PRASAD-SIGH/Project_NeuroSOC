import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import AlertFeed from "../components/AlertFeed";
import IngestionWorkbench from "../components/IngestionWorkbench";
import ModelCandidatesPanel from "../components/ModelCandidatesPanel";
import ModelStatusCard from "../components/ModelStatusCard";
import PageTabs from "../components/PageTabs";
import { Hero, WhyNow, Workspace } from "../components/OverviewHero";
import ThreatMap from "../components/ThreatMap";
import UserProfileModal from "../components/UserProfileModal";
import VerdictTimeline from "../components/Charts/VerdictTimeline";
import { DEMO_DATA_ENABLED, MODEL_INTEGRATION_ENABLED } from "../lib/featureFlags";
import { buildTimelineData } from "../mocks/data";
import { useDashboardStore } from "../store/dashboardStore";

export default function DashboardPage() {
  const alerts = useDashboardStore((state) => state.alerts.items);
  const statsError = useDashboardStore((state) => state.stats.error);
  const modelError = useDashboardStore((state) => state.modelStatus.error);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabs = [
    { key: "overview", label: "Activity" },
    { key: "threat-map", label: "Threat map" },
    ...(MODEL_INTEGRATION_ENABLED ? [{ key: "model-health", label: "Model health" }] : []),
    { key: "pipeline", label: "Pipeline" },
  ];
  const requestedTab = searchParams.get("view");
  const activeTab = tabs.some((tab) => tab.key === requestedTab) ? requestedTab : "overview";

  const timelineData = useMemo(() => buildTimelineData(alerts), [alerts]);

  function setActiveTab(view) {
    const next = new URLSearchParams(searchParams);
    if (view === "overview") {
      next.delete("view");
    } else {
      next.set("view", view);
    }

    setSearchParams(next);
  }

  return (
    <div className="space-y-5">
      {activeTab === "overview" ? (
        <Hero onOpenAlerts={() => document.getElementById("alert-feed")?.scrollIntoView({ behavior: "smooth" })} />
      ) : null}

      <header className={activeTab === "overview" ? "hidden" : ""}>
        <div>
          <p className="soc-kicker">Overview</p>
          <h1 className="soc-title mt-1">Security operations</h1>
          <p className="mt-1 max-w-2xl text-sm text-soc-muted">
            {DEMO_DATA_ENABLED
              ? "Explore the alert investigation and analyst review flow. Colab model signals are reserved for integration."
              : !MODEL_INTEGRATION_ENABLED
                ? "Investigate live events and analyst decisions. Colab model signals will appear when the service is connected."
                : "Security event classification with analyst review and model feedback."}
          </p>
        </div>
      </header>

      {statsError || modelError ? (
        <div className="rounded-md border border-soc-red/40 bg-soc-red/10 px-4 py-2.5 text-sm text-soc-red">
          {statsError || modelError}
        </div>
      ) : null}

      <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} idPrefix="overview" label="Overview sections" />

      <section id="overview-panel" role="tabpanel" aria-labelledby={`overview-tab-${activeTab}`} tabIndex={0} className="space-y-5 focus:outline-none">
        {activeTab === "overview" ? (
          <>
            <WhyNow />
            <Workspace />
            <div id="alert-feed" className="grid scroll-mt-24 grid-cols-1 gap-4 pt-10 xl:grid-cols-[minmax(0,1fr)_400px]">
              <VerdictTimeline data={timelineData} />
              <AlertFeed />
            </div>
          </>
        ) : null}

        {activeTab === "threat-map" ? <ThreatMap compact={false} /> : null}

        {activeTab === "model-health" && MODEL_INTEGRATION_ENABLED ? (
          <div className="max-w-3xl">
            <ModelStatusCard />
            <ModelCandidatesPanel />
          </div>
        ) : null}

        {activeTab === "pipeline" ? <IngestionWorkbench /> : null}
      </section>

      <UserProfileModal />
    </div>
  );
}
