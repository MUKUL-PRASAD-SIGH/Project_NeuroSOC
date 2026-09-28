import { useDashboardStore } from "../store/dashboardStore";

export default function ModelStatusCard() {
  const modelStatus = useDashboardStore((state) => state.modelStatus);
  const { data, loading, error, lastUpdated } = modelStatus;

  const versions = Array.isArray(data?.versions) ? data.versions : [];
  const scores = (Array.isArray(data?.validationF1) ? data.validationF1 : []).filter(
    (entry) => entry?.value !== null && entry?.value !== undefined && Number.isFinite(Number(entry.value)),
  );

  return (
    <section className="soc-glass flex flex-col p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="soc-section-title">Model</h2>
          <p className="mt-0.5 text-xs text-soc-muted">Active inference ensemble</p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs text-soc-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${error ? "bg-soc-red" : loading ? "bg-soc-amber" : "bg-soc-green"}`} />
          {error ? "Unavailable" : loading ? "Syncing" : "Healthy"}
        </span>
      </div>

      {error ? <p className="mt-3 text-sm text-soc-red">{error}</p> : null}

      <dl className="mt-4 divide-y divide-soc-border/70 border-y border-soc-border/70">
        {versions.length === 0 ? (
          <div className="py-2 text-sm text-soc-muted">No version metadata yet.</div>
        ) : (
          versions.map((version) => (
            <div key={version.label} className="flex items-center justify-between gap-4 py-2">
              <dt className="text-xs text-soc-muted">{version.label}</dt>
              <dd className="truncate font-mono text-xs text-soc-text" title={version.value}>
                {version.value}
              </dd>
            </div>
          ))
        )}
      </dl>

      {scores.length ? (
        <div className="mt-4">
          <p className="text-xs font-medium text-soc-muted">Reported validation F1</p>
          <div className="mt-2 space-y-2.5">
            {scores.map((entry) => {
              const value = Number(entry.value) || 0;
              return (
                <div key={entry.label} className="grid grid-cols-[88px_minmax(0,1fr)_40px] items-center gap-3">
                  <span className="truncate text-xs text-soc-text">{entry.label.replace(/_/g, " ")}</span>
                  <div className="h-1.5 rounded-full bg-soc-panelSoft">
                    <div className="h-1.5 rounded-full bg-soc-electric" style={{ width: `${Math.min(Math.max(value * 100, 2), 100)}%` }} />
                  </div>
                  <span className="soc-tabular text-right font-mono text-xs text-soc-muted">{value.toFixed(2)}</span>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-soc-muted">
            Manifest values only. Dataset provenance and full production evaluation are still pending.
          </p>
        </div>
      ) : (
        <p className="mt-4 text-xs text-soc-muted">No validation metric is recorded in the active model manifest.</p>
      )}

      <div className="mt-auto flex items-center justify-between gap-3 pt-4 text-[11px] text-soc-muted">
        <span>Retrained {data?.lastRetrainedAt ? new Date(data.lastRetrainedAt).toLocaleString() : "—"}</span>
        <span>Checked {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : "—"}</span>
      </div>
    </section>
  );
}
