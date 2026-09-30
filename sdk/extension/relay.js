// Bridge between the SDK in the page and the extension's background worker. The page's Content
// Security Policy may forbid calls to NeuroSOC; the background worker is not bound by it.
window.addEventListener("message", (event) => {
  const data = event.data;
  if (event.source !== window || !data || typeof data.__neurosoc_request !== "string") return;
  if (typeof data.path !== "string" || !data.path.startsWith("/api/v1/sdk/")) return;
  chrome.runtime.sendMessage({ path: data.path, body: typeof data.body === "string" ? data.body : undefined }, (reply) => {
    const failed = chrome.runtime.lastError || !reply;
    window.postMessage({
      __neurosoc_reply: data.__neurosoc_request,
      ok: !failed && reply.ok,
      body: failed ? undefined : reply.body,
      error: failed ? String(chrome.runtime.lastError?.message || "no reply") : reply.error,
    }, window.location.origin);
  });
});
