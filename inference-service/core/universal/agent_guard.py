"""Detector 3: an AI agent acting outside its own normal behavior.

Aimed at the prompt-injection pattern behind incidents like the May 2026 Grok/Bankr wallet drain:
an instruction hidden in outside content makes an agent move value somewhere it has never sent
anything, in an amount far above its usual. The check runs before the tool executes and outside
the language model, so no prompt can argue its way past it.
"""

from __future__ import annotations

from typing import Any

from .taxonomy import VALUE_ACTIONS

VALUE_Z_THRESHOLD = 3.0
BURST_RATE_Z = 3.0

# Policy checks against the site's agent registry (see sites.normalize_agents). Any single failure is
# enough to pause the agent: a tool or resource the owner never approved is not a gray area.
AUTHORIZATION_RISK = 0.7
SENSITIVE_WINDOW_SECONDS = 60
DEFAULT_MAX_SENSITIVE_PER_MINUTE = 10
# Actions whose target resource must be on the agent's authorized list (plus its own sensitive actions).
RESOURCE_CHECKED_ACTIONS = VALUE_ACTIONS | {"agent.tool_call", "permission.change", "api_key.create", "agent.config_change"}


def spec_for(policy: list[dict[str, Any]] | None, agent_id: str) -> dict[str, Any] | None:
    return next((agent for agent in policy or [] if agent.get("agent_id") == agent_id), None)


def counts_as_sensitive(event: dict[str, Any], spec: dict[str, Any] | None) -> bool:
    """Whether an agent event is a sensitive action for the rate window."""
    if event["entity"]["type"] != "agent":
        return False
    return event["action"] in VALUE_ACTIONS or event["action"] in (spec or {}).get("sensitive_actions", [])


def authorization(event: dict[str, Any], policy: list[dict[str, Any]] | None) -> tuple[float, list[str]]:
    """Judge an agent event against the site's registry. No registry means no policy (0, [])."""
    if not policy or event["entity"]["type"] != "agent":
        return 0.0, []
    agent_id = event["entity"]["id"]
    spec = spec_for(policy, agent_id)
    if spec is None:
        return AUTHORIZATION_RISK, [f"agent {agent_id} is not registered for this application"]
    reasons: list[str] = []
    tool = (event.get("agent") or {}).get("tool")
    if tool and spec.get("tools") and tool not in spec["tools"]:
        reasons.append(f"tool {tool} is not permitted for agent {agent_id}")
    resource = event["resource"]["id"]
    checked = event["action"] in RESOURCE_CHECKED_ACTIONS or event["action"] in spec.get("sensitive_actions", [])
    if checked and spec.get("authorized_resources") and resource not in spec["authorized_resources"]:
        reasons.append(f"agent {agent_id} is not authorized to act on resource {resource}")
    return (AUTHORIZATION_RISK, reasons) if reasons else (0.0, [])


def evaluate(event: dict[str, Any], features: dict[str, float], z: dict[str, float],
             policy: list[dict[str, Any]] | None = None,
             sensitive_rate: int | None = None) -> tuple[float, list[str]]:
    """Return (risk 0..1, reasons). Only agents and value-moving actions are judged here.

    ``policy`` is the site's agent registry and ``sensitive_rate`` the number of sensitive actions this
    agent performed in the last minute (including this one); both are optional, and without them this is
    the original anomaly-only check.
    """
    entity_type = event["entity"]["type"]
    action = event["action"]
    auth_risk, auth_reasons = authorization(event, policy)
    spec = spec_for(policy, event["entity"]["id"]) if policy else None
    if sensitive_rate is not None and spec is not None:
        limit = int(spec.get("max_sensitive_per_minute", DEFAULT_MAX_SENSITIVE_PER_MINUTE))
        if sensitive_rate > limit:
            auth_risk = AUTHORIZATION_RISK
            auth_reasons.append(f"{sensitive_rate} sensitive actions in {SENSITIVE_WINDOW_SECONDS}s; "
                                f"this agent is limited to {limit}")
    if auth_risk:
        base_risk, base_reasons = _anomaly(event, features, z, entity_type, action)
        return min(auth_risk + base_risk, 1.0), auth_reasons + base_reasons
    return _anomaly(event, features, z, entity_type, action)


def _anomaly(event: dict[str, Any], features: dict[str, float], z: dict[str, float],
             entity_type: str, action: str) -> tuple[float, list[str]]:
    moves_value = action in VALUE_ACTIONS or (action == "agent.tool_call" and (event.get("value") or {}).get("amount"))
    if entity_type != "agent" and not moves_value:
        return 0.0, []

    risk = 0.0
    reasons: list[str] = []
    agent = event.get("agent") or {}
    value = event.get("value") or {}

    if moves_value and features.get("new_destination"):
        risk += 0.35
        reasons.append(f"sends value to a destination never used before ({value.get('destination')})")
    value_z = z.get("value_amount", 0.0)
    if moves_value and value_z >= VALUE_Z_THRESHOLD:
        risk += 0.35
        size = "far above" if value_z > 50 else f"{value_z:.0f} standard deviations above"
        reasons.append(f"amount {float(value.get('amount') or 0):,.2f} is {size} its usual")
    if moves_value and agent.get("instruction_source") == "external_content":
        risk += 0.3
        reasons.append("the instruction came from outside content, not the agent's owner")
    if z.get("event_rate_1m", 0.0) >= BURST_RATE_Z:
        risk += 0.15
        reasons.append("tool calls are much faster than this agent's normal pace")
    if features.get("new_action") and entity_type == "agent":
        risk += 0.1
        reasons.append(f"first time this agent has performed {action}")
    return min(risk, 1.0), reasons
