import { useEffect, useRef, useState } from "react";
import { money } from "./session";
import { Button, Card, Notice, Pill, inputClass } from "./ui";

const SUGGESTIONS = ["What's my balance?", "Show recent transactions", "Summarize my portfolio", "Send $500 to Alice", "Cancel my last transfer"];
const TOOL_LABEL = {
  get_balance: "Checked your balance", get_transactions: "Looked up transactions", get_portfolio: "Reviewed your portfolio",
  create_transfer: "Prepared a transfer", cancel_transfer: "Cancelled a transfer",
};

function StepCard({ step, account, onConfirm, onCancel }) {
  const blocked = step.status === "blocked";
  const unavailable = step.status === "unavailable";
  const tx = step.tool === "create_transfer" && step.status === "executed"
    ? (account?.transactions || []).find((t) => t.id === step.result?.id) || step.result : null;
  return (
    <div className={`mt-2 rounded-xl border px-3.5 py-3 text-xs ${blocked ? "border-rose-200 bg-rose-50/60" : unavailable ? "border-amber-200 bg-amber-50/60" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-slate-800">{TOOL_LABEL[step.tool] || step.tool}</span>
        {blocked ? <Pill tone="bad">Blocked by NeuroSOC</Pill>
          : unavailable ? <Pill tone="warn">Security service unavailable</Pill>
          : step.status === "error" ? <Pill tone="bad">Couldn't complete</Pill> : <Pill tone="good">Done</Pill>}
      </div>
      {tx ? <p className="mt-1.5 text-slate-600">{money(tx.amount)} to {tx.counterparty} · {tx.id} · <strong className="font-medium">{tx.status}</strong></p> : null}
      {blocked && step.verdict ? (
        <div className="mt-1.5 text-slate-700">
          <p>Risk {Number(step.verdict.risk).toFixed(2)} · no money moved</p>
          <ul className="mt-1 list-disc pl-4">{(step.verdict.reasons || []).map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      ) : null}
      {step.status === "error" ? <p className="mt-1.5 text-slate-600">{step.error}</p> : null}
      {tx?.status === "pending" ? (
        <div className="mt-2.5 flex gap-2">
          <Button className="!px-3 !py-1.5 text-xs" onClick={() => onConfirm(tx.id)}>Confirm</Button>
          <Button variant="secondary" className="!px-3 !py-1.5 text-xs" onClick={() => onCancel(tx.id)}>Cancel</Button>
        </div>
      ) : null}
    </div>
  );
}

export default function NovaAssistant({ chat, account, agent, demoMode, onReset }) {
  const [draft, setDraft] = useState("");
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [chat.messages, chat.busy]);

  function submit(event) {
    event.preventDefault();
    chat.send(draft);
    setDraft("");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Nova AI</h1>
        <p className="mt-1 text-sm text-slate-500">Your financial assistant. Transfers it prepares wait for your confirmation.</p>
      </div>

      {agent?.status === "paused" ? (
        <Notice tone="warn" title="Nova AI is paused"
          action={demoMode ? <Button variant="secondary" onClick={onReset}>Reset demo</Button> : null}>
          NeuroSOC stopped a risky action, so Nova AI cannot move money until an analyst restores it.
        </Notice>
      ) : null}

      <Card className="!p-0">
        <div className="max-h-[28rem] min-h-[18rem] space-y-4 overflow-y-auto p-5" role="log" aria-live="polite" aria-label="Conversation with Nova AI">
          {chat.messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                m.role === "user" ? "bg-slate-900 text-white" : m.error ? "border border-rose-200 bg-rose-50 text-rose-900" : "bg-slate-100 text-slate-800"}`}>
                <p className="whitespace-pre-line">{m.text}</p>
                {(m.steps || []).filter((s) => s.tool !== "get_balance" || s.status !== "executed").length
                  ? (m.steps || []).filter((s) => ["create_transfer", "cancel_transfer"].includes(s.tool) || s.status !== "executed")
                      .map((s, i) => <StepCard key={i} step={s} account={account} onConfirm={chat.confirm} onCancel={chat.cancel} />)
                  : null}
              </div>
            </div>
          ))}
          {chat.busy ? <p className="text-xs text-slate-400" role="status">Nova AI is thinking…</p> : null}
          <div ref={endRef} />
        </div>
        <div className="border-t border-slate-100 px-5 py-3">
          <div className="mb-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" disabled={chat.busy} onClick={() => chat.send(s)}
                className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
          <form onSubmit={submit} className="flex gap-2">
            <input className={inputClass} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask Nova AI…" aria-label="Message Nova AI" maxLength={500} disabled={chat.busy} />
            <Button type="submit" disabled={chat.busy || !draft.trim()}>Send</Button>
          </form>
        </div>
      </Card>
    </div>
  );
}
