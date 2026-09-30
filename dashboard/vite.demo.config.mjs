import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { assertMocksDisabledForBuild } from "./scripts/productionBuildGuard.mjs";

const demoEnv = {
  VITE_API_URL: "http://localhost:8000",
  VITE_USE_MOCKS: "true",
  VITE_DEV_MOCK_FALLBACK: "false",
  VITE_ENABLE_MSW: "false",
  VITE_MODEL_INTEGRATION_ENABLED: "false",
  VITE_OIDC_REQUIRED: "false",
  VITE_KEYCLOAK_URL: "http://localhost:8081",
  VITE_KEYCLOAK_REALM: "neurosoc",
  VITE_KEYCLOAK_CLIENT_ID: "neurosoc-dashboard",
  VITE_NOVATRUST_TRUSTED_PASSWORD: "",
  VITE_NOVATRUST_REVIEW_PASSWORD: "",
};

export default defineConfig(({ command }) => {
  assertMocksDisabledForBuild(command, demoEnv, "NeuroSOC demo profile");

  return {
    envDir: false,
    envPrefix: "NEUROSOC_PUBLIC_",
    plugins: [react()],
    define: Object.fromEntries(
      Object.entries(demoEnv).map(([key, value]) => [`import.meta.env.${key}`, JSON.stringify(value)]),
    ),
  };
});
