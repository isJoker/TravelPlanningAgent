"""Provider adapter base class.

Each tool delegates to a Provider so we can swap mock ↔ real without touching
graph or node code. ``fallback`` is an optional secondary provider that is
tried when the primary raises.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseProvider(ABC):
    name: str = "base"
    fallback: Optional["BaseProvider"] = None

    @abstractmethod
    async def fetch(self, **kwargs: Any) -> Any:  # pragma: no cover
        ...
