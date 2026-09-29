import { apiClient, buildWsUrl, getApiBaseUrl } from "../lib/apiClient";
import {
  createMockAlert,
  mockAlerts,
  mockModelStatus,
  mockStats,
} from "../mocks/data";

const MAX_ALERTS = 50;
const DEV_MOCK_STREAM_INTERVAL_MS = 6000;
const SOCKET_RECONNECT_DELAY_MS = 3000;
let preferMockData = false;
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";

function isDevelopmentMockFallbackEnabled() {
  return import.meta.env.DEV && import.meta.env.VITE_DEV_MOCK_FALLBACK === "true";
}

function isNetworkError(error) {
  if (!error) {
    return false;
  }

  if (error.name === "AxiosError") {
    return !error.response;
  }

  if (error instanceof TypeError) {
    return /fetch|network/i.test(error.message);
  }

  return false;
}

async function withMockFallback(loadLiveData, loadMockData) {
  if (preferMockData && isDevelopmentMockFallbackEnabled()) {
    return loadMockData();
  }

  try {
    return await loadLiveData();
  } catch (error) {
    if (isDevelopmentMockFallbackEnabled() && isNetworkError(error)) {
      preferMockData = true;
      return loadMockData();
    }
    throw error;
  }
}

function startMockAlertStream({ onMessage, onStatusChange }) {
  onStatusChange?.("connected");

  const intervalId = window.setInterval(() => {
    onMessage?.(normalizeAlert(createMockAlert()));
  }, DEV_MOCK_STREAM_INTERVAL_MS);

  return () => {
    window.clearInterval(intervalId);
    onStatusChange?.("disconnected");
  };
}

function normalizeAlert(alert) {
  return {
    id: alert.id,
    severity: alert.severity || "medium",
    verdict: alert.verdict || "LEGITIMATE",
    message: alert.message,
    timestamp: alert.timestamp,
    sourceIp: alert.sourceIp || "",
    userId: alert.userId || "unknown-user",
    userName: alert.userName || "Unknown User",
    locationLabel: alert.locationLabel || "Unknown location",
    score: typeof alert.score === "number" ? alert.score : 0,
    dimensions: Array.isArray(alert.dimensions) ? alert.dimensions : [],
    recentVerdicts: Array.isArray(alert.recentVerdicts) ? alert.recentVerdicts : [],
    modelVersion: alert.modelVersion || null,
    status: alert.status || "new",
    decision: alert.decision || null,
    explanation: alert.explanation || null,
  };
}

function sortAlerts(alerts) {
  return [...alerts]
    .map(normalizeAlert)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, MAX_ALERTS);
}

export async function getStats() {
  if (USE_MOCKS) {
    return mockStats;
  }
  return withMockFallback(
    async () => {
      const { data } = await apiClient.get("/api/v1/stats");
      return data;
    },
    () => mockStats
  );
}

export async function getModelVersion() {
  if (USE_MOCKS) {
    return mockModelStatus;
  }
  return withMockFallback(
    async () => {
      const { data } = await apiClient.get("/api/v1/model/version");
      return data;
    },
    () => mockModelStatus
  );
}

export async function getAlerts() {
  if (USE_MOCKS) {
    return sortAlerts(mockAlerts);
  }
  return withMockFallback(
    async () => {
      const { data } = await apiClient.get("/api/v1/alerts");
      return sortAlerts(Array.isArray(data) ? data : []);
    },
    () => sortAlerts(mockAlerts)
  );
}

export async function getSandboxReplay(sessionId) {
  if (USE_MOCKS || !sessionId) {
    return null;
  }
  try {
    const { data } = await apiClient.get(`/api/v1/sandbox/${encodeURIComponent(sessionId)}/replay`);
    return data;
  } catch {
    // Sessions that were never diverted have no replay.
    return null;
  }
}

export async function getModelCandidates() {
  if (USE_MOCKS) {
    return [];
  }
  const { data } = await apiClient.get("/api/v1/models/candidates");
  return Array.isArray(data) ? data : [];
}

export async function promoteModelCandidate(candidateId) {
  const { data } = await apiClient.post(`/api/v1/models/candidates/${encodeURIComponent(candidateId)}/promote`);
  return data;
}

export async function rejectModelCandidate(candidateId) {
  const { data } = await apiClient.post(`/api/v1/models/candidates/${encodeURIComponent(candidateId)}/reject`);
  return data;
}

export async function rollbackModel() {
  const { data } = await apiClient.post("/api/v1/models/rollback");
  return data;
}

export async function submitAlertDecision(sessionId, decision, notes) {
  if (USE_MOCKS || !sessionId) {
    return {
      sessionId,
      decision,
      status: decision === "confirm_threat" || decision === "false_positive" ? "closed" : "triaged",
      decidedBy: "mock-analyst",
      decidedAt: new Date().toISOString(),
      trainingLabelWritten: null,
    };
  }
  const { data } = await apiClient.post(
    `/api/v1/alerts/${encodeURIComponent(sessionId)}/decision`,
    { decision, notes: notes || null }
  );
  return data;
}

export function subscribeToAlerts({ onMessage, onStatusChange, onError }) {
  if (USE_MOCKS || (preferMockData && isDevelopmentMockFallbackEnabled())) {
    return startMockAlertStream({ onMessage, onStatusChange });
  }

  let socket;
  let reconnectTimer;
  let isClosed = false;
  let stopMockStream;

  const switchToMockStream = () => {
    if (isClosed || stopMockStream) {
      return;
    }

    stopMockStream = startMockAlertStream({ onMessage, onStatusChange });
  };

  const connect = () => {
    if (isClosed || stopMockStream) {
      return;
    }

    onStatusChange?.("connecting");

    socket = new WebSocket(buildWsUrl("/api/v1/ws/alerts"));

    socket.onopen = () => {
      onStatusChange?.("connected");
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const alerts = Array.isArray(payload) ? payload : [payload];
        alerts.map(normalizeAlert).forEach((alert) => onMessage?.(alert));
      } catch (error) {
        onError?.(error);
      }
    };

    socket.onerror = () => {
      const error = new Error("Alert stream connection error");
      if (isDevelopmentMockFallbackEnabled()) {
        preferMockData = true;
        switchToMockStream();
        return;
      }
      onError?.(error);
    };

    socket.onclose = () => {
      if (stopMockStream) {
        return;
      }

      onStatusChange?.("reconnecting");
      if (!isClosed) {
        reconnectTimer = window.setTimeout(connect, SOCKET_RECONNECT_DELAY_MS);
      }
    };
  };

  connect();

  return () => {
    isClosed = true;
    window.clearTimeout(reconnectTimer);
    stopMockStream?.();
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close();
    }
    if (!stopMockStream) {
      onStatusChange?.("disconnected");
    }
  };
}

export function getMockBootstrap() {
  return {
    stats: mockStats,
    model: mockModelStatus,
    alerts: sortAlerts(mockAlerts),
  };
}

export { MAX_ALERTS };
