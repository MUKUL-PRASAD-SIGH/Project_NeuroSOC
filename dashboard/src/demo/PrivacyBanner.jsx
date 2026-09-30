import { Button } from "./ui";

// Shown until the visitor chooses. The NeuroSOC SDK stays dormant (no requests, no capture) until Accept.
export default function PrivacyBanner({ onAccept, onDecline }) {
  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby="privacy-title"
      aria-describedby="privacy-body"
      className="fixed inset-x-4 bottom-4 z-40 mx-auto max-w-xl rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
    >
      <h2 id="privacy-title" className="text-sm font-semibold text-slate-900">Privacy &amp; Security</h2>
      <p id="privacy-body" className="mt-1.5 text-[13px] leading-relaxed text-slate-600">
        We use security telemetry to protect your account, detect abuse, and improve the safety of this application.
        We record how you interact with pages (timing and movement), never what you type.
      </p>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button variant="secondary" onClick={onDecline}>Not now</Button>
        <Button onClick={onAccept}>Accept</Button>
      </div>
    </div>
  );
}
