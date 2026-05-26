"""Process-local TTL cache shared by tools.

Keyed by ``(tool_name, provider, sha1(canonical(kwargs)))``. Replaces the Redis
cache referenced in the design with a zero-dependency in-memory variant.

We use one default ``TTLCache`` plus a small registry of per-TTL caches so
that callers can pass a custom ``ttl`` to :func:`set` and have it actually
honoured (``cachetools.TTLCache`` ties an entry's TTL to the cache instance,
not the entry).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from cachetools import TTLCache

_DEFAULT_TTL = 24 * 3600
# 4096 entries x ~24h max ttl is plenty for a demo.
_default_cache: TTLCache[str, Any] = TTLCache(maxsize=4096, ttl=_DEFAULT_TTL)
_caches_by_ttl: dict[int, TTLCache[str, Any]] = {_DEFAULT_TTL: _default_cache}


def _cache_for(ttl: int | None) -> TTLCache[str, Any]:
    if ttl is None or ttl == _DEFAULT_TTL:
        return _default_cache
    bucket = _caches_by_ttl.get(ttl)
    if bucket is None:
        bucket = TTLCache(maxsize=4096, ttl=ttl)
        _caches_by_ttl[ttl] = bucket
    return bucket


def make_key(tool: str, provider: str, kwargs: dict[str, Any]) -> str:
    canon = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]
    return f"{tool}:{provider}:{h}"


async def get(key: str) -> Any | None:
    # Search every TTL bucket; entries are namespaced by tool+provider+hash so
    # collisions across buckets are not possible by construction.
    for bucket in _caches_by_ttl.values():
        v = bucket.get(key)
        if v is not None:
            return v
    return None


async def set(key: str, value: Any, ttl: int | None = None) -> None:  # noqa: A001
    _cache_for(ttl)[key] = value
