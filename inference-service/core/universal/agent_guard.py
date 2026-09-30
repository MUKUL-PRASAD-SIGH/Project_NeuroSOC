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


def evaluate(event: dict[str, Any], features: dict[str, float], z: dict[str, float]) -> tuple[float, list[str]]:
    """Return (risk 0..1, reasons). Only agents and value-moving actions are judged here."""
    entity_type = event["entity"]["type"]
    action = event["action"]
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
