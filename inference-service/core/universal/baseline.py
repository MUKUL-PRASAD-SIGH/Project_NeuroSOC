"""Running per-feature baselines (Welford mean/variance) for entities and entity groups."""

from __future__ import annotations

import math
from typing import Any

# A standard deviation floor per feature, so a perfectly regular history does not turn the first
# small wobble into an enormous z-score.
STD_FLOOR = {
    "event_rate_1m": 1.0,
    "inter_event_cv": 0.15,
    "failure_rate": 0.1,
    "sequence_surprise": 0.15,
    "unique_resources_1h": 1.0,
    "fan_out_1h": 1.0,
    "value_amount": 1.0,
}
BASELINE_FEATURES = tuple(STD_FLOOR)
MIN_HISTORY = 20  # events before an entity's own baseline replaces its group's


def empty() -> dict[str, Any]:
    return {"n": 0, "mean": {}, "m2": {}}


def update(state: dict[str, Any], features: dict[str, float]) -> dict[str, Any]:
    state["n"] = int(state.get("n", 0)) + 1
    n = state["n"]
    for name in BASELINE_FEATURES:
        if name not in features:
            continue
        x = float(features[name])
        mean = float(state["mean"].get(name, 0.0))
        delta = x - mean
        mean += delta / n
        state["mean"][name] = mean
        state["m2"][name] = float(state["m2"].get(name, 0.0)) + delta * (x - mean)
    return state


def zscores(state: dict[str, Any], features: dict[str, float]) -> dict[str, float]:
    n = int(state.get("n", 0))
    if n < 2:
        return {}
    scores: dict[str, float] = {}
    for name in BASELINE_FEATURES:
        if name not in features or name not in state["mean"]:
            continue
        variance = float(state["m2"].get(name, 0.0)) / (n - 1)
        std = max(math.sqrt(max(variance, 0.0)), STD_FLOOR[name])
        scores[name] = (float(features[name]) - float(state["mean"][name])) / std
    return scores


def choose(entity_state: dict[str, Any], group_state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Use the entity's own baseline once it has enough history, else its group's."""
    if int(entity_state.get("n", 0)) >= MIN_HISTORY:
        return entity_state, "entity"
    return group_state, "group"
