import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import path from "path";
import { fileURLToPath } from "url";
import { assertMocksDisabledForBuild } from "./scripts/productionBuildGuard.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  assertMocksDisabledForBuild(command, env, "NeuroSOC dashboard");
  // VITE_API_URL=/ makes the app call same-origin paths (no CORS); VITE_PROXY_TARGET then says where the dev
  // server forwards /api and /ws. Without it, the proxy target is VITE_API_URL, as before.
  const apiTarget = env.VITE_PROXY_TARGET || (/^https?:/.test(env.VITE_API_URL || "") ? env.VITE_API_URL : "http://localhost:8000");
  const ingestionTarget = env.VITE_INGESTION_URL || "http://localhost:8080";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@neurosoc/sdk": path.resolve(__dirname, "./src/sdk/index.ts"),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: apiTarget,
          ws: true,   // the live verdict feed connects at /api/v1/universal/ws
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
