"""Shared ``@timed`` decorator for LangGraph node coroutines.

Wraps a node function so that:

  - ``monitor.report_node_start(node_name)`` fires on entry,
  - ``monitor.report_node_end(node_name, duration_ms, summary)`` fires on
    success (consuming any ``_summary`` key the node returns),
  - ``monitor.report_error(node_name, str(exc))`` fires before the
    exception is re-raised.

Lives in ``agent/`` rather than ``core/`` because it depends on the LangGraph
state-shape contract (``state -> partial_state``); ``core/`` should stay
free of orchestration semantics.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from core.monitor import monitor


def timed(node_name: str) -> Callable:
    """Decorate a node coroutine to emit ``node_start`` / ``node_end`` events."""

    def deco(fn: Callable[..., Awaitable[dict[str, Any]]]):
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            monitor.report_node_start(node_name)
            t0 = time.perf_counter()
            try:
                result = await fn(state)
            except Exception as e:
                monitor.report_error(node_name, str(e))
                raise
            duration = (time.perf_counter() - t0) * 1000
            summary = result.pop("_summary", None) if isinstance(result, dict) else None
            monitor.report_node_end(node_name, duration, summary)
            return result or {}

        wrapper.__name__ = node_name
        return wrapper

    return deco
