import { useEffect, useState } from "react";
import { MODEL_INTEGRATION_ENABLED } from "../lib/featureFlags";
import { useDashboardStore } from "../store/dashboardStore";

const statusTone = {
  pending_approval: "border-soc-amber/50 bg-soc-amber/10 text-soc-amber",
  promoted: "border-soc-green/50 bg-soc-green/10 text-soc-green",
  rejected: "border-soc-border bg-soc-panelSoft/40 text-soc-muted",
};

export default function ModelCandidatesPanel() {
  const { items, loading, error } = useDashboardStore((state) => state.modelCandidates);
  const fetchModelCandidates = useDashboardStore((state) => state.fetchModelCandidates);
  const promoteCandidate = useDashboardStore((state) => state.promoteCandidate);
  const rejectCandidate = useDashboardStore((state) => state.rejectCandidate);
  const rollbackActiveModel = useDashboardStore((state) => state.rollbackActiveModel);
  const { roles } = useDashboardStore((state) => state.auth);
  const canManageModels = roles.includes("platform-admin");
  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);

  useEffect(() => {
    if (canManageModels && MODEL_INTEGRATION_ENABLED) fetchModelCandidates();
  }, [canManageModels, fetchModelCandidates]);

  async function runAction(id, action) {
    setBusyId(id);
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err?.response?.data?.detail || "That action failed. Try again.");
    } finally {
      setBusyId(null);
    }
  }

  const pending = items.filter((candidate) => candidate.status === "pending_approval");

  if (!MODEL_INTEGRATION_ENABLED) {
    return (
      <section className="soc-glass mt-4 p-5">
        <h2 className="soc-section-title">Candidate review</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-soc-muted">
          Candidate approval and rollback controls will appear after Colab artifacts are connected to the model registry. Model changes stay disabled until then.
        </p>
        <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-soc-muted">
          <span className="rounded border border-soc-border px-2.5 py-1.5">Artifact validation</span>
          <span className="rounded border border-soc-border px-2.5 py-1.5">Registry handoff</span>
          <span className="rounded border border-soc-border px-2.5 py-1.5">Promotion review</span>
        </div>
      </section>
    );
  }

  return (
    <section className="soc-glass mt-4 p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="soc-section-title">Model candidates</h2>
          <p className="mt-0.5 text-xs text-soc-muted">Review and change the model shared by all tenants.</p>
        </div>
        {canManageModels ? (
          <button
            type="button"
            disabled={busyId !== null}
            onClick={() => runAction("rollback", rollbackActiveModel)}
            className="rounded-xl border border-soc-amber/50 px-3 py-1.5 text-xs font-medium text-soc-amber transition hover:bg-soc-amber/10 disabled:opacity-50"
          >
            {busyId === "rollback" ? "Rolling back…" : "Rollback to previous"}
          </button>
        ) : null}
      </div>

      {error ? <p className="mt-3 text-sm text-soc-red">{error}</p> : null}
      {actionError ? <p className="mt-3 text-sm text-soc-red">{actionError}</p> : null}

      <div className="mt-4 space-y-2.5">
        {loading && items.length === 0 ? (
          <p className="text-sm text-soc-muted">Loading candidates…</p>
        ) : pending.length === 0 ? (
          <p className="rounded-xl border border-dashed border-soc-border p-4 text-center text-sm text-soc-muted">
            No candidates pending approval.
          </p>
        ) : (
          pending.map((candidate) => (
            <article
              key={candidate.candidateId}
              className="rounded-xl border border-soc-border/80 bg-soc-panelSoft/50 p-3.5"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-soc-text">
                    {candidate.modelKey.toUpperCase()} → v{candidate.proposedVersion}
                  </p>
                  <p className="mt-0.5 text-xs text-soc-muted">
                    from v{candidate.baseModelVersion} · held-out F1 {candidate.validationF1.toFixed(3)}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.1em] ${
                    statusTone[candidate.status] || statusTone.pending_approval
                  }`}
                >
                  {candidate.status.replace(/_/g, " ")}
                </span>
              </div>
              {canManageModels ? (
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    disabled={busyId !== null}
                    onClick={() => runAction(candidate.candidateId, () => promoteCandidate(candidate.candidateId))}
                    className="rounded-xl border border-soc-green/50 px-3 py-1.5 text-xs font-medium text-soc-green transition hover:bg-soc-green/10 disabled:opacity-50"
                  >
                    {busyId === candidate.candidateId ? "Working…" : "Promote"}
                  </button>
                  <button
                    type="button"
                    disabled={busyId !== null}
                    onClick={() => runAction(candidate.candidateId, () => rejectCandidate(candidate.candidateId))}
                    className="rounded-xl border border-soc-border/70 px-3 py-1.5 text-xs font-medium text-soc-muted transition hover:bg-soc-panelSoft disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              ) : null}
            </article>
          ))
        )}
      </div>
    </section>
  );
}
