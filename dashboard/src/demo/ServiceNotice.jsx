import { Button, Notice } from "./ui";

// Shown when the security service cannot be reached. Money-moving actions fail closed, so say so plainly.
export default function ServiceNotice({ message, onRetry }) {
  return (
    <Notice tone="warn" title="Security service temporarily unavailable"
      action={onRetry ? <Button variant="secondary" onClick={onRetry}>Try again</Button> : null}>
      {message || "Transfers are paused until protection is back, so nothing was sent. Balances and history still work."}
    </Notice>
  );
}
