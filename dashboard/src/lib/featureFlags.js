export const DEMO_DATA_ENABLED = String(import.meta.env.VITE_USE_MOCKS || "false").toLowerCase() === "true";

export const MODEL_INTEGRATION_ENABLED =
  String(import.meta.env.VITE_MODEL_INTEGRATION_ENABLED || "false").toLowerCase() === "true";

// The SDK protection page (universal behavioral engine). Off unless the backend runs with ENABLE_UNIVERSAL_ENGINE=true.
export const UNIVERSAL_ENABLED = String(import.meta.env.VITE_UNIVERSAL_ENABLED || "false").toLowerCase() === "true";
