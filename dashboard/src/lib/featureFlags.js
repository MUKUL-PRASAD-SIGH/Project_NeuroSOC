export const DEMO_DATA_ENABLED = String(import.meta.env.VITE_USE_MOCKS || "false").toLowerCase() === "true";

export const MODEL_INTEGRATION_ENABLED =
  String(import.meta.env.VITE_MODEL_INTEGRATION_ENABLED || "false").toLowerCase() === "true";

// The SDK protection page (universal behavioral engine). Off unless the backend runs with ENABLE_UNIVERSAL_ENGINE=true.
export const UNIVERSAL_ENABLED = String(import.meta.env.VITE_UNIVERSAL_ENABLED || "false").toLowerCase() === "true";

// Shows the NovaTrust demo's "Security Testing" panel. Both sides must agree: the API must also run with
// NEUROSOC_DEMO_MODE=true (the panel additionally checks GET /api/v1/demo/config, so a mismatch hides it).
export const DEMO_MODE_ENABLED = String(import.meta.env.VITE_DEMO_MODE || "false").toLowerCase() === "true";
