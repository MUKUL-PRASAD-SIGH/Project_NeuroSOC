import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { connectDemoBackend, createSite, fetchDemoConfig, fetchSites } from "../../services/universalApi";
import { CodeBlock, CopyButton, EmptyState, Modal } from "./shared";
import { allSnippets } from "./snippets";

const SITE_STORAGE_KEY = "novatrust_demo_site"; // read by the customer demo (src/demo/session.js)
const AGENT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{1,62}$/;
const TOOL_RE = /^[A-Za-z0-9_.:-]{1,64}$/;

const APP_TYPES = [
  { id: "web", label: "Web app", help: "A website or web app with the JavaScript SDK." },
  { id: "agent", label: "AI agent", help: "A backend agent guarded with the Python SDK." },
  { id: "both", label: "Both", help: "A web app that also runs an AI agent." },
];
const MODES = [
  { id: "observe", label: "Monitor", help: "Records every decision and never blocks." },
  { id: "enforce", label: "Protect", help: "Blocks actions NeuroSOC judges unsafe." },
];
const SENSITIVE_CHOICES = ["token.transfer", "token.sell", "liquidity.remove", "permission.change", "api_key.create", "agent.config_change"];
const DEFAULT_TOOLS = ["get_balance", "get_transactions", "get_portfolio", "create_transfer", "cancel_transfer"];

const modeLabel = (mode) => (mode === "enforce" ? "Protect" : "Monitor");

function originOf(url) {
  try { return new URL(url).origin; } catch { return null; }
}

function initialForm() {
  return {
    name: "NovaTrust", url: `${window.location.origin}/demo`, appType: "both", mode: "enforce",
    agentId: "novatrust-agent", agentName: "Nova AI", tools: [...DEFAULT_TOOLS], customTool: "",
    sensitive: ["token.transfer"], resources: "treasury",
  };
}

