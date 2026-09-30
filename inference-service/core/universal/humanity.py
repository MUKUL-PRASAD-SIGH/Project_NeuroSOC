"""Detector 1: how human does this session's input look?

Reuses the 20-number session vector from ``core.behavioral.signals`` (the same one the NovaTrust
portal tracker produces). The SDK sends either that vector or the raw timing events, never what
was typed. Scripts type with near-constant rhythm, move the mouse in straight lines or not at
all, and finish forms in a couple of seconds; people do none of those.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from core.behavioral.signals import SESSION_VECTOR_SIZE, extract_session_vector

from .taxonomy import INTERACTIVE_ACTIONS

# Index of each value in the session vector built by extract_session_vector.
MEAN_IKI, STD_IKI, MEAN_DWELL, STD_DWELL, MEAN_VELOCITY, STD_VELOCITY, MEAN_CURVE, STD_CURVE = range(8)
DURATION, ERROR_RATE = 10, 12

MAX_TELEMETRY_EVENTS = 2000


def session_vector(telemetry: dict[str, Any] | None) -> np.ndarray | None:
    if not telemetry:
        return None
    if telemetry.get("session_vector") is not None:
        vector = np.asarray(telemetry["session_vector"], dtype=np.float32)
        return vector if vector.shape == (SESSION_VECTOR_SIZE,) else None
    events = telemetry.get("events")
    if isinstance(events, list) and events:
        return extract_session_vector(events[:MAX_TELEMETRY_EVENTS])
    return None


def _clip(value: float) -> float:
    return float(min(max(value, 0.0), 1.0))


def score(vector: np.ndarray | None, input_event_count: int | None, action: str) -> tuple[float | None, list[str]]:
    """Return (humanity 0..1 or None when there is no telemetry, reasons for a low score)."""
    if vector is None:
        if input_event_count is not None and input_event_count < 3 and action in INTERACTIVE_ACTIONS:
            return 0.15, ["no keyboard or mouse activity before a form action"]
        return None, []

    reasons: list[str] = []
    v = [float(x) for x in vector]

    if v[MEAN_IKI] > 0:
        typing_cv = v[STD_IKI] / v[MEAN_IKI]
        typing = _clip(typing_cv / 0.3)
        if typing < 0.4:
            reasons.append(f"typing rhythm is machine-regular (variation {typing_cv:.2f}, people ~0.3+)")
    else:
        typing = 0.5

    if v[MEAN_VELOCITY] > 0:
        mouse = _clip(v[MEAN_CURVE] / 15.0) * 0.6 + _clip(v[STD_VELOCITY] / max(v[MEAN_VELOCITY], 1e-6)) * 0.4
        if mouse < 0.3:
            reasons.append("mouse moves in straight, constant-speed lines")
    else:
        mouse = 0.25
        reasons.append("no mouse movement")

    duration = v[DURATION]
    pace = 0.1 if duration < 3 else 0.5 if duration < 8 else 1.0
    if pace < 0.5:
        reasons.append(f"whole session took {duration:.1f}s")

    corrections = 1.0 if v[ERROR_RATE] > 0 else 0.6

    humanity = 0.3 * typing + 0.3 * mouse + 0.25 * pace + 0.15 * corrections
    return _clip(humanity), reasons if humanity < 0.5 else []
