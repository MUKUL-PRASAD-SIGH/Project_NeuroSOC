import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getUserManager } from "../lib/auth";
import { useDashboardStore } from "../store/dashboardStore";

export default function AuthCallbackPage() {
  const navigate = useNavigate();
  const refreshAuth = useDashboardStore((state) => state.refreshAuth);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        await getUserManager().signinRedirectCallback();
        await refreshAuth();
        if (!cancelled) navigate("/", { replace: true });
      } catch (err) {
        if (!cancelled) setError(err?.message || "Sign-in failed.");
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [navigate, refreshAuth]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-soc-bg text-sm text-soc-muted">
      {error ? `Sign-in failed: ${error}` : "Completing sign-in…"}
    </div>
  );
}
