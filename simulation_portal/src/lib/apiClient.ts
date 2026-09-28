const DEFAULT_API_BASE_URL = 'http://localhost:8000';

const API_BASE_URL = (import.meta.env.VITE_API_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '');
const API_REQUEST_TIMEOUT_MS = 15000;

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_REQUEST_TIMEOUT_MS);
  const relayAbort = () => controller.abort(init?.signal?.reason);
  if (init?.signal?.aborted) {
    relayAbort();
  } else {
    init?.signal?.addEventListener('abort', relayAbort, { once: true });
  }

  try {
    const response = await fetch(buildApiUrl(path), {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
      },
    });

    if (!response.ok) {
      throw new Error(`Request failed (${response.status}) for ${path}`);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (timedOut) {
      throw new Error('API request timed out.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    init?.signal?.removeEventListener('abort', relayAbort);
  }
}
