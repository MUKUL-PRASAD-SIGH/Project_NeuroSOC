import { useCallback, useEffect, useState } from "react";
import { NeuroSOC } from "@neurosoc/sdk";
import { clearConsent, readConsent, writeConsent } from "./session";

const ACCOUNT_ID = "act_alex_novatrust";
let shared = null; // {key, client}: one SDK client per key, even when React mounts the component twice in dev

function clientFor(publishableKey) {
  if (shared?.key === publishableKey) return shared.client;
  // Same-origin endpoint: the dev server / nginx proxies /api to NeuroSOC. waitForConsent keeps the SDK dormant:
  // it sends nothing, and starts no capture, until consent(true).
  const client = NeuroSOC.init({ publishableKey, endpoint: window.location.origin, waitForConsent: true });
  shared = { key: publishableKey, client };
  return client;
}

/**
 * The real NeuroSOC JavaScript SDK for the customer app.
 * consent: true (accepted) | false (declined) | null (not asked yet). Nothing is collected unless true.
 */
export function useNeuroSoc(publishableKey) {
  const [consent, setConsent] = useState(readConsent);
  const [sdk, setSdk] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!publishableKey) {
      setSdk(null);
      return;
    }
    try {
      const client = clientFor(publishableKey);
      setSdk(client);
      setError(null);
      if (readConsent() === true) {   // a returning visitor who already accepted
        client.consent(true);
        client.identify({ id: ACCOUNT_ID, type: "human" });
      }
    } catch (err) {
      setError(err?.message || "The NeuroSOC SDK could not start.");
    }
  }, [publishableKey]);

  const decide = useCallback((granted) => {
    writeConsent(granted);
    setConsent(granted);
    if (!sdk) return;
    if (granted) {
      sdk.consent(true);
      sdk.identify({ id: ACCOUNT_ID, type: "human" });
      void sdk.track({ action: "auth.login", resource: { id: "novatrust-session", type: "account", sensitivity: "medium" } });
    } else {
      sdk.consent(false);   // stops capture; harmless if it never started
    }
  }, [sdk]);

  const reopen = useCallback(() => {   // "change my privacy choice"
    sdk?.consent(false);
    clearConsent();
    setConsent(null);
  }, [sdk]);

  // Best-effort telemetry: a no-op without consent, and a security-service failure never reaches the page.
  const track = useCallback((input) => {
    if (!sdk || consent !== true) return Promise.resolve(null);
    return sdk.track(input).catch(() => null);
  }, [sdk, consent]);

  return {
    sdk, error, consent, track, reopen,
    accept: () => decide(true),
    decline: () => decide(false),
    active: Boolean(sdk) && consent === true,
    sessionId: sdk?.sessionId ?? null,
  };
}