function validate(form, step) {
  const errors = {};
  if (step >= 1) {
    if (!form.name.trim()) errors.name = "Give the application a name.";
    if (form.url.trim() && !/^https?:\/\/[^\s/$.?#][^\s]*$/i.test(form.url.trim())) errors.url = "Use a full URL starting with http:// or https://.";
  }
  if (step >= 2 && form.appType !== "web") {
    if (!AGENT_ID_RE.test(form.agentId)) errors.agentId = "2-63 letters, digits, dot, dash or underscore; start with a letter or digit.";
    if (!form.tools.length) errors.tools = "Choose at least one tool.";
  }
  return errors;
}

function buildPayload(form) {
  const origins = [...new Set([window.location.origin, originOf(form.url.trim())].filter(Boolean))];
  const payload = {
    name: form.name.trim(), mode: form.mode, app_type: form.appType, allowed_origins: origins,
    preset: form.name.trim().toLowerCase() === "novatrust" ? "novatrust" : null,
  };
  if (form.url.trim()) payload.url = form.url.trim();
  if (form.appType !== "web") {
    payload.agents = [{
      agent_id: form.agentId.trim(), name: form.agentName.trim() || null, tools: form.tools,
      sensitive_actions: form.sensitive,
      authorized_resources: form.resources.split(",").map((r) => r.trim()).filter(Boolean),
    }];
  }
  return payload;
}

function Field({ id, label, error, hint, children }) {
  return (
    <div>
      <label htmlFor={id} className="text-xs font-medium text-soc-text">{label}</label>
      {children}
      {hint && !error ? <p className="mt-1 text-[11px] text-soc-muted">{hint}</p> : null}
      {error ? <p id={`${id}-error`} className="mt-1 text-[11px] text-soc-red" role="alert">{error}</p> : null}
    </div>
  );
}

function Choice({ name, options, value, onChange }) {
  return (
    <div role="radiogroup" aria-label={name} className="grid gap-2 sm:grid-cols-3">
      {options.map((o) => (
        <label key={o.id} className={`soc-inset cursor-pointer p-3 text-xs ${value === o.id ? "ring-1 ring-soc-blue" : ""}`}>
          <input type="radio" className="sr-only" name={name} checked={value === o.id} onChange={() => onChange(o.id)} />
          <span className="block font-medium text-soc-text">{o.label}</span>
          <span className="mt-0.5 block text-soc-muted">{o.help}</span>
        </label>
      ))}
    </div>
  );
}

function AppStep({ form, set, errors }) {
  return (
    <div className="space-y-4">
      <Field id="app-name" label="Application name" error={errors.name}>
        <input id="app-name" className="soc-inset mt-1 w-full px-3 py-2 text-sm text-soc-text" value={form.name}
          onChange={(e) => set({ name: e.target.value })} aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? "app-name-error" : undefined} maxLength={128} />
      </Field>
      <Field id="app-url" label="Application URL (optional)" error={errors.url} hint="Used to allow browser requests from your site.">
        <input id="app-url" className="soc-inset mt-1 w-full px-3 py-2 text-sm text-soc-text" value={form.url}
          onChange={(e) => set({ url: e.target.value })} aria-invalid={Boolean(errors.url)} aria-describedby={errors.url ? "app-url-error" : undefined} />
      </Field>
      <div><p className="mb-1.5 text-xs font-medium text-soc-text">Application type</p><Choice name="Application type" options={APP_TYPES} value={form.appType} onChange={(appType) => set({ appType })} /></div>
      <div><p className="mb-1.5 text-xs font-medium text-soc-text">Protection mode</p><Choice name="Protection mode" options={MODES} value={form.mode} onChange={(mode) => set({ mode })} /></div>
    </div>
  );
}

function AgentStep({ form, set, errors }) {
  const toggle = (key, value) => set({ [key]: form[key].includes(value) ? form[key].filter((v) => v !== value) : [...form[key], value] });
  const addTool = () => {
    const tool = form.customTool.trim();
    if (TOOL_RE.test(tool) && !form.tools.includes(tool)) set({ tools: [...form.tools, tool], customTool: "" });
  };
  const toolChoices = [...new Set([...DEFAULT_TOOLS, ...form.tools])];
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="agent-id" label="Agent ID" error={errors.agentId} hint="The id your agent reports to NeuroSOC.">
          <input id="agent-id" className="soc-inset mt-1 w-full px-3 py-2 font-mono text-sm text-soc-text" value={form.agentId}
            onChange={(e) => set({ agentId: e.target.value })} aria-invalid={Boolean(errors.agentId)} aria-describedby={errors.agentId ? "agent-id-error" : undefined} />
        </Field>
        <Field id="agent-name" label="Agent name">
          <input id="agent-name" className="soc-inset mt-1 w-full px-3 py-2 text-sm text-soc-text" value={form.agentName} onChange={(e) => set({ agentName: e.target.value })} maxLength={128} />
        </Field>
      </div>
      <fieldset>
        <legend className="text-xs font-medium text-soc-text">Tools this agent may call</legend>
        <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
          {toolChoices.map((tool) => (
            <label key={tool} className="flex items-center gap-2 font-mono text-xs text-soc-text">
              <input type="checkbox" checked={form.tools.includes(tool)} onChange={() => toggle("tools", tool)} />{tool}
            </label>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <input aria-label="Add another tool" className="soc-inset flex-1 px-3 py-1.5 font-mono text-xs text-soc-text" placeholder="another_tool" value={form.customTool}
            onChange={(e) => set({ customTool: e.target.value })} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTool(); } }} />
          <button type="button" className="soc-btn" onClick={addTool}>Add</button>
        </div>
        {errors.tools ? <p className="mt-1 text-[11px] text-soc-red" role="alert">{errors.tools}</p> : null}
      </fieldset>
      <fieldset>
        <legend className="text-xs font-medium text-soc-text">Sensitive actions (counted against the per-minute limit)</legend>
        <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
          {SENSITIVE_CHOICES.map((action) => (
            <label key={action} className="flex items-center gap-2 font-mono text-xs text-soc-text">
              <input type="checkbox" checked={form.sensitive.includes(action)} onChange={() => toggle("sensitive", action)} />{action}
            </label>
          ))}
        </div>
      </fieldset>
      <Field id="agent-resources" label="Resources it may act on (comma separated)" hint="Anything else is treated as unauthorized and pauses the agent.">
        <input id="agent-resources" className="soc-inset mt-1 w-full px-3 py-2 font-mono text-sm text-soc-text" value={form.resources} onChange={(e) => set({ resources: e.target.value })} />
      </Field>
    </div>
  );
}

