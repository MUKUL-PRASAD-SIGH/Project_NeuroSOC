import { useEffect, useMemo, useRef, useState } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import GlowPipeline from "./GlowPipeline";
import { DEMO_DATA_ENABLED } from "../lib/featureFlags";
import { SCENARIO_LIBRARY, liveScenarioRunners } from "../services/liveScripts";

const THEATER_PHASES = [
  { id: "portal", label: "Portal session", code: "01" },
  { id: "behavioral", label: "Behaviour capture", code: "02" },
  { id: "ensemble", label: "Model ensemble (SNN · LNN · XGB)", code: "03" },
  { id: "decision", label: "Decision", code: "04" },
  { id: "route", label: "Routing", code: "05" },
  { id: "feedback", label: "Feedback", code: "06" },
  { id: "retraining", label: "Retraining check", code: "07" },
];

const ACCENT_TOKENS = {
  emerald: {
    halo: "from-sky-300/20 via-sky-300/10 to-transparent",
    border: "border-sky-300/45",
    badge: "border-sky-300/35 bg-sky-300/10 text-sky-300",
    text: "text-sky-300",
    orb: "bg-sky-300",
    soft: "bg-sky-300/10",
  },
  amber: {
    halo: "from-blue-200/20 via-blue-200/10 to-transparent",
    border: "border-blue-200/45",
    badge: "border-blue-200/35 bg-blue-200/10 text-blue-200",
    text: "text-blue-200",
    orb: "bg-blue-200",
    soft: "bg-blue-200/10",
  },
  rose: {
    halo: "from-indigo-200/20 via-indigo-200/10 to-transparent",
    border: "border-indigo-200/45",
    badge: "border-indigo-200/35 bg-indigo-200/10 text-indigo-200",
    text: "text-indigo-200",
    orb: "bg-indigo-200",
    soft: "bg-indigo-200/10",
  },
  cyan: {
    halo: "from-soc-electric/20 via-soc-electric/10 to-transparent",
    border: "border-soc-electric/45",
    badge: "border-soc-electric/35 bg-soc-electric/10 text-soc-electric",
    text: "text-soc-electric",
    orb: "bg-soc-electric",
    soft: "bg-soc-electric/10",
  },
  neutral: {
    halo: "from-slate-500/14 via-slate-400/8 to-transparent",
    border: "border-soc-border/70",
    badge: "border-soc-border/70 bg-soc-panelSoft/35 text-soc-muted",
    text: "text-soc-text",
    orb: "bg-soc-muted",
    soft: "bg-soc-panelSoft/35",
  },
};

const ROUTE_LANES = [
  {
    key: "safe",
    title: "Allow",
    detail: "Simulated portal view continues.",
  },
  {
    key: "review",
    title: "Soft review",
    detail: "Demo session pauses; a reload restores the simulated view.",
  },
  {
    key: "sandbox",
    title: "Sandbox",
    detail: "Demo session enters the local decoy view and records test activity.",
  },
];

const EMPTY_SCENE = {
  browser: {
    tone: "neutral",
    eyebrow: "Idle",
    title: "Select a scenario to begin",
    subtitle: "Each run submits generated test inputs to the local services when available.",
    lines: [
      "Simulated trusted customer → standard portal view.",
      "Simulated customer → review branch, then safe reload.",
      "Generated test signal → local sandbox branch and analyst review.",
    ],
    badge: "Ready",
  },
  route: {
    kind: "idle",
    title: "No route selected",
    detail: "Waiting for a decision.",
    footer: "Run a scenario to see the routing outcome.",
  },
  feedback: {
    tone: "neutral",
    title: "Feedback loop idle",
    detail: "No session has produced a label yet.",
    chips: ["Awaiting run"],
  },
  retraining: {
    tone: "neutral",
    title: "Retraining loop idle",
    detail: "The model remains on the current production version until a run earns a strong label.",
    chips: ["No delta"],
  },
};

function mergeScene(previous, patch = {}) {
  return {
    ...previous,
    ...patch,
    browser: patch.browser || previous.browser,
    route: patch.route || previous.route,
    feedback: patch.feedback || previous.feedback,
    retraining: patch.retraining || previous.retraining,
  };
}

function tokenFor(tone) {
  return ACCENT_TOKENS[tone] || ACCENT_TOKENS.neutral;
}

function statusClasses(status) {
  if (status === "success") return "border-soc-green/40 bg-soc-green/10 text-soc-green";
  if (status === "warning") return "border-soc-amber/40 bg-soc-amber/10 text-soc-amber";
  if (status === "error") return "border-soc-red/45 bg-soc-red/10 text-soc-red";
  return "border-soc-electric/35 bg-soc-electric/10 text-soc-electric";
}

