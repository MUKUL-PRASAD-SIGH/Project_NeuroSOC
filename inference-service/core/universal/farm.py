"""Detector 2: bot farms, many accounts behaving as one.

A single careful bot can pass as human; fifty cannot hide that they are copies. Every entity that
touches a resource (a campaign, a token launch) is indexed by what it shares with others.

  strong links - one is enough to tie two accounts: the same device fingerprint, the same
                 funding wallet
  weak links   - common among unrelated people (an office or carrier IP block, similar typing
                 statistics), so two accounts are tied only when they share both

Accounts tied together form a group; a large enough group on one resource is a farm.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

from .store import get_json, set_json

FARM_MIN_SIZE = 5
TIMING_MAX_RELATIVE_DIFF = 0.02
PARTICIPANT_LIMIT = 500
INDEX_TTL = 7 * 24 * 3600
STRONG_KINDS = ("device_hash", "funded_by")
WEAK_KINDS = ("ip_prefix_hash",)
WEAK_LINKS_REQUIRED = 2


def _participants_key(tenant: str, resource_id: str) -> str:
    return f"{tenant}:res:{resource_id}:participants"


def _link_key(tenant: str, kind: str, value: str) -> str:
    return f"{tenant}:link:{kind}:{value}"


def _vector_key(tenant: str, entity_id: str) -> str:
    return f"{tenant}:vec:{entity_id}"


def record(kv: Any, tenant: str, entity_id: str, resource_id: str, context: dict[str, Any],
           vector: np.ndarray | None) -> None:
    kv.sadd(_participants_key(tenant, resource_id), entity_id)
    kv.expire(_participants_key(tenant, resource_id), INDEX_TTL)
    for kind in STRONG_KINDS + WEAK_KINDS:
        value = context.get(kind)
        if value:
            kv.sadd(_link_key(tenant, kind, value), entity_id)
            kv.expire(_link_key(tenant, kind, value), INDEX_TTL)
            kv.sadd(f"{tenant}:links:{entity_id}", f"{kind}={value}")
    kv.expire(f"{tenant}:links:{entity_id}", INDEX_TTL)
    if vector is not None:
        set_json(kv, _vector_key(tenant, entity_id), [round(float(x), 5) for x in vector], ttl=INDEX_TTL)


def near_identical(a: np.ndarray, b: np.ndarray) -> bool:
    """Input-timing statistics that match within a couple of percent on every measured dimension:
    what one script replayed across accounts produces. People with similar typing speed can agree
    on average, but not on all twenty statistics at once, so the check uses the worst dimension."""
    measured = (np.abs(a) + np.abs(b)) > 1e-6
    if int(measured.sum()) < 6:
        return False  # too little input to compare fairly
    relative = np.abs(a - b)[measured] / (np.abs(a) + np.abs(b))[measured]
    return float(relative.max()) <= TIMING_MAX_RELATIVE_DIFF


def cluster(kv: Any, tenant: str, entity_id: str, resource_id: str) -> dict[str, Any]:
    """Accounts on this resource tied to ``entity_id``, and what ties them."""
    participants = kv.smembers(_participants_key(tenant, resource_id))
    if entity_id not in participants:
        return {"size": 1, "members": [entity_id], "shared": {}}
    capped = set(sorted(participants)[:PARTICIPANT_LIMIT]) | {entity_id}

    vectors: dict[str, np.ndarray] = {}
    for member in capped:
        raw = get_json(kv, _vector_key(tenant, member))
        if raw:
            vectors[member] = np.asarray(raw, dtype=np.float64)

    shared: dict[str, set[str]] = {}
    seen = {entity_id}
    queue = deque([entity_id])
    while queue:
        current = queue.popleft()
        neighbours: set[str] = set()
        weak_counts: dict[str, int] = {}
        for link in kv.smembers(f"{tenant}:links:{current}"):
            kind, _, value = link.partition("=")
            linked = (kv.smembers(_link_key(tenant, kind, value)) & capped) - {current}
            if not linked:
                continue
            if kind in STRONG_KINDS:
                neighbours |= linked
                shared.setdefault(kind, set()).update(linked | {current})
            else:
                for other in linked:
                    weak_counts[other] = weak_counts.get(other, 0) + 1
        if current in vectors:
            for other, other_vector in vectors.items():
                if other != current and near_identical(vectors[current], other_vector):
                    weak_counts[other] = weak_counts.get(other, 0) + 1
        for other, count in weak_counts.items():
            if count >= WEAK_LINKS_REQUIRED:
                neighbours.add(other)
                shared.setdefault("ip_block_and_input_timing", set()).update({current, other})
        for neighbour in neighbours - seen:
            seen.add(neighbour)
            queue.append(neighbour)

    return {"size": len(seen), "members": sorted(seen), "shared": {kind: len(ids) for kind, ids in shared.items()}}


def is_farm(result: dict[str, Any]) -> bool:
    return int(result.get("size", 1)) >= FARM_MIN_SIZE
