# neurosoc

Python SDK for [NeuroSOC](https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC): check browser session verdicts from your backend and guard AI agent tool calls before they run. Standard library only, Python 3.9+.

```bash
pip install neurosoc
```

## Backend: never trust the browser

The NeuroSOC browser script adds a hidden `neurosoc_session` field to every form. Check it on your server before you pay, mint or execute anything:

```python
from neurosoc import NeuroSOC

soc = NeuroSOC(endpoint="https://your-neurosoc-host", secret_key="sk_live_...")

verdict = soc.session_verdict(request.form["neurosoc_session"])
if verdict.action in ("shadow", "step_up"):
    hold_reward()        # shadowed accounts see "pending review"; nothing is paid
```

## AI agents: guard every tool

```python
from neurosoc import NeuroSOC, ActionBlocked

soc = NeuroSOC(endpoint="https://your-neurosoc-host", secret_key="sk_live_...")

@soc.guard_tool(agent_id="flows-agent-1", action="token.transfer", resource="treasury", sensitivity="critical")
def transfer(to: str, amount: float, instruction_source: str = "owner"):
    ...
```

Each call is scored before the body runs. A transfer to a never-used destination, far above the agent's usual amount, right after an instruction from outside content (the prompt-injection pattern) raises `ActionBlocked`. The check runs outside the model, so no prompt can argue past it. If NeuroSOC is unreachable, guarded tools fail closed unless you pass `fail_open=True`.

## Events and guards

```python
soc.track(entity_id="user_42", action="reward.claim", resource_id="campaign_7")   # record an action from a backend
verdict = soc.guard(entity_id="user_42", action="reward.claim", resource_id="campaign_7")
if not verdict.allowed:
    ...
```

`Verdict` carries `verdict`, `action` (`allow`, `step_up`, `shadow`, ...), `risk`, `reasons`, `verdict_id` and `session_id`. Network failures and refused requests raise `NeuroSOCError`.

Use a secret key (`sk_...`) here, never in a browser. See the [full SDK docs](https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/tree/main/sdk) for the browser script, rules and webhooks.
