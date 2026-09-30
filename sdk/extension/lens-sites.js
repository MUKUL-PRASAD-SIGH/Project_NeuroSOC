// Which sites the Lens runs on, and the NeuroSOC publishable key for each (see sdk/sites.local.json).
// Loaded in the page (to configure the SDK) and in the background worker (to pick the key).
// To add a site: add its host here and to "matches" in manifest.json, and register it in NeuroSOC
// with "chrome-extension://*" among its allowed origins and mode "observe".
globalThis.NEUROSOC_LENS = {
  endpoint: "http://localhost:8000",
  sites: {
    "cyreneai.com": "pk_local_cyreneai_observe",
    "www.cyreneai.com": "pk_local_cyreneai_observe",
    "app.cyreneai.com": "pk_local_cyreneai_observe",
    "localhost:3001": "pk_local_novatrust_observe",
    "localhost:5174": "pk_local_novatrust_observe"
  }
};

if (typeof window !== "undefined" && window.location) {
  const key = globalThis.NEUROSOC_LENS.sites[window.location.host];
  if (key) window.__NEUROSOC_CONFIG__ = { key, endpoint: globalThis.NEUROSOC_LENS.endpoint, relay: true };
}
