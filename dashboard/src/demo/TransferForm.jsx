import { useState } from "react";
import { describeError, sendTransfer } from "./demoApi";
import { money } from "./session";
import { Button, Card, Field, Notice, inputClass } from "./ui";

const RESULT = {
  sent: { tone: "good", title: "Transfer sent" },
  blocked: { tone: "warn", title: "Transfer stopped" },
  unavailable: { tone: "warn", title: "Security service temporarily unavailable" },
  error: { tone: "bad", title: "Transfer failed" },
};

export default function TransferForm({ account, onAccount, track }) {
  const [to, setTo] = useState("Alice");
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState("");
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const value = Number(amount);
  const invalid = !to.trim() || !(value > 0);
  const tooMuch = account && value > account.available_balance;

  function onReview(event) {
    event.preventDefault();
    if (invalid || tooMuch) return;
    setResult(null);
    setReview(true);
    void track?.({ action: "form.submit", resource: { id: "transfer-form", type: "form", sensitivity: "medium" } });
  }

  async function onSend() {
    setBusy(true);
    try {
      const body = await sendTransfer(to.trim(), value, purpose.trim());
      onAccount(body);
      setResult({ status: body.status, message: body.message, verdict: body.verdict });
      if (body.status === "sent") { setAmount(""); setPurpose(""); }
      setReview(false);
    } catch (err) {
      setResult({ status: "error", message: describeError(err, "We could not send that transfer.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Send money</h1>
        <p className="mt-1 text-sm text-slate-500">Available: {account ? money(account.available_balance) : "…"}</p>
      </div>

      {result ? (
        <Notice tone={RESULT[result.status]?.tone || "info"} title={RESULT[result.status]?.title}>
          {result.message}
          {result.verdict?.reasons?.length ? <ul className="mt-1.5 list-disc pl-4">{result.verdict.reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
        </Notice>
      ) : null}

      <Card>
        {!review ? (
          <form onSubmit={onReview} className="space-y-5" noValidate>
            <Field label="Recipient" htmlFor="nt-to">
              <input id="nt-to" className={inputClass} value={to} onChange={(e) => setTo(e.target.value)} placeholder="Name or account" autoComplete="off" />
            </Field>
            <Field label="Amount (USD)" htmlFor="nt-amount" hint={tooMuch ? "That is more than your available balance." : undefined}>
              <input id="nt-amount" className={inputClass} inputMode="decimal" type="number" min="0.01" step="0.01" value={amount}
                onChange={(e) => setAmount(e.target.value)} placeholder="0.00" aria-invalid={Boolean(tooMuch)} />
            </Field>
            <Field label="Purpose" htmlFor="nt-purpose">
              <input id="nt-purpose" className={inputClass} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Optional" maxLength={120} />
            </Field>
            <Button type="submit" className="w-full" disabled={invalid || tooMuch}>Review transfer</Button>
          </form>
        ) : (
          <div className="space-y-5">
            <dl className="divide-y divide-slate-100 text-sm">
              {[["To", to], ["Amount", money(value)], ["Purpose", purpose || "-"]].map(([k, v]) => (
                <div key={k} className="flex justify-between py-2.5"><dt className="text-slate-500">{k}</dt><dd className="font-medium text-slate-900">{v}</dd></div>
              ))}
            </dl>
            <div className="flex gap-2">
              <Button variant="secondary" className="flex-1" onClick={() => setReview(false)} disabled={busy}>Edit</Button>
              <Button className="flex-1" onClick={onSend} disabled={busy}>{busy ? "Sending…" : "Send"}</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
