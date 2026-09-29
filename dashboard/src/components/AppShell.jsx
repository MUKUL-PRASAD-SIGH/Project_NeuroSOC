import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { OIDC_REQUIRED } from "../lib/auth";
import { useDashboardStore } from "../store/dashboardStore";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/intel-feed", label: "Intel Feed" },
  { to: "/response-ops", label: "Response" },
];

function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
      <path
        d="M12 2.5 4 5.5v6c0 4.7 3.3 8.8 8 10 4.7-1.2 8-5.3 8-10v-6l-8-3Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M8.5 12.2 11 14.6l4.6-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
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

  return (
    <span className="inline-flex items-center gap-2 rounded-md border border-soc-border bg-soc-panelSoft px-2.5 py-1 text-xs text-soc-muted">
      <span className={connected ? "soc-live-dot" : "inline-block h-2 w-2 rounded-full bg-soc-amber"} />
      <span className="text-soc-text">{connected ? "Live" : "Connecting"}</span>
      <span className="hidden sm:inline">stream</span>
    </span>
  );
}

function UserBadge() {
  const { user, roles, isAuthenticated } = useDashboardStore((state) => state.auth);
  const doSignIn = useDashboardStore((state) => state.signIn);
  const doSignOut = useDashboardStore((state) => state.signOut);

  if (!isAuthenticated) {
    return (
      <button
        type="button"
        onClick={doSignIn}
        className="rounded-md border border-soc-electric/50 px-2.5 py-1 text-xs font-medium text-soc-electric transition hover:bg-soc-electric/10"
      >
        Sign in
      </button>
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
        className="rounded-md border border-soc-border/70 px-2.5 py-1 text-xs font-medium text-soc-muted transition hover:bg-soc-panelSoft"
      >
        Sign out
      </button>
    </div>
  );
}

function TopBar() {
  const now = useClock();

  return (
    <header className="sticky top-0 z-40 border-b border-soc-border bg-soc-bg/90 backdrop-blur">
      <div className="mx-auto flex min-h-14 w-full max-w-[1680px] flex-wrap items-center gap-x-6 px-4 md:px-6 lg:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-soc-electric/15 text-soc-electric">
            <BrandMark />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold tracking-tight text-soc-text">NeuroSOC</p>
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
          <span className="hidden font-mono text-xs text-soc-muted soc-tabular md:inline">
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
    if (!dataAllowed) return undefined;
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
            <h1 className="mt-2 text-lg font-semibold text-soc-text">Sign in to continue</h1>
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
        <Outlet />
      </main>
    </>
  );
}
