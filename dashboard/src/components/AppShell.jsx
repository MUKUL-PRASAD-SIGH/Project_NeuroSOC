import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { OIDC_REQUIRED } from "../lib/auth";
import { DEMO_DATA_ENABLED, MODEL_INTEGRATION_ENABLED } from "../lib/featureFlags";
import { useDashboardStore } from "../store/dashboardStore";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/intel-feed", label: "Intel Feed" },
  { to: "/response-ops", label: "Response" },
];

function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
      <path d="M4 4l16 16M20 4 4 20M12 2v20M2 12h20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

function ConnectionStatus() {
  const status = useDashboardStore((state) => state.alerts.status);
  const connected = status === "connected";
  const label = DEMO_DATA_ENABLED ? "Demo data" : connected ? "Live" : "Connecting";

  return (
    <span
      role="status"
      aria-label={DEMO_DATA_ENABLED ? "Demo data stream" : `${label} alert stream`}
      className="inline-flex items-center gap-2 rounded-full border border-soc-border bg-soc-panelSoft px-3 py-1 text-xs text-soc-muted"
    >
      <span className={connected && !DEMO_DATA_ENABLED ? "soc-live-dot" : "inline-block h-2 w-2 rounded-full bg-soc-amber"} />
      <span className="text-soc-text">{label}</span>
      {DEMO_DATA_ENABLED ? <span className="hidden sm:inline">stream</span> : null}
    </span>
  );
}

function UserBadge() {
  const { user, roles, isAuthenticated } = useDashboardStore((state) => state.auth);
  const doSignIn = useDashboardStore((state) => state.signIn);
  const doSignOut = useDashboardStore((state) => state.signOut);

  if (!isAuthenticated) {
    return (
      <button type="button" onClick={doSignIn} className="soc-btn-primary">Sign in</button>
    );
  }

  const username = user?.profile?.preferred_username || user?.profile?.email || "analyst";
  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-xs text-soc-muted sm:inline">
        {username} · {roles[0] || "analyst"}
      </span>
      <button
        type="button"
        onClick={doSignOut}
        className="rounded-xl border border-soc-border/70 px-2.5 py-1 text-xs font-medium text-soc-muted transition hover:bg-soc-panelSoft"
      >
        Sign out
      </button>
    </div>
  );
}

function TopBar() {
  const now = useClock();

  return (
    <header className="sticky top-0 z-40 border-b border-soc-border bg-[#05070d]/75 backdrop-blur-xl">
      <div className="mx-auto flex min-h-14 w-full max-w-[1680px] flex-wrap items-center gap-x-6 px-4 md:px-6 lg:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-b from-[#7aa8ff] to-[#2f5fe0] text-white shadow-[0_6px_24px_-6px_rgba(91,147,255,0.9)]">
            <BrandMark />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-medium tracking-tight text-soc-text">NeuroSOC</p>
            <p className="text-[11px] text-soc-muted">Security Operations</p>
          </div>
        </div>

        <nav aria-label="Security operations sections" className="order-3 -mx-1 w-[calc(100%+0.5rem)] overflow-x-auto md:order-none md:mx-0 md:w-auto">
          <div className="flex min-w-max items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `relative flex h-12 items-center whitespace-nowrap px-3 text-sm font-medium transition-colors after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:transition-colors ${
                    isActive ? "text-soc-text after:bg-soc-electric" : "text-soc-muted after:bg-transparent hover:text-soc-text"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>

        <div className="ml-auto flex h-14 items-center gap-3">
          <ConnectionStatus />
          <span className="hidden  text-xs text-soc-muted soc-tabular md:inline">
            {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
          <UserBadge />
        </div>
      </div>
    </header>
  );
}

export default function AppShell() {
  const fetchStats = useDashboardStore((state) => state.fetchStats);
  const fetchModelStatus = useDashboardStore((state) => state.fetchModelStatus);
  const hydrateAlerts = useDashboardStore((state) => state.hydrateAlerts);
  const startAlertStream = useDashboardStore((state) => state.startAlertStream);
  const stopAlertStream = useDashboardStore((state) => state.stopAlertStream);
  const refreshAuth = useDashboardStore((state) => state.refreshAuth);
  const { isAuthenticated, checked } = useDashboardStore((state) => state.auth);

  useEffect(() => {
    refreshAuth();
  }, [refreshAuth]);

  const dataAllowed = !OIDC_REQUIRED || isAuthenticated;

  useEffect(() => {
    if (!dataAllowed) return undefined;
    fetchStats();
    const statsInterval = window.setInterval(fetchStats, 30000);

    return () => {
      window.clearInterval(statsInterval);
    };
  }, [fetchStats, dataAllowed]);

  useEffect(() => {
    if (!dataAllowed || !MODEL_INTEGRATION_ENABLED) return undefined;
    fetchModelStatus();
    const modelInterval = window.setInterval(fetchModelStatus, 60000);

    return () => {
      window.clearInterval(modelInterval);
    };
  }, [fetchModelStatus, dataAllowed]);

  useEffect(() => {
    if (!dataAllowed) return undefined;
    hydrateAlerts();
    startAlertStream();

    return () => {
      stopAlertStream();
    };
  }, [hydrateAlerts, startAlertStream, stopAlertStream, dataAllowed]);

  if (OIDC_REQUIRED && checked && !isAuthenticated) {
    return (
      <>
        <TopBar />
        <main className="soc-shell flex min-h-[60vh] items-center justify-center">
          <div className="soc-glass max-w-sm p-6 text-center">
            <p className="soc-kicker">Sign-in required</p>
            <h1 className="mt-2 text-lg font-medium text-soc-text">Sign in to continue</h1>
            <p className="mt-2 text-sm text-soc-muted">
              This deployment requires a Keycloak session to view live security data.
            </p>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <TopBar />
      <main className="soc-shell">
        {DEMO_DATA_ENABLED ? (
          <aside className="mb-5 flex items-center gap-2 rounded-full border border-soc-border bg-soc-panel px-4 py-2 text-xs leading-relaxed text-soc-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-soc-electric" /><span className="font-medium text-soc-text">Demo data.</span> Seeded events refresh locally. Analyst decisions stay in this browser and are not written to the backend.
          </aside>
        ) : null}
        <Outlet />
      </main>
    </>
  );
}
