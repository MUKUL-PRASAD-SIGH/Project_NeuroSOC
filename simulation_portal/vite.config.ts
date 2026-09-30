import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {fileURLToPath} from 'url';
import {defineConfig, loadEnv} from 'vite';
import {assertMocksDisabledForBuild} from './scripts/productionBuildGuard.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({command, mode}) => {
  const env = loadEnv(mode, '.', '');
  assertMocksDisabledForBuild(command, env, 'NovaTrust simulation portal');
  const apiTarget = env.VITE_API_URL || 'http://localhost:8000';
  const ingestionTarget = env.VITE_INGESTION_URL || 'http://localhost:8080';
  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ws': {
          target: apiTarget,
          ws: true,
          changeOrigin: true,
        },
        '/ingest': {
          target: ingestionTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
