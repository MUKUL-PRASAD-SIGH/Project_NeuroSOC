export const DEMO_DATA_ENABLED = String(import.meta.env.VITE_USE_MOCKS || "false").toLowerCase() === "true";

export const MODEL_INTEGRATION_ENABLED =
  String(import.meta.env.VITE_MODEL_INTEGRATION_ENABLED || "false").toLowerCase() === "true";
