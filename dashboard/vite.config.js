import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { assertMocksDisabledForBuild } from "../scripts/productionBuildGuard.mjs";

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  assertMocksDisabledForBuild(command, env, "NeuroSOC dashboard");
  const apiTarget = env.VITE_API_URL || "http://localhost:8000";
  const ingestionTarget = env.VITE_INGESTION_URL || "http://localhost:8080";

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
        "/ws": {
          target: apiTarget,
          ws: true,
          changeOrigin: true,
        },
        "/ingest": {
          target: ingestionTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
