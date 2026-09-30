"""The fixed action vocabulary, loaded from ``schemas/taxonomy.json``."""

from __future__ import annotations

import json
from pathlib import Path

_TAXONOMY_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "schemas" / "taxonomy.json",
    Path("/schemas/taxonomy.json"),
    Path(__file__).resolve().parent / "taxonomy.json",
)


def _load() -> dict:
    for candidate in _TAXONOMY_CANDIDATES:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise RuntimeError("schemas/taxonomy.json was not found; the universal engine cannot start without it.")


TAXONOMY = _load()
ACTIONS: frozenset[str] = frozenset(a for group in TAXONOMY["categories"].values() for a in group)
ENTITY_TYPES: frozenset[str] = frozenset(TAXONOMY["entity_types"])
RESULTS: frozenset[str] = frozenset(TAXONOMY["results"])
SENSITIVITIES: tuple[str, ...] = tuple(TAXONOMY["sensitivities"])
INSTRUCTION_SOURCES: frozenset[str] = frozenset(TAXONOMY["instruction_sources"])

VALUE_ACTIONS = frozenset(TAXONOMY["categories"]["value"])
ENGAGEMENT_ACTIONS = frozenset(TAXONOMY["categories"]["engagement"])
# Actions a human performs through a form; a claim with no input activity behind it is suspect.
INTERACTIVE_ACTIONS = frozenset({"task.complete", "reward.claim", "form.submit", "account.create", "campaign.join"})


def sensitivity_rank(value: str | None) -> int:
    try:
        return SENSITIVITIES.index(value or "low")
    except ValueError:
        return 0
