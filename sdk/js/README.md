# @neurosoc/sdk

> **Status:** the npm package `@neurosoc/sdk` is not published yet, so the CDN and `npm i` instructions below work only after its first release (see [Releasing](../README.md#releasing)). Until then, use the bundle your NeuroSOC dashboard serves at `/neurosoc.min.js`, or build it here with `npm run build`.

Browser SDK for [NeuroSOC](https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC): tells people from bots and bot farms on any website and reports to your NeuroSOC engine. It measures typing and mouse timing, never content. Under 5 KB gzipped, no dependencies.

## Script tag

```html
<script src="https://cdn.jsdelivr.net/npm/@neurosoc/sdk/dist/neurosoc.min.js"
        data-key="pk_live_..." data-endpoint="https://your-neurosoc-host" async></script>
```

That is the whole install. The script starts a session, records page views (including single-page-app route changes) and form submits, listens for Solana and EVM wallet connections, and maps clicks to actions using the site's rules, which are fetched from the server. The client is available as `window.neurosoc`.

Tag options: `data-consent="wait"` starts with capture off until `neurosoc.consent(true)`; `data-debug="true"` logs to the console.

## npm

```bash
npm i @neurosoc/sdk
```

```js
import { NeuroSOC } from "@neurosoc/sdk";

const soc = NeuroSOC.init({ publishableKey: "pk_live_...", endpoint: "https://your-neurosoc-host" });

soc.identify({ id: user.id, type: "human" });       // once the user signs in
const verdict = await soc.guard({                   // wait for a verdict before continuing
  action: "reward.claim",
  resource: { id: "campaign_7", type: "campaign" },
  value: { amount: 25 },
});
if (verdict?.action === "shadow") showPendingReview();   // cosmetic: your server decides
soc.consent(false);                                 // wire to your cookie banner
```

## Decide on the server

Anything in a browser can be tampered with, so the decision to pay, mint or execute belongs on your backend. The SDK adds a hidden `neurosoc_session` field to every form; check it with your secret key (`sk_...`), for example with the Python SDK (`pip install neurosoc`):

```python
verdict = soc.session_verdict(request.form["neurosoc_session"])
if verdict.action in ("shadow", "step_up"):
    hold_reward()
```

Use only a publishable key (`pk_...`) in the browser. It can send events from the site's registered origins and read the site's rules, nothing more. The browser only learns the response to render (`allow`, `step_up`, `shadow`), never the scores or reasons.

## Privacy

- Keystrokes are reduced to a class (`char`, `space`, `backspace`, ...) in the page. Typed text, form values and page content never leave the browser.
- The device fingerprint is a hash of coarse, stable browser properties.
- `consent(false)` stops all capture.

See the [full SDK docs](https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/tree/main/sdk) for site registration, rules and webhooks.
