// Data access for the SDK protection page (universal behavioral engine, /api/v1/universal/*).
import { apiClient, buildWsUrl } from "../lib/apiClient";
import { getAccessToken } from "../lib/auth";

export async function fetchLatestVerdicts(limit = 200) {
  const { data } = await apiClient.get("/api/v1/universal/verdicts/latest", { params: { limit } });
  return data.verdicts || [];
}

export async function fetchIntegrity(resourceId) {
  const { data } = await apiClient.get(`/api/v1/universal/resources/${encodeURIComponent(resourceId)}/integrity`);
  return data;
}

export async function fetchEntity(entityType, entityId) {
  const { data } = await apiClient.get(
    `/api/v1/universal/entities/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`
  );
  return data;
}

export async function overrideVerdict(verdictId, decision) {
  const { data } = await apiClient.post(`/api/v1/universal/verdicts/${encodeURIComponent(verdictId)}/override`, { decision });
  return data;
}

export async function fetchSites() {
  const { data } = await apiClient.get("/api/v1/universal/sites");
  return data.sites || [];
}

/** Live universal verdicts: a snapshot on connect, then one message per verdict. Reconnects. */
export function subscribeToUniversal({ onSnapshot, onVerdict, onStatusChange }) {
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
