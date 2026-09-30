"""Domain-agnostic behavioral features computed per entity.

Each entity (a person, an agent, a wallet, a service) keeps a compact state document: its
recent events, what it has seen before (devices, resources, destinations, actions), its action
transitions and its hours of activity. ``compute`` turns one incoming event plus that state into
a flat dict of numbers; ``remember`` folds the event back into the state afterwards.
None of the features mention a domain, so a bank login and an agent tool call are scored alike.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any

from .taxonomy import sensitivity_rank

RECENT_EVENTS = 200
SEEN_LIMIT = 200
SESSION_LIMIT = 50
SEQUENCE_WINDOW = 20
MIN_HOURS_HISTORY = 20


def empty_state() -> dict[str, Any]:
    return {
        "first_seen": None,
        "events": [],        # [ts, action, result, resource_id]
        "seen": {"device": [], "ip": [], "resource": [], "action": [], "destination": []},
        "last": {"device": None, "geo": None},
        "sessions": {},      # session_id -> start ts
        "transitions": {},   # "prev>next" -> count
        "hours": [0] * 24,
        "max_sensitivity": 0,
    }


def _intervals(timestamps: list[float]) -> list[float]:
    return [b - a for a, b in zip(timestamps, timestamps[1:]) if b >= a]


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, math.sqrt(variance)


def _entropy(items: list[str]) -> float:
    if len(items) < 2:
        return 0.0
    counts = Counter(items)
    total = len(items)
    entropy = -sum((c / total) * math.log(c / total) for c in counts.values())
    max_entropy = math.log(min(len(counts), total)) if len(counts) > 1 else 1.0
    return entropy / max_entropy if max_entropy > 0 else 0.0


def transition_surprise(transitions: dict[str, int], previous: str | None, action: str) -> float:
    """1 - P(action | previous action), from the counts seen so far; 0.5 when unknown."""
    if previous is None:
        return 0.5
    outgoing = {k: v for k, v in transitions.items() if k.startswith(previous + ">")}
    total = sum(outgoing.values())
    if total == 0:
        return 0.5
    return 1.0 - outgoing.get(f"{previous}>{action}", 0) / total


def compute(state: dict[str, Any], event: dict[str, Any], group_transitions: dict[str, int]) -> dict[str, float]:
    now = float(event["timestamp"])
    action = event["action"]
    context = event.get("context") or {}
    value = event.get("value") or {}
    resource = event["resource"]
    history = state["events"]
    has_history = bool(history)

    timestamps = [e[0] for e in history[-SEQUENCE_WINDOW:]] + [now]
    intervals = _intervals(timestamps)
    mean_gap, std_gap = _mean_std(intervals)
    recent = history[-SEQUENCE_WINDOW:]
    recent_actions = [e[1] for e in recent] + [action]
    recent_results = [e[2] for e in recent] + [event["result"]]

    last_hour = [e for e in history if now - e[0] <= 3600]
    seen = state["seen"]
    previous_action = history[-1][1] if has_history else None
    transitions = state["transitions"] if sum(state["transitions"].values()) >= SEQUENCE_WINDOW else group_transitions

    session_start = state["sessions"].get(event["session_id"])
    time_in_session = (now - session_start) if session_start is not None else 0.0

    destination = value.get("destination")
    destinations_1h = {e[3] for e in last_hour if e[1] in {"token.transfer", "agent.tool_call"}}
    if destination:
        destinations_1h.add(destination)

    hours = state["hours"]
    hour = time.gmtime(now).tm_hour
    total_hours = sum(hours)
    off_hours = 1.0 if total_hours >= MIN_HOURS_HISTORY and hours[hour] / total_hours < 0.05 else 0.0

    device = context.get("device_hash")
    geo = context.get("geo")

    def novel(kind: str, item: str | None) -> float:
        return 1.0 if has_history and item and item not in seen[kind] else 0.0

    return {
        "event_rate_1m": float(sum(1 for e in history if now - e[0] <= 60) + 1),
        "event_rate_1h": float(len(last_hour) + 1),
        "burstiness": (std_gap - mean_gap) / (std_gap + mean_gap) if (std_gap + mean_gap) > 0 else 0.0,
        "inter_event_cv": std_gap / mean_gap if mean_gap > 0 else 0.0,
        "mean_gap_seconds": mean_gap,
        "time_in_session": time_in_session,
        "entity_age_hours": (now - state["first_seen"]) / 3600.0 if state["first_seen"] else 0.0,
        "new_device": novel("device", device),
        "new_ip": novel("ip", context.get("ip_hash")),
        "new_resource": novel("resource", resource["id"]),
        "new_action": novel("action", action),
        "new_destination": novel("destination", destination),
        "failure_rate": sum(1 for r in recent_results if r != "success") / len(recent_results),
        "action_entropy": _entropy(recent_actions),
        "sequence_surprise": transition_surprise(transitions, previous_action, action),
        "unique_resources_1h": float(len({e[3] for e in last_hour} | {resource["id"]})),
        "fan_out_1h": float(len(destinations_1h)),
        "privilege_delta": float(max(sensitivity_rank(resource.get("sensitivity")) - state["max_sensitivity"], 0))
        if has_history else 0.0,
        "value_amount": float(value.get("amount") or 0.0),
        "off_hours": off_hours,
        "geo_change": 1.0 if has_history and geo and state["last"]["geo"] and geo != state["last"]["geo"] else 0.0,
        "device_change": 1.0 if has_history and device and state["last"]["device"] and device != state["last"]["device"] else 0.0,
        "cold_start": 0.0 if has_history else 1.0,
    }


def _remember_seen(seen: list[str], item: str | None) -> None:
    if item and item not in seen:
        seen.append(item)
        del seen[:-SEEN_LIMIT]


def remember(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    now = float(event["timestamp"])
    context = event.get("context") or {}
    value = event.get("value") or {}
    action = event["action"]
    if state["first_seen"] is None:
        state["first_seen"] = now
    if state["events"]:
        key = f"{state['events'][-1][1]}>{action}"
        state["transitions"][key] = state["transitions"].get(key, 0) + 1
    target = value.get("destination") or event["resource"]["id"]
    state["events"].append([now, action, event["result"], target])
    del state["events"][:-RECENT_EVENTS]

    seen = state["seen"]
    _remember_seen(seen["device"], context.get("device_hash"))
    _remember_seen(seen["ip"], context.get("ip_hash"))
    _remember_seen(seen["resource"], event["resource"]["id"])
    _remember_seen(seen["action"], action)
    _remember_seen(seen["destination"], value.get("destination"))
    state["last"] = {"device": context.get("device_hash") or state["last"]["device"],
                     "geo": context.get("geo") or state["last"]["geo"]}

    sessions = state["sessions"]
    if event["session_id"] not in sessions:
        sessions[event["session_id"]] = now
        while len(sessions) > SESSION_LIMIT:
            sessions.pop(next(iter(sessions)))
    state["hours"][time.gmtime(now).tm_hour] += 1
    state["max_sensitivity"] = max(state["max_sensitivity"], sensitivity_rank(event["resource"].get("sensitivity")))
    return state


def remember_transition(group_transitions: dict[str, int], previous: str | None, action: str) -> dict[str, int]:
    if previous is not None:
        key = f"{previous}>{action}"
        group_transitions[key] = group_transitions.get(key, 0) + 1
    return group_transitions