function KeysStep({ site, secret, form, confirmed, setConfirmed, showWarning, demoAvailable, onLaunch, launching, launchError }) {
  const [revealed, setRevealed] = useState(false);
  const [tab, setTab] = useState(form.appType === "agent" ? "python" : "script");
  const origin = window.location.origin;
  const agent = form.appType === "web" ? null : { agent_id: form.agentId, sensitive_tool: "create_transfer", sensitive_action: form.sensitive[0] || "token.transfer", resource: form.resources.split(",")[0]?.trim() || "treasury" };
  const snippets = useMemo(() => allSnippets({ origin, publishableKey: site.publishable_key, agent }), [origin, site.publishable_key, form.agentId]);
  const tabs = [
    ...(form.appType !== "agent" ? [{ id: "script", label: "Script tag" }, { id: "module", label: "JavaScript module" }] : []),
    ...(form.appType !== "web" ? [{ id: "python", label: "Python agent" }] : []),
  ];
  return (
    <div className="space-y-5">
      <div className="soc-inset space-y-3 p-4">
        <div>
          <p className="text-xs font-medium text-soc-text">Publishable key <span className="font-normal text-soc-muted">· safe to put in a web page</span></p>
          <div className="mt-1 flex items-center gap-2"><code className="flex-1 break-all text-xs text-soc-text">{site.publishable_key}</code><CopyButton value={site.publishable_key} /></div>
        </div>
        <div>
          <p className="text-xs font-medium text-soc-red">Secret key <span className="font-normal text-soc-muted">· server only, shown once</span></p>
          <div className="mt-1 flex items-center gap-2">
            <code className="flex-1 break-all text-xs text-soc-text">{revealed ? secret : "sk_" + "•".repeat(28)}</code>
            <button type="button" className="soc-btn" onClick={() => setRevealed(!revealed)} aria-pressed={revealed}>{revealed ? "Hide" : "Reveal"}</button>
            <CopyButton value={secret} />
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-soc-text">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I have copied the secret key somewhere safe. NeuroSOC cannot show it again.
        </label>
        {showWarning && !confirmed ? <p className="text-[11px] text-soc-red" role="alert">Confirm you copied the secret key first.</p> : null}
      </div>

      <div>
        <div role="tablist" aria-label="Integration snippets" className="flex gap-2">
          {tabs.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={`soc-btn ${tab === t.id ? "ring-1 ring-soc-blue" : ""}`} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
        <div className="mt-3" role="tabpanel"><CodeBlock code={snippets[tab] || snippets[tabs[0].id]} label={`${tab} integration snippet`} /></div>
        <p className="mt-2 text-[11px] text-soc-muted">Install the Python SDK with <code>pip install neurosoc</code>. The JavaScript SDK is not on npm yet: the script tag is served by this dashboard at <code>/neurosoc.min.js</code>.</p>
      </div>

      {demoAvailable && form.appType !== "web" ? (
        <div className="soc-inset flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="max-w-md text-xs text-soc-muted">Demo mode is on. Launch the NovaTrust sample app wired to this application, with Nova AI guarded by the secret key above (kept in server memory only).</p>
          <button type="button" className="soc-btn" disabled={!confirmed || launching} onClick={onLaunch}>{launching ? "Connecting…" : "Launch NovaTrust"}</button>
          {launchError ? <p className="basis-full text-[11px] text-soc-red" role="alert">{launchError}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function SiteCard({ site }) {
  const agents = site.agents || [];
  return (
    <li className="soc-glass p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-soc-text">{site.name}{site.demo ? <span className="ml-2 rounded border border-soc-border px-1.5 py-0.5 text-[10px] uppercase text-soc-muted">Demo</span> : null}</h3>
          <p className="mt-0.5 text-xs text-soc-muted">{site.app_type || "web"} · {modeLabel(site.mode)}{site.url ? ` · ${site.url}` : ""}</p>
        </div>
        {site.demo ? <Link className="soc-btn" to="/demo" onClick={() => localStorage.setItem(SITE_STORAGE_KEY, JSON.stringify({ site_id: site.site_id, publishable_key: site.publishable_key }))}>Open NovaTrust</Link> : null}
      </div>
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
        <div><dt className="text-soc-muted">Publishable key</dt><dd className="mt-0.5 flex items-center gap-2"><code className="break-all text-soc-text">{site.publishable_key}</code><CopyButton value={site.publishable_key} /></dd></div>
        <div><dt className="text-soc-muted">Agents</dt><dd className="mt-0.5 text-soc-text">{agents.length ? agents.map((a) => a.agent_id).join(", ") : "None registered"}</dd></div>
      </dl>
    </li>
  );
}

export default function SitesPanel() {
  const navigate = useNavigate();
  const [sites, setSites] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [created, setCreated] = useState(null); // {site, secret} lives only while the dialog is open
  const [confirmed, setConfirmed] = useState(false);
  const [showWarning, setShowWarning] = useState(false);
  const [demoAvailable, setDemoAvailable] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState(null);

  const load = useCallback(async () => {
    try { setSites(await fetchSites()); setError(null); }
    catch (err) { setError(err?.response?.data?.detail || "Could not load applications."); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { fetchDemoConfig().then((c) => setDemoAvailable(Boolean(c?.demo_mode))).catch(() => setDemoAvailable(false)); }, []);

  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const hasAgent = form.appType !== "web";

  function openWizard() {
    setForm(initialForm()); setErrors({}); setStep(1); setCreated(null); setConfirmed(false); setShowWarning(false);
    setSubmitError(null); setLaunchError(null); setOpen(true);
  }
  const close = useCallback(() => {
    if (created && !confirmed) { setShowWarning(true); return; }
    setOpen(false); setCreated(null); // the secret key is dropped from memory here
    load();
  }, [created, confirmed, load]);

  function next() {
    const found = validate(form, step);
    setErrors(found);
    if (Object.keys(found).length) return;
    if (step === 1 && hasAgent) setStep(2);
    else submit();
  }

  async function submit() {
    setSubmitting(true); setSubmitError(null);
    try {
      const response = await createSite(buildPayload(form));
      setCreated({ site: response.site, secret: response.secret_key });
      setStep(3);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSubmitError(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : err.message || "Could not create the application.");
    } finally { setSubmitting(false); }
  }

  async function launch() {
    setLaunching(true); setLaunchError(null);
    try {
      await connectDemoBackend(created.secret);
      localStorage.setItem(SITE_STORAGE_KEY, JSON.stringify({ site_id: created.site.site_id, publishable_key: created.site.publishable_key }));
      setOpen(false); setCreated(null);
      navigate("/demo");
    } catch (err) {
      setLaunchError(err?.response?.data?.detail || "Could not connect the demo backend.");
    } finally { setLaunching(false); }
  }

  const titles = { 1: "Add application: details", 2: "Add application: AI agent", 3: "Application created" };

  return (
    <section aria-labelledby="apps-title" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="apps-title" className="soc-section-title">Applications</h2>
          <p className="text-xs text-soc-muted">Each application gets its own keys, mode and registered agents.</p>
        </div>
        <button type="button" className="soc-btn" onClick={openWizard}>+ Add Application</button>
      </div>
      {error ? <p className="text-xs text-soc-red" role="alert">{error}</p> : null}
      {sites && !sites.length ? <EmptyState title="No applications yet">Add your first application to get keys and a copy-paste integration.</EmptyState> : null}
      {sites?.length ? <ul className="space-y-3">{sites.map((site) => <SiteCard key={site.site_id} site={site} />)}</ul> : null}

      {open ? (
        <Modal title={titles[step]} onClose={close}>
          {step === 1 ? <AppStep form={form} set={set} errors={errors} /> : null}
          {step === 2 ? <AgentStep form={form} set={set} errors={errors} /> : null}
          {step === 3 && created ? (
            <KeysStep site={created.site} secret={created.secret} form={form} confirmed={confirmed} setConfirmed={setConfirmed} showWarning={showWarning}
              demoAvailable={demoAvailable} onLaunch={launch} launching={launching} launchError={launchError} />
          ) : null}
          {submitError ? <p className="mt-4 text-xs text-soc-red" role="alert">{submitError}</p> : null}
          <div className="mt-6 flex justify-between gap-3">
            {step === 2 ? <button type="button" className="soc-btn" onClick={() => setStep(1)}>Back</button> : <span />}
            {step < 3
              ? <button type="button" className="soc-btn" disabled={submitting} onClick={next}>{step === 1 && hasAgent ? "Next" : submitting ? "Creating…" : "Create application"}</button>
              : <button type="button" className="soc-btn" disabled={!confirmed} onClick={close}>Done</button>}
          </div>
        </Modal>
      ) : null}
    </section>
  );
}
