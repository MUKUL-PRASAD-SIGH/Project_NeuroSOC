"""Turn feature deviations into short sentences an analyst (or a site owner) can read."""

from __future__ import annotations

FEATURE_WORDS = {
    "event_rate_1m": "activity rate",
    "inter_event_cv": "timing irregularity",
    "failure_rate": "failure rate",
    "sequence_surprise": "action order",
    "unique_resources_1h": "number of resources touched",
    "fan_out_1h": "number of destinations",
    "value_amount": "amount",
}
FLAG_WORDS = {
    "new_device": "new device for this account",
    "geo_change": "location changed since last activity",
    "off_hours": "unusual hour for this account",
    "privilege_delta": "touches a more sensitive resource than ever before",
}
MAX_REASONS = 4


def reasons(detector_reasons: list[str], features: dict[str, float], z: dict[str, float]) -> list[str]:
    out = list(detector_reasons)
    for name, score in sorted(z.items(), key=lambda item: -abs(item[1])):
        if abs(score) < 3.0 or name not in FEATURE_WORDS:
            continue
        direction = "above" if score > 0 else "below"
        out.append(f"{FEATURE_WORDS[name]} is {abs(score):.0f} standard deviations {direction} its usual")
    for name, sentence in FLAG_WORDS.items():
        if features.get(name, 0.0) > 0:
            out.append(sentence)
    deduped: list[str] = []
    for sentence in out:
        if sentence not in deduped:
            deduped.append(sentence)
    return deduped[:MAX_REASONS]
