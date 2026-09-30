import { useEffect, useState } from "react";
import { getApiBaseUrl } from "../../lib/apiClient";
import { fetchSites } from "../../services/universalApi";
import { EmptyState } from "./shared";

export default function SitesPanel() {
  const [sites, setSites] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(null);

  useEffect(() => {
    fetchSites().then(setSites).catch(() => setError("Could not load sites."));
  }, []);

  async function copy(text, id) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard unavailable: the snippet stays selectable */
    }
  }

  if (error) return <EmptyState title="Sites unavailable">{error}</EmptyState>;
  if (!sites) return <p className="py-8 text-center text-sm text-soc-muted">Loading…</p>;
  if (!sites.length) {
    return <EmptyState title="No sites registered">Register a site with <code>POST /api/v1/universal/sites</code> or seed <code>sdk/sites.local.json</code>.</EmptyState>;
  }

  return (
    <section className="space-y-3">
      {sites.map((site) => {
        const snippet = `<script src="https://cdn.jsdelivr.net/npm/@neurosoc/sdk/dist/neurosoc.min.js"\n        data-key="${site.publishable_key}" data-endpoint="${getApiBaseUrl()}" async></script>`;
        return (
          <article key={site.site_id} className="soc-glass p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="soc-section-title">{site.name}</h2>
                <p className="mt-0.5 font-mono text-xs text-soc-muted">{site.site_id}</p>
              </div>
              <span className={`rounded border px-2 py-0.5 text-[11px] font-medium ${site.mode === "enforce"
                ? "border-soc-electric/50 text-soc-electric" : "border-soc-border text-soc-muted"}`}>
                {site.mode === "enforce" ? "Enforce" : "Observe only"}
              </span>
            </div>
            <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
              <div><dt className="soc-kicker">Allowed origins</dt><dd className="mt-1 break-all font-mono text-soc-text">{site.allowed_origins.join(", ") || "server-side only"}</dd></div>
              <div><dt className="soc-kicker">Rules</dt><dd className="mt-1 text-soc-text">{site.rules.length}{site.preset ? ` · preset ${site.preset}` : ""}</dd></div>
              <div><dt className="soc-kicker">Webhooks</dt><dd className="mt-1 text-soc-text">{site.webhooks.length}</dd></div>
            </dl>
            <div className="mt-3">
              <div className="flex items-center justify-between">
                <p className="soc-kicker">Install</p>
                <button type="button" className="soc-btn" onClick={() => copy(snippet, site.site_id)}>
                  {copied === site.site_id ? "Copied" : "Copy snippet"}
                </button>
              </div>
              <pre className="soc-inset mt-2 overflow-x-auto p-3 font-mono text-[11px] leading-relaxed text-soc-text">{snippet}</pre>
            </div>
          </article>
        );
      })}
    </section>
  );
}
