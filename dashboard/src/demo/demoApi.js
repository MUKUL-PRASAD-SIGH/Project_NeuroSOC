import axios from "axios";
import { getDemoSession } from "./session";

// The demo talks to its own backend through same-origin paths: the Vite dev server (or the dashboard's nginx)
// proxies /api to the NeuroSOC API, so there is no CORS to configure and no API address to get wrong.
const client = axios.create({ baseURL: "", timeout: 30000, headers: { "Content-Type": "application/json" } });
client.interceptors.request.use((config) => {
  config.headers = config.headers || {};
  config.headers["X-Demo-Session"] = getDemoSession();
  return config;
});

const PREFIX = "/api/v1/demo";
const data = (promise) => promise.then((response) => response.data);

export function describeError(err, fallback = "Something went wrong.") {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (!err?.response) return "The NovaTrust service is not reachable.";
  return fallback;
}

export const fetchDemoConfig = () => data(client.get(`${PREFIX}/config`));
export const connectDemo = (secretKey) => data(client.post(`${PREFIX}/connect`, { secret_key: secretKey }));
export const fetchAccount = () => data(client.get(`${PREFIX}/account`));
export const resetDemo = () => data(client.post(`${PREFIX}/account/reset`));
export const chatWithNova = (message, content) => data(client.post(`${PREFIX}/agent/chat`, { message, ...(content ? { content } : {}) }));
export const sendTransfer = (to, amount, purpose) => data(client.post(`${PREFIX}/transfer`, { to, amount, purpose }));
export const confirmTransfer = (id) => data(client.post(`${PREFIX}/transfer/${encodeURIComponent(id)}/confirm`));
export const cancelTransfer = (id) => data(client.post(`${PREFIX}/transfer/${encodeURIComponent(id)}/cancel`));
export const runSimulation = (type) => data(client.post(`${PREFIX}/simulate`, { type }));
