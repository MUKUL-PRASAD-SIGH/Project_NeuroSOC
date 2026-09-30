import { useCallback, useEffect, useState } from "react";
import { describeError, fetchDemoConfig } from "./demoApi";

// status: "loading" | "ready" | "disabled" (the API has no demo routes: NEUROSOC_DEMO_MODE is off) | "error"
export function useDemoConfig() {
  const [state, setState] = useState({ status: "loading", config: null, error: null });

  const load = useCallback(async () => {
    try {
      setState({ status: "ready", config: await fetchDemoConfig(), error: null });
    } catch (err) {
      const code = err?.response?.status;
      setState(code === 404
        ? { status: "disabled", config: null, error: null }
        : { status: "error", config: null, error: describeError(err, "The NovaTrust service returned an error.") });
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  return { ...state, reload: load };
}
