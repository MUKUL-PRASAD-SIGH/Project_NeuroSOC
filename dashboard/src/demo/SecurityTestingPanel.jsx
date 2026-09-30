import { useState } from "react";
import { Link } from "react-router-dom";
import { describeError, runSimulation } from "./demoApi";
import { Button, Card, Notice, Pill } from "./ui";

const TESTS = [
  { type: "prompt_injection", label: "Prompt injection", help: "Nova AI reads an invoice that hides an instruction to wire money to an unknown payee." },
  { type: "unauthorized_resource", label: "Unauthorized resource", help: "Nova AI tries to move funds from token.transfer on a vault it is not registered for." },
  { type: "excessive_actions", label: "Excessive actions", help: "Nova AI attempts about 20 transfers in a few seconds." },
  { type: "suspicious_session", label: "Suspicious session", help: "A brand-new visitor signs up and immediately touches the treasury." },
];

const OUTCOME = {
  blocked: { tone: "bad", label: "Blocked" }, flagged: { tone: "warn", label: "Flagged" },
  unavailable: { tone: "warn", label: "Service unavailable" }, allowed: { tone: "good", label: "Allowed" },
};

// Demo-only. The parent renders this only when VITE_DEMO_MODE is on AND the API reports demo_mode.
export default function SecurityTestingPanel({ onPayload, onReset, disabled }) {
  const [running, setRunning] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function run(type) {
    setRunning(type);
    setError(null);
    try {
      const body = await runSimulation(type);
      setResult(body);
      onPayload?.(body);
    } catch (err) {
      setError(describeError(err, "The simulation could not run."));
    } finally {
      setRunning(null);
    }
  }

  return (
    <Card title="Security testing" action={<Pill tone="warn">Simulated · demo only</Pill>}>
      <p className="text-sm text-slate-600">
        These run against this demo's own fake data through the real NeuroSOC SDK. Nothing real is touched.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {TESTS.map((t) => (
          <div key={t.type} className="rounded-xl border border-slate-200 p-3.5">
            <p className="text-sm font-medium text-slate-900">{t.label}</p>
            <p className="mt-1 min-h-[2.5rem] text-xs leading-relaxed text-slate-500">{t.help}</p>
            <Button variant="secondary" className="mt-2.5 !py-1.5 text-xs" disabled={disabled || Boolean(running)} onClick={() => run(t.type)}>
              {running === t.type ? "Running…" : "Run test"}
            </Button>
          </div>
        ))}
      </div>
      {error ? <div className="mt-4"><Notice tone="bad">{error}</Notice></div> : null}
      {result ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm" role="status" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-slate-900">{result.title}</p>
            <Pill tone={OUTCOME[result.outcome]?.tone || "neutral"}>{OUTCOME[result.outcome]?.label || result.outcome}</Pill>
          </div>
          <p className="mt-1.5 text-slate-600">{result.reply}</p>
          {result.verdict ? (
            <div className="mt-2 text-xs text-slate-600">
              <p>Decision: <strong>{result.verdict.action}</strong> · risk {Number(result.verdict.risk).toFixed(2)}</p>
              <ul className="mt-1 list-disc pl-4">{(result.verdict.reasons || []).map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          ) : null}
          <Link className="mt-3 inline-block text-xs font-medium text-indigo-600 underline underline-offset-2" to="/protection?view=live">
            See it in the NeuroSOC dashboard
          </Link>
        </div>
      ) : null}
      <div className="mt-4 border-t border-slate-100 pt-3">
        <Button variant="secondary" className="!py-1.5 text-xs" onClick={onReset} disabled={Boolean(running)}>Reset demo</Button>
        <span className="ml-3 text-xs text-slate-400">Restores the account and un-pauses Nova AI.</span>
      </div>
    </Card>
  );
}
