# NeuroSOC SDK

Drop-in behavioral security for any website and any AI agent. NeuroSOC learns how each entity (a person, a wallet, an agent) normally behaves and flags what does not fit: scripted sign-ups, bot farms claiming rewards, and agents tricked into moving funds.

| Package | Where it runs | What it does |
| --- | --- | --- |
| [`js/`](js) (`@neurosoc/sdk`) | Browser, any framework | Auto-captures sessions, page views, form submits, wallet connects and rule-mapped clicks; measures typing and mouse timing (never content) |
| [`python/`](python) (`neurosoc`) | Backends, agents | Server-side verdict checks; `@guard_tool` scores every agent tool call before it runs |
| [`presets/`](presets) | NeuroSOC server | Rules files mapping a site's buttons and forms to actions (CyreneAI, generic auth, NovaTrust, the example campaign) |

The engine behind it lives in `inference-service/core/universal` and is enabled with `ENABLE_UNIVERSAL_ENGINE=true`.

## Website: one script tag

```html
<script src="https://cdn.jsdelivr.net/npm/@neurosoc/sdk/dist/neurosoc.min.js"
        data-key="pk_live_..." data-endpoint="https://your-neurosoc-host" async></script>
```

That is the whole install. The script starts a session, records page views (including single-page-app route changes) and form submits, listens for Solana and EVM wallet connections, and maps clicks to actions using the site's rules, which are fetched from the server and edited in the dashboard, so onboarding needs no redeploy.

Optional, from your own code:

```js
const soc = window.neurosoc;                        // started by the script tag
soc.identify({ id: user.id, type: "human" });       // once the user signs in
const verdict = await soc.guard({                   // wait for a verdict before continuing
  action: "reward.claim",
  resource: { id: "campaign_7", type: "campaign" },
  value: { amount: 25 },
});
if (verdict?.action === "shadow") showPendingReview();   // cosmetic: the server decides (below)
soc.consent(false);                                 // wire to your cookie banner
```

Or install from npm: `npm i @neurosoc/sdk`, then `NeuroSOC.init({ publishableKey, endpoint })`.

## Backend: never trust the browser

Anything in a browser can be tampered with, so the decision to pay, mint or execute happens on your server. The script adds a hidden `neurosoc_session` field to every form:

```python
from neurosoc import NeuroSOC

soc = NeuroSOC(endpoint="https://your-neurosoc-host", secret_key="sk_live_...")

verdict = soc.session_verdict(request.form["neurosoc_session"])
if verdict.action in ("shadow", "step_up"):
    hold_reward()        # shadowed accounts see "pending review"; nothing is paid
```

Prefer push? Register a webhook in the dashboard; verdicts arrive signed with `X-NeuroSOC-Signature: sha256=<hmac>`.

## AI agents: guard every tool

```python
from neurosoc import NeuroSOC, ActionBlocked

soc = NeuroSOC(endpoint="https://your-neurosoc-host", secret_key="sk_live_...")

@soc.guard_tool(agent_id="flows-agent-1", action="token.transfer", resource="treasury", sensitivity="critical")
def transfer(to: str, amount: float, instruction_source: str = "owner"):
    ...
```

Each call is scored before the body runs. A transfer to a never-used destination, far above the agent's usual amount, right after an instruction from outside content (the prompt-injection pattern) raises `ActionBlocked`. The check runs outside the model, so no prompt can argue past it. If NeuroSOC is unreachable, guarded tools fail closed unless you pass `fail_open=True`.

## Keys

| Key | Where | Can |
| --- | --- | --- |
| `pk_...` publishable | Browser | Send events from the site's registered origins; read the site's rules |
| `sk_...` secret | Server, agents | Everything above, plus session verdicts and synchronous guards |

A browser only ever learns the response to render (`allow`, `step_up`, `shadow`), never the scores or reasons, so a bot cannot learn what gave it away.

## Rules

```json
{ "match": { "url": "/campaign/*", "event": "click", "selector": "#claim" },
  "action": "reward.claim",
  "resource": { "type": "campaign", "id_from": "url:2", "sensitivity": "medium" },
  "value_from": "attr:data-reward" }
```

- `match.event`: `click` (default) or `submit`
- `match.url`: glob on the path, e.g. `*campaign*`
- `match.selector` (CSS), `match.text` (visible label, case-insensitive; one word or a list), `match.has` (the form contains this selector)
- `id_from` / `value_from`: `url:path`, `url:<n>` (n-th path segment), `attr:<name>` (nearest element carrying it), `const:<value>`

Actions come from the fixed list in [`schemas/taxonomy.json`](../schemas/taxonomy.json).

## Privacy

- Keystrokes are reduced to a class (`char`, `space`, `backspace`, ...) in the page. Typed text, form values and page content never leave the browser.
- The device fingerprint is a hash of coarse, stable browser properties, used to link accounts coming from one machine.
- IP addresses are hashed on the server with a per-deployment secret before storage.
- `consent(false)` stops all capture; `data-consent="wait"` on the script tag starts with capture off.

## Build and test

```bash
cd sdk/js && npm install && npm run build && npm test     # dist/neurosoc.min.js, ~4 KB gzipped
pytest tests/test_python_sdk.py tests/test_universal_*.py  # from the repo root
```
