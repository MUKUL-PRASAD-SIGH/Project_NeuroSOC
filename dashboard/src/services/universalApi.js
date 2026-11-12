// Data access for the SDK protection page (universal behavioral engine, /api/v1/universal/*).
import { apiClient, buildWsUrl } from "../lib/apiClient";
import { getAccessToken } from "../lib/auth";

// Demo-data mode (same switch dashboardApi.js uses): serve seeded data from the browser so the
// page matches the "Demo data" banner instead of reporting the engine as unavailable.
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";
const mocks = () => import("../mocks/universalData").then((module) => module.mockUniversal);
const DEMO_READ_ONLY = "Demo data is read-only. Connect the API to add or change applications.";

export async function fetchLatestVerdicts(limit = 200) {
  if (USE_MOCKS) return (await mocks()).latest(limit);
  const { data } = await apiClient.get("/api/v1/universal/verdicts/latest", { params: { limit } });
  return data.verdicts || [];
}

export async function fetchIntegrity(resourceId) {
  if (USE_MOCKS) return (await mocks()).integrity(resourceId);
  const { data } = await apiClient.get(`/api/v1/universal/resources/${encodeURIComponent(resourceId)}/integrity`);
  return data;
}

export async function fetchEntity(entityType, entityId) {
  if (USE_MOCKS) return (await mocks()).entity(entityType, entityId);
  const { data } = await apiClient.get(
    `/api/v1/universal/entities/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`
  );
  return data;
}

export async function overrideVerdict(verdictId, decision) {
  if (USE_MOCKS) return (await mocks()).override(verdictId, decision);
  const { data } = await apiClient.post(`/api/v1/universal/verdicts/${encodeURIComponent(verdictId)}/override`, { decision });
  return data;
}

export async function fetchSites() {
  if (USE_MOCKS) return (await mocks()).sites();
  const { data } = await apiClient.get("/api/v1/universal/sites");
  return data.sites || [];
}

export async function createSite(siteData) {
  if (USE_MOCKS) throw new Error(DEMO_READ_ONLY);
  const { data } = await apiClient.post("/api/v1/universal/sites", siteData);
  return data;
}

export async function updateSite(siteId, siteData) {
  if (USE_MOCKS) throw new Error(DEMO_READ_ONLY);
  const { data } = await apiClient.put(`/api/v1/universal/sites/${encodeURIComponent(siteId)}`, siteData);
  return data;
}

// The NovaTrust demo backend (only exists when the API runs with NEUROSOC_DEMO_MODE=true).
export async function fetchDemoConfig() {
  if (USE_MOCKS) return { demo_mode: false };
  const { data } = await apiClient.get("/api/v1/demo/config");
  return data;
}

// Hands the new application's secret key to the demo backend (server memory only; it is never returned).
export async function connectDemoBackend(secretKey) {
  if (USE_MOCKS) throw new Error(DEMO_READ_ONLY);
  const { data } = await apiClient.post("/api/v1/demo/connect", { secret_key: secretKey });
  return data;
}

/** Live universal verdicts: a snapshot on connect, then one message per verdict. Reconnects. */
export function subscribeToUniversal({ onSnapshot, onVerdict, onStatusChange }) {
  if (USE_MOCKS) {
    let stop = () => {};
    let cancelled = false;
    mocks().then((mock) => {
      if (!cancelled) stop = mock.subscribe({ onSnapshot, onVerdict, onStatusChange });
    });
    return () => {
      cancelled = true;
      stop();
    };
  }
  let socket;
  let timer;
  let closed = false;

  const connect = async () => {
    if (closed) return;
    onStatusChange?.("connecting");
    const token = await getAccessToken();
    const url = buildWsUrl("/api/v1/universal/ws");
    socket = new WebSocket(token ? `${url}?access_token=${encodeURIComponent(token)}` : url);
    socket.onopen = () => onStatusChange?.("connected");
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "universal.snapshot") onSnapshot?.(message.data || []);
        if (message.type === "universal.verdict") onVerdict?.(message.data);
      } catch {
        /* ignore malformed frames */
      }
    };
    socket.onclose = () => {
      onStatusChange?.("disconnected");
      if (!closed) timer = window.setTimeout(connect, 3000);
    };
  };

  connect();
  return () => {
    closed = true;
    window.clearTimeout(timer);
    socket?.close();
  };
}
