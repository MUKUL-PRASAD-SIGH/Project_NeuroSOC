// Script-tag entry point:
//   <script src=".../neurosoc.min.js" data-key="pk_..." data-endpoint="https://api..." async></script>
// Reads its settings from the tag, starts the SDK, and exposes it as window.NeuroSOC.
import { NeuroSOC } from "./index";

declare global {
  interface Window {
    NeuroSOC?: typeof NeuroSOC;
    neurosoc?: NeuroSOC;
    __NEUROSOC_CONFIG__?: { key: string; endpoint: string; debug?: boolean; relay?: boolean };
  }
}

function currentScript(): HTMLScriptElement | null {
  if (document.currentScript instanceof HTMLScriptElement) return document.currentScript;
  return document.querySelector<HTMLScriptElement>("script[data-key][src*='neurosoc']");
}

window.NeuroSOC = NeuroSOC;
if (!window.neurosoc) {
  const tag = currentScript();
  // The Lens extension sets __NEUROSOC_CONFIG__ instead of a script tag.
  const key = tag?.dataset.key ?? window.__NEUROSOC_CONFIG__?.key;
  const endpoint = tag?.dataset.endpoint ?? window.__NEUROSOC_CONFIG__?.endpoint;
  if (key && endpoint) {
    try {
      window.neurosoc = NeuroSOC.init({
        publishableKey: key,
        endpoint,
        waitForConsent: tag?.dataset.consent === "wait",
        debug: tag?.dataset.debug === "true" || Boolean(window.__NEUROSOC_CONFIG__?.debug),
        relay: !tag && Boolean(window.__NEUROSOC_CONFIG__?.relay),
      });
    } catch (error) {
      console.warn("[neurosoc] not started:", error);
    }
  }
}