function ActorAvatar({ scenario, large = false }) {
  const tokens = tokenFor(scenario.accent);

  return (
    <div
      className={`relative inline-flex items-center justify-center rounded-2xl border font-medium ${tokens.border} ${tokens.soft} ${
        large ? "h-16 w-16 text-xl" : "h-12 w-12 text-sm"
      }`}
    >
      <div className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${tokens.halo}`} />
      <span className="relative text-soc-text">{scenario.initials}</span>
    </div>
  );
}

function ScenarioCard({ scenario, isActive, isRunning, onRun }) {
  const tokens = tokenFor(scenario.accent);

  return (
    <article
      className={`relative overflow-hidden rounded-2xl border bg-soc-panel/70 p-4 transition-all duration-300 ${
        isActive ? `${tokens.border} shadow-[0_20px_55px_rgba(3,10,24,0.5)]` : "border-soc-border/70"
      }`}
    >
      <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${tokens.halo}`} />
      <div className="relative">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <ActorAvatar scenario={scenario} />
            <div>
              <p className="text-xs font-medium text-soc-muted">{scenario.role}</p>
              <h3 className="mt-1 text-base font-medium text-soc-text">{scenario.title}</h3>
              <p className="text-sm text-soc-muted">{scenario.actorName}</p>
            </div>
          </div>
          <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
            {scenario.expectedLane}
          </span>
        </div>

        <div className="mt-4 grid gap-2 text-sm text-soc-text">
          <p><span className="font-medium text-soc-muted">Source IP:</span> {scenario.ipAddress}</p>
          <p><span className="font-medium text-soc-muted">Device:</span> {scenario.device}</p>
          <p className="text-soc-muted">{scenario.expectation}</p>
        </div>

        <button
          type="button"
          disabled={isRunning}
          onClick={() => onRun(scenario.key)}
          className={`mt-4 inline-flex rounded-full border px-4 py-2 text-xs font-medium uppercase tracking-[0.18em] transition-colors ${
            isActive
              ? `${tokens.badge} hover:brightness-110`
              : "border-soc-border/70 bg-soc-panelSoft/40 text-soc-text hover:border-soc-electric/35"
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {isRunning && isActive ? "Running…" : "Run scenario"}
        </button>
      </div>
    </article>
  );
}

function BrowserMock({ browser, scenario }) {
  const tokens = tokenFor(browser?.tone || scenario?.accent || "neutral");

  return (
    <div className="soc-tilt-panel rounded-2xl border border-soc-border/70 bg-soc-panel p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-soc-red" />
          <span className="h-2.5 w-2.5 rounded-full bg-soc-amber" />
          <span className="h-2.5 w-2.5 rounded-full bg-soc-green" />
        </div>
        <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
          {browser.badge}
        </span>
      </div>

      <div className="mt-4 rounded-xl border border-soc-border/70 bg-soc-panel/70 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-medium text-soc-muted">{browser.eyebrow}</p>
            <h3 className="mt-1 text-lg font-medium text-soc-text">{browser.title}</h3>
            <p className="mt-2 text-sm text-soc-muted">{browser.subtitle}</p>
          </div>
          {scenario ? <ActorAvatar scenario={scenario} /> : null}
        </div>

        <div className="mt-4 space-y-2">
          {(Array.isArray(browser.lines) ? browser.lines : []).map((line) => (
            <div key={line} className="rounded-xl border border-soc-border/60 bg-soc-panelSoft/40 px-3 py-2 text-sm text-soc-text">
              {line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RouteBoard({ route }) {
  return (
    <div className="rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
      <p className="text-xs font-medium text-soc-muted">Routing</p>
      <div className="mt-4 grid gap-3">
        {ROUTE_LANES.map((lane) => {
          const active = route.kind === lane.key;
          const color =
            lane.key === "safe"
              ? active
                ? "border-soc-green/40 bg-soc-green/10 text-soc-green"
                : "border-soc-border/70 bg-soc-panelSoft/30 text-soc-muted"
              : lane.key === "review"
                ? active
                  ? "border-soc-amber/40 bg-soc-amber/10 text-soc-amber"
                  : "border-soc-border/70 bg-soc-panelSoft/30 text-soc-muted"
                : active
                  ? "border-soc-red/45 bg-soc-red/10 text-soc-red"
                  : "border-soc-border/70 bg-soc-panelSoft/30 text-soc-muted";

          return (
            <div key={lane.key} className={`rounded-xl border px-3 py-3 transition-all ${color}`}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium">{lane.title}</p>
                <span className="text-[10px] font-medium uppercase tracking-[0.16em]">{active ? "active" : "idle"}</span>
              </div>
              <p className="mt-2 text-xs">{active ? route.detail : lane.detail}</p>
            </div>
          );
        })}
      </div>

      <div className="mt-4 rounded-xl border border-soc-border/70 bg-soc-panelSoft/30 px-3 py-3">
        <p className="text-[11px] font-medium text-soc-muted">Outcome</p>
        <p className="mt-2 text-sm font-medium text-soc-text">{route.title}</p>
        <p className="mt-2 text-sm text-soc-muted">{route.footer}</p>
      </div>
    </div>
  );
}

function FeedbackCard({ feedback }) {
  const tokens = tokenFor(feedback?.tone || "neutral");

  return (
    <div className="rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-soc-muted">Feedback</p>
        <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
          {feedback?.tone || "idle"}
        </span>
      </div>
      <h3 className="mt-3 text-base font-medium text-soc-text">{feedback?.title}</h3>
      <p className="mt-2 text-sm text-soc-muted">{feedback?.detail}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {feedback?.chips?.map((chip) => (
          <span key={chip} className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
            {chip}
          </span>
        ))}
      </div>
    </div>
  );
}

function RetrainingCard({ retraining }) {
  const tokens = tokenFor(retraining?.tone || "neutral");

  return (
    <div className="rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-soc-muted">Retraining</p>
        <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
          {retraining?.tone || "idle"}
        </span>
      </div>
      <h3 className="mt-3 text-base font-medium text-soc-text">{retraining?.title}</h3>
      <p className="mt-2 text-sm text-soc-muted">{retraining?.detail}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {retraining?.chips?.map((chip) => (
          <span key={chip} className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
            {chip}
          </span>
        ))}
      </div>
    </div>
  );
}

function VerdictCard({ verdict }) {
  if (!verdict) {
    return (
      <div className="rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
        <p className="text-xs font-medium text-soc-muted">Decision</p>
        <p className="mt-3 text-sm text-soc-muted">Model scores appear once the run reaches the decision stage.</p>
      </div>
    );
  }

  const verdictLabel = verdict.verdict || "INCONCLUSIVE";
  const verdictTone =
    verdictLabel === "HACKER" ? "rose" : verdictLabel === "FORGETFUL_USER" ? "amber" : verdictLabel === "LEGITIMATE" ? "emerald" : "neutral";
  const tokens = tokenFor(verdictTone);

  const metricCards = [
    { label: "Confidence", value: `${Math.round((Number(verdict.confidence || 0) || 0) * 100)}%` },
    { label: "SNN", value: `${Math.round((Number(verdict.snnScore || verdict.snn_score || 0) || 0) * 100)}%` },
    { label: "LNN", value: verdict.lnnClass || verdict.lnn_class || "—" },
    { label: "XGBoost", value: verdict.xgbClass || verdict.xgb_class || "—" },
  ];

  return (
    <div className="rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-soc-muted">Decision</p>
        <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${tokens.badge}`}>
          {verdictLabel}
        </span>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {metricCards.map((metric) => (
          <div key={metric.label} className="rounded-xl border border-soc-border/70 bg-soc-panelSoft/35 px-3 py-3">
            <p className="text-[11px] font-medium text-soc-muted">{metric.label}</p>
            <p className={`mt-2 text-sm font-medium ${tokens.text}`}>{metric.value}</p>
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-xl border border-soc-border/70 bg-soc-panelSoft/35 px-3 py-3 text-sm text-soc-muted">
        Session <span className="font-medium text-soc-text">{verdict.sessionId || verdict.session_id || "pending"}</span>
        {verdict?.sandbox?.active ? (
          <span className="ml-2 rounded-full border border-soc-red/40 bg-soc-red/10 px-2 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-soc-red">
            sandboxed
          </span>
        ) : null}
      </div>
    </div>
  );
}

function TracePanel({ logs, runError, usedFallback }) {
  return (
    <div className="rounded-2xl border border-soc-border/70 bg-soc-panel/55 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-soc-muted">Execution log</p>
        {usedFallback ? (
          <span className="rounded-full border border-soc-amber/40 bg-soc-amber/10 px-2 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-soc-amber">
            fallback
          </span>
        ) : null}
      </div>

      {runError ? (
        <div className="mt-4 rounded-xl border border-soc-red/45 bg-soc-red/10 px-4 py-3 text-sm text-soc-red">
          {runError}
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        {logs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-soc-border/70 bg-soc-panelSoft/40 px-4 py-5 text-sm text-soc-muted">
            Run a scenario to see each service call and its result.
          </div>
        ) : null}

        {logs.map((item) => (
          <article key={item.id} className="rounded-xl border border-soc-border/70 bg-soc-panelSoft/40 p-3">
            <div className="flex items-center justify-between gap-3">
              <h4 className="text-sm font-medium text-soc-text">{item.title}</h4>
              <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${statusClasses(item.status)}`}>
                {item.status}
              </span>
            </div>
            <p className="mt-2 text-sm text-soc-muted">{item.detail}</p>
            {item.endpoint ? (
              <p className="mt-2 text-[10px] font-medium uppercase tracking-[0.16em] text-soc-electric">{item.endpoint}</p>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

export default function IngestionWorkbench() {
  const [activeScenarioKey, setActiveScenarioKey] = useState(SCENARIO_LIBRARY[0].key);
  const [activePhase, setActivePhase] = useState(null);
  const activePhaseRef = useRef(null);

  useEffect(() => {
    activePhaseRef.current = activePhase;
  }, [activePhase]);
  const [scene, setScene] = useState(EMPTY_SCENE);
  const [logs, setLogs] = useState([]);
  const [latestVerdict, setLatestVerdict] = useState(null);
  const [runError, setRunError] = useState("");
  const [usedFallback, setUsedFallback] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  const fetchStats = useDashboardStore((state) => state.fetchStats);
  const fetchModelStatus = useDashboardStore((state) => state.fetchModelStatus);
  const hydrateAlerts = useDashboardStore((state) => state.hydrateAlerts);
  const liveModel = useDashboardStore((state) => state.modelStatus.data);

  const activeScenario = useMemo(
    () => SCENARIO_LIBRARY.find((scenario) => scenario.key === activeScenarioKey) || SCENARIO_LIBRARY[0],
    [activeScenarioKey]
  );

  async function runScenario(scenarioKey) {
    const runner = liveScenarioRunners[scenarioKey];
    const scenario = SCENARIO_LIBRARY.find((entry) => entry.key === scenarioKey);
    if (!runner || !scenario || isRunning) {
      return;
    }

    setIsRunning(true);
    setActiveScenarioKey(scenarioKey);
    setActivePhase("portal");
    setScene(EMPTY_SCENE);
    setLogs([]);
    setLatestVerdict(null);
    setRunError("");
    setUsedFallback(false);

    try {
      const result = await runner({
        onScenario: (meta) => {
          setActiveScenarioKey(meta.key);
        },
        onPhase: (phase) => {
          setActivePhase(phase);
        },
        onSnapshot: (snapshot) => {
          setScene((previous) => mergeScene(previous, snapshot));
        },
        onLog: (item) => {
          setLogs((previous) => [...previous, item]);
        },
        onVerdict: (verdict) => {
          setLatestVerdict(verdict);
        },
      });

      if (result?.summary) {
        setScene((previous) => mergeScene(previous, result.summary));
      }
      if (result?.latestVerdict) {
        setLatestVerdict(result.latestVerdict);
      }
      setUsedFallback(Boolean(result?.usedFallback));
      setActivePhase("retraining");

      await Promise.all([fetchStats(), fetchModelStatus(), hydrateAlerts()]);
    } catch (error) {
      if (DEMO_DATA_ENABLED) {
        // Demo mode has no backend: finish the walkthrough locally so the pipeline still plays through.
        setLogs((previous) => [
          ...previous,
          {
            id: `offline-${Date.now()}`,
            status: "warning",
            title: "Backend offline — simulated walkthrough",
            detail: error instanceof Error ? error.message : "The local services are unavailable.",
            endpoint: null,
          },
        ]);
        setUsedFallback(true);
        const startIndex = Math.max(0, THEATER_PHASES.findIndex((phase) => phase.id === activePhaseRef.current));
        for (const phase of THEATER_PHASES.slice(startIndex)) {
          setActivePhase(phase.id);
          await new Promise((resolve) => window.setTimeout(resolve, 1100));
        }
      } else {
        setRunError(error instanceof Error ? error.message : "Unable to run the live scenario.");
        setActivePhase(null);
      }
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="soc-glass relative isolate overflow-hidden p-5">
      <video
        className="pointer-events-none absolute inset-0 -z-10 h-full w-full object-cover opacity-[0.55] motion-reduce:hidden"
        src="/media/blue-liquid.mp4"
        onLoadedMetadata={(event) => {
          event.currentTarget.defaultPlaybackRate = 0.25;
          event.currentTarget.playbackRate = 0.25;
        }}
        autoPlay
        loop
        muted
        playsInline
        aria-hidden="true"
      />
      <div className="flex flex-col gap-3 border-b border-soc-border pb-4 md:flex-row md:items-end md:justify-between">
        <div className="max-w-3xl">
          <p className="soc-kicker">Scenario runner</p>
          <h2 className="mt-1 text-xl font-medium tracking-tight text-soc-text">End-to-end pipeline walkthrough</h2>
          <p className="mt-1 text-sm text-soc-muted">
            Run generated NovaTrust test signals against the local services. Portal accounts and activity are simulated; inference and verdict APIs are local.
          </p>
        </div>

        <div className="flex items-center gap-4 text-xs">
          <div>
            <p className="text-soc-muted">Active model</p>
            <p className="mt-0.5  text-soc-text">{liveModel?.version || "—"}</p>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-xl border border-soc-border bg-soc-panelSoft px-2.5 py-1 text-soc-muted">
            <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? "bg-soc-electric" : "bg-soc-green"}`} />
            {isRunning ? "Running" : "Ready"}
          </span>
        </div>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium text-soc-muted">Choose a scenario</p>

            <div className="space-y-2">
              {SCENARIO_LIBRARY.map((scenario) => (
                <ScenarioCard
                  key={scenario.key}
                  scenario={scenario}
                  isActive={scenario.key === activeScenarioKey}
                  isRunning={isRunning}
                  onRun={runScenario}
                />
              ))}
            </div>
          </div>

          <VerdictCard verdict={latestVerdict} />
        </aside>

        <div className="space-y-4">
          <section className="rounded-2xl border border-soc-border bg-soc-bg/30 p-4">
            <div>
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-xs font-medium text-soc-muted">Current run</p>
                  <h3 className="mt-0.5 text-base font-medium text-soc-text">
                    {activeScenario.title} · {activeScenario.actorName}
                  </h3>
                </div>
                <span className={`rounded border px-2 py-0.5 text-[11px] font-medium ${tokenFor(activeScenario.accent).badge}`}>
                  {isRunning ? "In progress" : activePhase ? "Completed" : "Not started"}
                </span>
              </div>

              <div className="mt-5 grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_320px]">
                <div className="space-y-4">
                  <div className="rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
                    <div className="flex items-center gap-3">
                      <ActorAvatar scenario={activeScenario} large />
                      <div>
                        <p className="text-xs font-medium text-soc-muted">{activeScenario.role}</p>
                        <h4 className="mt-1 text-lg font-medium text-soc-text">{activeScenario.actorName}</h4>
                        <p className="text-sm text-soc-muted">{activeScenario.device}</p>
                      </div>
                    </div>
                    <div className="mt-4 space-y-2 text-sm text-soc-text">
                      <p><span className="font-medium text-soc-muted">Source IP:</span> {activeScenario.ipAddress}</p>
                      <p><span className="font-medium text-soc-muted">Expected lane:</span> {activeScenario.expectedLane}</p>
                      <p className="text-soc-muted">{activeScenario.expectation}</p>
                    </div>
                  </div>

                  <FeedbackCard feedback={scene.feedback} />
                  <RetrainingCard retraining={scene.retraining} />
                </div>

                <div className="space-y-4">
                  <div className="rounded-2xl border border-soc-border/70 bg-soc-panel/45 p-4" style={{ perspective: "1400px" }}>
                    <div className="soc-tilt-panel rounded-2xl border border-soc-border/70 bg-soc-panelSoft/40 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs font-medium text-soc-muted">Pipeline stages</p>
                        <span className="rounded-full border border-soc-electric/25 bg-soc-electric/10 px-2 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-soc-electric">
                          {activePhase || "idle"}
                        </span>
                      </div>

                      <div className="mt-4">
                        <GlowPipeline phases={THEATER_PHASES} activePhase={activePhase} isRunning={isRunning} />
                      </div>
                    </div>
                  </div>

                  <RouteBoard route={scene.route} />
                </div>

                <BrowserMock browser={scene.browser} scenario={activeScenario} />
              </div>
            </div>
          </section>

          <TracePanel logs={logs} runError={runError} usedFallback={usedFallback} />
        </div>
      </div>
    </section>
  );
}
