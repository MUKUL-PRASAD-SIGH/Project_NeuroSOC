importScripts("lens-sites.js");

// Forward SDK requests to NeuroSOC with the key registered for the tab's site.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  let host = "";
  try { host = new URL(sender.tab?.url || "").host; } catch { /* no tab */ }
  const key = globalThis.NEUROSOC_LENS.sites[host];
  if (!key || typeof message?.path !== "string" || !message.path.startsWith("/api/v1/sdk/")) {
    sendResponse({ ok: false, error: "site not enabled in NeuroSOC Lens" });
    return false;
  }
  const url = `${globalThis.NEUROSOC_LENS.endpoint}${message.path}?key=${encodeURIComponent(key)}`;
  const init = message.body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "text/plain;charset=UTF-8" }, body: message.body,
  };
  fetch(url, init)
    .then(async (response) => sendResponse({ ok: response.ok, body: await response.json().catch(() => null),
      error: response.ok ? undefined : `HTTP ${response.status}` }))
    .catch((error) => sendResponse({ ok: false, error: String(error) }));
  return true; // answer asynchronously
});
