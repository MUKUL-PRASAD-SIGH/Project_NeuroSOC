import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DEMO_MODE_ENABLED } from "../lib/featureFlags";
import AccountView from "../demo/AccountView";
import DashboardView from "../demo/DashboardView";
import DemoLayout, { VIEWS } from "../demo/DemoLayout";
import NovaAssistant from "../demo/NovaAssistant";
import PrivacyBanner from "../demo/PrivacyBanner";
import SecurityTestingPanel from "../demo/SecurityTestingPanel";
import SecurityView from "../demo/SecurityView";
import ServiceNotice from "../demo/ServiceNotice";
import TransferForm from "../demo/TransferForm";
import { describeError, fetchAccount, resetDemo } from "../demo/demoApi";
import { readSite, writeSite } from "../demo/session";
import { Button, Card, Notice, Spinner } from "../demo/ui";
import { useDemoConfig } from "../demo/useDemoConfig";
import { useNeuroSoc } from "../demo/useNeuroSoc";
import { useNovaChat } from "../demo/useNovaChat";

function Shell({ children }) {
  return <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6"><div className="w-full max-w-md">{children}</div></div>;
}

// Application key, in order: what the dashboard wizard stored, a ?pk= link, then the site the API says is
// connected. There is no built-in fallback key: with none, the page tells you to add an application.
function resolveKey(params, config) {
  const stored = readSite();
  if (stored) return stored.publishable_key;
  const fromUrl = params.get("pk");
  if (fromUrl && /^pk_/.test(fromUrl)) return fromUrl;
  return config?.site?.publishable_key || null;
}

export default function CustomerDemo() {
  const [params] = useSearchParams();
  const { status, config, error, reload } = useDemoConfig();
  const [view, setView] = useState("dashboard");
  const [account, setAccount] = useState(null);
  const [agent, setAgent] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [outage, setOutage] = useState(false);

  const publishableKey = useMemo(() => resolveKey(params, config), [params, config]);
  const neuro = useNeuroSoc(publishableKey);

  useEffect(() => {
    const site = config?.site;
    if (site?.publishable_key && !readSite()) writeSite(site);
  }, [config]);

  const onPayload = useCallback((body) => {
    if (body?.account) setAccount(body.account);
    if (body?.agent) setAgent(body.agent);
    const steps = body?.steps || [];
    setOutage(body?.status === "unavailable" || steps.some((s) => s.status === "unavailable"));
  }, []);

  const loadAccount = useCallback(async () => {
    setLoadError(null);
    try { onPayload(await fetchAccount()); }
    catch (err) { setLoadError(describeError(err, "We couldn't load your account.")); }
  }, [onPayload]);

  useEffect(() => { if (status === "ready") loadAccount(); }, [status, loadAccount]);
  useEffect(() => { if (config?.agent) setAgent((current) => current || config.agent); }, [config]);

  const chat = useNovaChat({ onPayload, track: neuro.track });

  async function onReset() {
    try { onPayload(await resetDemo()); setOutage(false); }
    catch (err) { setLoadError(describeError(err, "The demo could not be reset.")); }
  }

  if (status === "loading") return <Shell><Spinner label="Loading NovaTrust" /></Shell>;
  if (status === "disabled") {
    return (
      <Shell>
        <Card title="NovaTrust demo is off">
          <p className="text-sm text-slate-600">The API was started without <code className="rounded bg-slate-100 px-1">NEUROSOC_DEMO_MODE=true</code>, so the demo application is not available.</p>
          <Link className="mt-3 inline-block text-sm font-medium text-indigo-600 underline underline-offset-2" to="/protection?view=sites">Back to NeuroSOC</Link>
        </Card>
      </Shell>
    );
  }
  if (status === "error") {
    return <Shell><Notice tone="bad" title="NovaTrust could not load" action={<Button variant="secondary" onClick={reload}>Retry</Button>}>{error}</Notice></Shell>;
  }

  const connected = Boolean(publishableKey) && Boolean(config?.connected);
  const showTesting = DEMO_MODE_ENABLED && config?.demo_mode === true;
  const views = VIEWS;

  return (
    <DemoLayout view={view} onView={setView} views={views} connected={connected} active={neuro.active} consent={neuro.consent}>
      <div className="space-y-5">
        {!publishableKey ? (
          <Notice tone="info" title="No application connected"
            action={<Link to="/protection?view=sites" className="text-sm font-medium text-indigo-700 underline underline-offset-2">Add an application</Link>}>
            Create an application in the NeuroSOC dashboard and choose “Launch NovaTrust”. Until then Nova AI can't move money.
          </Notice>
        ) : !config?.connected ? (
          <Notice tone="warn" title="Application not connected to the demo backend"
            action={<Link to="/protection?view=sites" className="text-sm font-medium text-amber-900 underline underline-offset-2">Open Applications</Link>}>
            Use “Launch NovaTrust” on the application so the backend can guard transfers.
          </Notice>
        ) : null}
        {neuro.error ? <Notice tone="warn" title="Telemetry unavailable">{neuro.error}</Notice> : null}
        {outage ? <ServiceNotice onRetry={() => setOutage(false)} /> : null}
        {loadError ? <Notice tone="bad" action={<Button variant="secondary" onClick={loadAccount}>Retry</Button>}>{loadError}</Notice> : null}

        {view === "dashboard" ? <DashboardView account={account} loading={!account && !loadError} onOpenAssistant={() => setView("assistant")} onOpenTransfer={() => setView("transfer")} /> : null}
        {view === "transfer" ? <TransferForm account={account} onAccount={onPayload} track={neuro.track} /> : null}
        {view === "assistant" ? <NovaAssistant chat={chat} account={account} agent={agent} demoMode={showTesting} onReset={onReset} /> : null}
        {view === "account" ? <AccountView account={account} /> : null}
        {view === "security" ? (
          <div className="space-y-5">
            <SecurityView consent={neuro.consent} onAccept={neuro.accept} onReopen={neuro.reopen} connected={connected} agent={agent} />
            {showTesting ? <div className="mx-auto max-w-2xl"><SecurityTestingPanel onPayload={onPayload} onReset={onReset} disabled={!connected} /></div> : null}
          </div>
        ) : null}
      </div>
      {publishableKey && neuro.consent === null ? <PrivacyBanner onAccept={neuro.accept} onDecline={neuro.decline} /> : null}
    </DemoLayout>
  );
}
