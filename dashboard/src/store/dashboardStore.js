import { create } from "zustand";
import {
  getAlerts,
  getModelCandidates,
  getModelVersion,
  getStats,
  MAX_ALERTS,
  promoteModelCandidate,
  rejectModelCandidate,
  rollbackModel,
  subscribeToAlerts,
} from "../services/dashboardApi";
import { loadCurrentUser, rolesFromUser, signIn as oidcSignIn, signOut as oidcSignOut } from "../lib/auth";

const initialStats = {
  totalTransactions: 0,
  hackerDetections: 0,
  avgRiskScore: 0,
  liveAlerts: 0,
};

const initialModel = {
  versions: [],
  validationF1: [],
  lastRetrainedAt: null,
};

function deriveThreatEvents(alerts) {
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;

  return alerts
    .filter((alert) => alert.verdict === "HACKER" && new Date(alert.timestamp).getTime() >= cutoff)
    .map((alert) => ({
      id: alert.id,
      timestamp: alert.timestamp,
      sourceIp: alert.sourceIp,
      score: alert.score,
      userId: alert.userId,
      userName: alert.userName,
      locationLabel: alert.locationLabel,
      message: alert.message,
    }));
}

function insertAlert(alert, alerts) {
  const deduped = [alert, ...alerts.filter((item) => item.id !== alert.id)];
  return deduped
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, MAX_ALERTS);
}

export const useDashboardStore = create((set, get) => ({
  stats: {
    data: initialStats,
    loading: false,
    error: null,
    lastUpdated: null,
  },
  modelStatus: {
    data: initialModel,
    loading: false,
    error: null,
    lastUpdated: null,
  },
  alerts: {
    items: [],
    status: "idle",
    loading: false,
    error: null,
    lastUpdated: null,
  },
  modelCandidates: {
    items: [],
    loading: false,
    error: null,
    lastUpdated: null,
  },
  threatMap: {
    items: [],
    lastUpdated: null,
  },
  modal: {
    selectedAlert: null,
    open: false,
  },
  alertStreamCleanup: null,
  auth: {
    user: null,
    roles: [],
    isAuthenticated: false,
    checked: false,
  },

  refreshAuth: async () => {
    const user = await loadCurrentUser();
    set({
      auth: {
        user,
        roles: rolesFromUser(user),
        isAuthenticated: Boolean(user && !user.expired),
        checked: true,
      },
    });
    return user;
  },

  signIn: async () => {
    await oidcSignIn();
  },

  signOut: async () => {
    await oidcSignOut();
  },

  fetchStats: async () => {
    set((state) => ({
      stats: {
        ...state.stats,
        loading: true,
        error: null,
      },
    }));

    try {
      const data = await getStats();
      set((state) => ({
        stats: {
          ...state.stats,
          data: {
            ...initialStats,
            ...data,
          },
          loading: false,
          error: null,
          lastUpdated: Date.now(),
        },
      }));
    } catch (error) {
      set((state) => ({
        stats: {
          ...state.stats,
          loading: false,
          error: error.message,
        },
      }));
    }
  },

  fetchModelStatus: async () => {
    set((state) => ({
      modelStatus: {
        ...state.modelStatus,
        loading: true,
        error: null,
      },
    }));

    try {
      const data = await getModelVersion();
      set((state) => ({
        modelStatus: {
          ...state.modelStatus,
          data: {
            ...initialModel,
            ...data,
          },
          loading: false,
          error: null,
          lastUpdated: Date.now(),
        },
      }));
    } catch (error) {
      set((state) => ({
        modelStatus: {
          ...state.modelStatus,
          loading: false,
          error: error.message,
        },
      }));
    }
  },

  fetchModelCandidates: async () => {
    set((state) => ({ modelCandidates: { ...state.modelCandidates, loading: true, error: null } }));
    try {
      const items = await getModelCandidates();
      set((state) => ({
        modelCandidates: { ...state.modelCandidates, items, loading: false, error: null, lastUpdated: Date.now() },
      }));
    } catch (error) {
      set((state) => ({ modelCandidates: { ...state.modelCandidates, loading: false, error: error.message } }));
    }
  },

  promoteCandidate: async (candidateId) => {
    await promoteModelCandidate(candidateId);
    await Promise.all([get().fetchModelCandidates(), get().fetchModelStatus()]);
  },

  rejectCandidate: async (candidateId) => {
    await rejectModelCandidate(candidateId);
    await get().fetchModelCandidates();
  },

  rollbackActiveModel: async () => {
    await rollbackModel();
    await Promise.all([get().fetchModelCandidates(), get().fetchModelStatus()]);
  },

  hydrateAlerts: async () => {
    set((state) => ({
      alerts: {
        ...state.alerts,
        loading: true,
        error: null,
      },
    }));

    try {
      const items = await getAlerts();
      set((state) => ({
        alerts: {
          ...state.alerts,
          items,
          loading: false,
          error: null,
          lastUpdated: Date.now(),
        },
        threatMap: {
          items: deriveThreatEvents(items),
          lastUpdated: Date.now(),
        },
      }));
    } catch (error) {
      set((state) => ({
        alerts: {
          ...state.alerts,
          loading: false,
          error: error.message,
        },
      }));
    }
  },

  startAlertStream: () => {
    const existingCleanup = get().alertStreamCleanup;
    if (existingCleanup) {
      return existingCleanup;
    }

    const cleanup = subscribeToAlerts({
      onStatusChange: (status) => {
        set((state) => ({
          alerts: {
            ...state.alerts,
            status,
          },
        }));
      },
      onMessage: (alert) => {
        set((state) => {
          const items = insertAlert(alert, state.alerts.items);
          return {
            alerts: {
              ...state.alerts,
              items,
              loading: false,
              error: null,
              status: "connected",
              lastUpdated: Date.now(),
            },
            threatMap: {
              items: deriveThreatEvents(items),
              lastUpdated: Date.now(),
            },
          };
        });
      },
      onError: (error) => {
        set((state) => ({
          alerts: {
            ...state.alerts,
            error: error.message,
          },
        }));
      },
    });

    set({ alertStreamCleanup: cleanup });
    return cleanup;
  },

  stopAlertStream: () => {
    const cleanup = get().alertStreamCleanup;
    if (cleanup) {
      cleanup();
    }
    set({ alertStreamCleanup: null });
  },

  applyAlertDecision: (sessionId, patch) => {
    set((state) => ({
      alerts: {
        ...state.alerts,
        items: state.alerts.items.map((item) =>
          item.id === sessionId ? { ...item, ...patch } : item
        ),
      },
      modal:
        state.modal.selectedAlert?.id === sessionId
          ? { ...state.modal, selectedAlert: { ...state.modal.selectedAlert, ...patch } }
          : state.modal,
    }));
  },

  openUserModal: (alert) => {
    set({
      modal: {
        selectedAlert: alert,
        open: Boolean(alert),
      },
    });
  },

  closeUserModal: () => {
    set({
      modal: {
        selectedAlert: null,
        open: false,
      },
    });
  },
}));
