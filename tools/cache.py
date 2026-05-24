"""Process-local TTL cache shared by tools.

Keyed by ``(tool_name, provider, sha1(canonical(kwargs)))``. Replaces the Redis
cache referenced in the design with a zero-dependency in-memory variant.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from cachetools import TTLCache

# 4096 entries x ~24h max ttl is plenty for a demo.
_cache: TTLCache[str, Any] = TTLCache(maxsize=4096, ttl=24 * 3600)


def make_key(tool: str, provider: str, kwargs: dict[str, Any]) -> str:
    canon = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]
    return f"{tool}:{provider}:{h}"


async def get(key: str) -> Any | None:
    return _cache.get(key)


async def set(key: str, value: Any, ttl: int | None = None) -> None:  # noqa: A001
    # cachetools.TTLCache uses a single ttl; for the demo we honour the global ttl.
    _cache[key] = value
