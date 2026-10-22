# @neurosoc/sdk

Browser SDK for [NeuroSOC](https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC): tells people from bots and bot farms on any website and reports to your NeuroSOC engine. It measures typing and mouse timing, never content. About 7 KB gzipped, no dependencies.

## Script tag

```html
<script src="https://cdn.jsdelivr.net/npm/@neurosoc/sdk/dist/neurosoc.min.js"
        data-key="pk_live_..." data-endpoint="https://your-neurosoc-host" async></script>
```

That is the whole install. The script starts a session, records page views (including single-page-app route changes) and form submits, listens for Solana and EVM wallet connections, and maps clicks to actions using the site's rules, which are fetched from the server. The client is available as `window.neurosoc`.

Tag options: `data-consent="wait"` starts with capture off until `neurosoc.consent(true)`; `data-debug="true"` logs delivery problems to the console; `data-auto-capture="false"`, `data-capture-behavior="false"` and `data-tag-forms="false"` switch those features off.

The script is loaded `async`, so code on your page that needs the client should wait for it: `window.neurosoc` exists once the `neurosoc:ready` event has fired on `window`.

```js
const whenSdk = (fn) => window.neurosoc ? fn(window.neurosoc) : addEventListener("neurosoc:ready", () => fn(window.neurosoc), { once: true });
whenSdk((soc) => soc.consent(true));   // e.g. a cookie banner remembering an earlier choice
```

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
soc.consent(false);                                 // wire to your cookie banner: stops capture and clears what the SDK stored
soc.reset();                                        // on sign-out: anonymous entity, fresh session
soc.destroy();                                      // when a single-page app unmounts: removes every listener
```

`NeuroSOC.init` returns the running client if called twice, and returns an inert client on the server, so it is safe in React/Next.js components that render under SSR. `require("@neurosoc/sdk")` works as well as `import`.

## Delivery

Events are batched (2 s, or 20 events) and sent as CORS "simple requests" with the publishable key in the URL, so there is no preflight. Each request times out after 8 s (`timeoutMs`). Network errors, timeouts, 429 and 5xx are retried with backoff and re-sent when the browser comes back online; the server de-duplicates by event id. A rejected key or origin (401/403) warns once in the console and stops the SDK from retrying. One invalid event in a batch is isolated and dropped without losing the others. `guard()` never throws and never waits longer than the timeout: it resolves `null` when no verdict could be obtained, so decide on the server what that means.

## Forms

The SDK writes the session id into **same-origin `POST` forms** only (as a hidden `neurosoc_session` field, and into `FormData` for `fetch(new FormData(form))`). `GET` forms and forms that post to another origin never receive it, so the id cannot leak into URLs or to third parties.

## Wallets

The SDK listens to the events wallets already emit (Phantom/Solana `connect`, EVM `accountsChanged`, EIP-6963 announcements) and reads `eth_accounts`, which never opens a prompt, to notice a wallet the visitor connected earlier. It never calls signing or connection-request methods.

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
