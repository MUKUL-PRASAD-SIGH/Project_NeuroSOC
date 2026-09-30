"""The one slot where learned sequence models plug into the universal engine.

A scorer receives an entity's recent event sequence plus the features of the current event and
returns two numbers in 0..1:

    spike  - a sudden burst that breaks the entity's rhythm (the SNN's job)
    drift  - a gradual departure from the entity's usual trajectory (the LNN's job)

Until the trained SNN/LNN are available, ``ZScoreScorer`` derives both from baseline z-scores, so
the engine produces real scores from day one. To plug in a trained model, point the
``UNIVERSAL_SCORER`` environment variable at a factory, e.g.
``UNIVERSAL_SCORER=core.universal.snn_lnn_scorer:build``; the factory returns an object with a
``name`` attribute and a ``score(sequence, features, z)`` method. Nothing else changes.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Scorer(Protocol):
    name: str

    def score(self, sequence: list[dict[str, Any]], features: dict[str, float], z: dict[str, float]) -> dict[str, float]:
        ...


def _clip(value: float) -> float:
    return float(min(max(value, 0.0), 1.0))


class ZScoreScorer:
    name = "zscore-baseline"

    def score(self, sequence: list[dict[str, Any]], features: dict[str, float], z: dict[str, float]) -> dict[str, float]:
        spike = _clip((max(z.get("event_rate_1m", 0.0), 0.0) - 2.0) / 4.0)
        others = [abs(v) for k, v in z.items() if k != "event_rate_1m"]
        drift = _clip((sum(others) / len(others) - 1.0) / 3.0) if others else 0.0
        drift = max(drift, _clip((features.get("sequence_surprise", 0.0) - 0.8) / 0.2) * 0.5)
        return {"spike": spike, "drift": drift}


def load_scorer() -> Scorer:
    target = os.getenv("UNIVERSAL_SCORER", "").strip()
    if not target:
        return ZScoreScorer()
    module_name, _, factory_name = target.partition(":")
    try:
        factory = getattr(importlib.import_module(module_name), factory_name or "build")
        scorer = factory()
        log.info("Universal engine using scorer %s", getattr(scorer, "name", target))
        return scorer
    except Exception as exc:  # a broken model must not take the engine down
        log.error("Could not load UNIVERSAL_SCORER=%s (%s); falling back to z-score baseline.", target, exc)
        return ZScoreScorer()
