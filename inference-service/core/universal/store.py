"""Key-value storage for the universal behavioral engine.

Everything the engine keeps (entity state, baselines, link indexes, session verdicts, site
registry) goes through this small interface, so it runs on Redis in shared deployments and on
process memory in local runs and tests. Keys never collide with the rest of inference-service:
the Redis implementation writes only under its own ``nsoc:ub:`` prefix.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

KEY_PREFIX = "nsoc:ub:"


class MemoryKV:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}
        self._expiry: dict[str, float] = {}
        self._lock = threading.RLock()

    def _expired(self, key: str) -> bool:
        deadline = self._expiry.get(key)
        if deadline is not None and deadline <= time.time():
            self._values.pop(key, None)
            self._sets.pop(key, None)
            self._lists.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    def get(self, key: str) -> str | None:
        with self._lock:
            if self._expired(key):
                return None
            return self._values.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        with self._lock:
            self._values[key] = value
            if ttl:
                self._expiry[key] = time.time() + ttl
            else:
                self._expiry.pop(key, None)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)
            self._sets.pop(key, None)
            self._lists.pop(key, None)
            self._expiry.pop(key, None)

    def sadd(self, key: str, *members: str) -> None:
        with self._lock:
            self._expired(key)
            self._sets.setdefault(key, set()).update(members)

    def srem(self, key: str, *members: str) -> None:
        with self._lock:
            self._sets.get(key, set()).difference_update(members)

    def smembers(self, key: str) -> set[str]:
        with self._lock:
            if self._expired(key):
                return set()
            return set(self._sets.get(key, set()))

    def lpush_trim(self, key: str, value: str, maxlen: int) -> None:
        with self._lock:
            self._expired(key)
            items = self._lists.setdefault(key, [])
            items.insert(0, value)
            del items[maxlen:]

    def lrange(self, key: str, count: int) -> list[str]:
        with self._lock:
            if self._expired(key):
                return []
            return list(self._lists.get(key, [])[:count])

    def expire(self, key: str, ttl: int) -> None:
        with self._lock:
            self._expiry[key] = time.time() + ttl


class RedisKV:
    """Thin adapter over a redis-py client created with ``decode_responses=True``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def get(self, key: str) -> str | None:
        return self._client.get(KEY_PREFIX + key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._client.set(KEY_PREFIX + key, value, ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(KEY_PREFIX + key)

    def sadd(self, key: str, *members: str) -> None:
        if members:
            self._client.sadd(KEY_PREFIX + key, *members)

    def srem(self, key: str, *members: str) -> None:
        if members:
            self._client.srem(KEY_PREFIX + key, *members)

    def smembers(self, key: str) -> set[str]:
        return set(self._client.smembers(KEY_PREFIX + key))

    def lpush_trim(self, key: str, value: str, maxlen: int) -> None:
        pipe = self._client.pipeline()
        pipe.lpush(KEY_PREFIX + key, value)
        pipe.ltrim(KEY_PREFIX + key, 0, maxlen - 1)
        pipe.execute()

    def lrange(self, key: str, count: int) -> list[str]:
        return list(self._client.lrange(KEY_PREFIX + key, 0, count - 1))

    def expire(self, key: str, ttl: int) -> None:
        self._client.expire(KEY_PREFIX + key, ttl)


def get_json(kv: MemoryKV | RedisKV, key: str, default: Any = None) -> Any:
    raw = kv.get(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def set_json(kv: MemoryKV | RedisKV, key: str, value: Any, ttl: int | None = None) -> None:
    kv.set(key, json.dumps(value, separators=(",", ":")), ttl=ttl)


def build_kv(redis_client: Any | None) -> MemoryKV | RedisKV:
    return RedisKV(redis_client) if redis_client is not None else MemoryKV()
