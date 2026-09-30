from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


GENESIS_HASH = "0" * 64
_HASHED_FIELDS = (
    "event_id",
    "tenant_id",
    "event_type",
    "outcome",
    "actor_id",
    "actor_roles",
    "http_method",
    "route",
    "source_ip",
    "resource_id",
    "details",
    "chain_id",
    "chain_sequence",
    "created_at",
)


def _canonical_timestamp(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical_audit_payload(event: dict[str, Any]) -> bytes:
    """Serialize the stable audit fields used by both writers and verifiers."""
    payload = {key: event.get(key) for key in _HASHED_FIELDS}
    payload["event_id"] = str(payload["event_id"])
    payload["tenant_id"] = str(payload["tenant_id"])
    payload["event_type"] = str(payload["event_type"])
    payload["outcome"] = str(payload["outcome"])
    payload["actor_roles"] = list(payload["actor_roles"] or [])
    payload["details"] = payload["details"] or {}
    payload["chain_id"] = str(payload["chain_id"])
    payload["chain_sequence"] = int(payload["chain_sequence"])
    payload["created_at"] = _canonical_timestamp(payload["created_at"])
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def audit_event_hash(previous_hash: str, event: dict[str, Any]) -> str:
    if len(previous_hash) != 64 or any(character not in "0123456789abcdef" for character in previous_hash):
        raise ValueError("previous_hash must be a lowercase SHA-256 digest")
    return hashlib.sha256(previous_hash.encode("ascii") + b"\n" + canonical_audit_payload(event)).hexdigest()


def verify_audit_event(previous_hash: str, event: dict[str, Any]) -> bool:
    if event.get("previous_hash") != previous_hash:
        return False
    try:
        return event.get("event_hash") == audit_event_hash(previous_hash, event)
    except (KeyError, TypeError, ValueError):
        return False
