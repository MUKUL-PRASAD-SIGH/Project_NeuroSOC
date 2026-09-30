import { Button, Card, Pill } from "./ui";

// The customer-facing security page: what is collected, the visitor's choice, and what protects Nova AI.
export default function SecurityView({ consent, onAccept, onReopen, connected, agent }) {
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight">Security &amp; privacy</h1>

      <Card title="Security telemetry"
        action={<Pill tone={consent === true ? "good" : "warn"}>{consent === true ? "On" : consent === false ? "Off" : "Not chosen"}</Pill>}>
        <p className="text-sm leading-relaxed text-slate-600">
          With your permission, NovaTrust records how you use pages (timing and movement) so it can tell you from a bot and
          catch account abuse. Nothing is recorded until you accept.
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>We record the <em>kind</em> of key pressed (letter, space, backspace), never the text you type.</li>
          <li>We record the shape and pace of mouse movement, and which page you are on.</li>
          <li>We do not record passwords, names, or message content.</li>
        </ul>
        <div className="mt-4">
          {consent === true
            ? <Button variant="secondary" onClick={onReopen}>Change my choice</Button>
            : <Button onClick={onAccept}>Turn on security telemetry</Button>}
        </div>
      </Card>

      <Card title="How Nova AI is kept safe">
        <ul className="space-y-3 text-sm text-slate-600">
          <li className="flex items-start justify-between gap-4">
            <span>Every transfer Nova AI prepares is checked by NeuroSOC before any money is held.</span>
            <Pill tone={connected ? "good" : "neutral"}>{connected ? "Active" : "Not connected"}</Pill>
          </li>
          <li>Nova AI can only use five tools, and only on your treasury account.</li>
          <li>Money moves only after you confirm a prepared transfer.</li>
          <li className="flex items-start justify-between gap-4">
            <span>If something looks wrong, Nova AI is paused until an analyst restores it.</span>
            <Pill tone={agent?.status === "paused" ? "bad" : "good"}>{agent?.status === "paused" ? "Paused" : "Running"}</Pill>
          </li>
        </ul>
      </Card>
    </div>
  );
}
