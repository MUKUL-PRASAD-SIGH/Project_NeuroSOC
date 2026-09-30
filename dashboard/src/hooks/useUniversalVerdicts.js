import { useEffect, useState } from "react";
import { fetchLatestVerdicts, subscribeToUniversal } from "../services/universalApi";

const KEEP = 1000;

/** Newest-first list of universal verdicts, kept live over the universal WebSocket. */
export function useUniversalVerdicts() {
  const [verdicts, setVerdicts] = useState([]);
  const [status, setStatus] = useState("connecting");
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    fetchLatestVerdicts(200)
      .then((items) => active && setVerdicts(items))
      .catch((err) => active && setError(err?.response?.status === 404
        ? "The SDK engine is not enabled on this server (ENABLE_UNIVERSAL_ENGINE=false)."
        : "Could not load verdicts."));

    const stop = subscribeToUniversal({
      onStatusChange: (next) => active && setStatus(next),
      onVerdict: (verdict) => active && setVerdicts((current) => {
        if (current.some((item) => item.verdict_id === verdict.verdict_id)) return current;
        return [verdict, ...current].slice(0, KEEP);
      }),
    });
    return () => {
      active = false;
      stop();
    };
  }, []);

  function replace(updated) {
    setVerdicts((current) => current.map((item) => (item.verdict_id === updated.verdict_id ? updated : item)));
  }

  return { verdicts, status, error, replace };
}
