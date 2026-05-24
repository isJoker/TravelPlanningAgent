"""Tool wrapper that adds caching, fallback, and ``monitor`` telemetry.

Nodes call e.g. ``await weather.fetch(...)``; the wrapper publishes
``tool_start`` / ``tool_end`` events to the active websocket via the singleton
monitor — no parameter threading required.
"""
from __future__ import annotations

import time
from typing import Any

from api.logger import logger
from api.monitor import monitor
from tools import cache
from tools.providers.base import BaseProvider


class TravelTool:
    name: str = "tool"

    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    async def fetch(self, **kwargs: Any) -> Any:
        provider_name = getattr(self.provider, "name", "unknown")
        monitor.report_tool_start(self.name, args=kwargs)
        t0 = time.perf_counter()

        key = cache.make_key(self.name, provider_name, kwargs)
        cached = await cache.get(key)
        if cached is not None:
            duration = (time.perf_counter() - t0) * 1000
            monitor.report_tool_end(self.name, summary=f"cache hit ({duration:.0f}ms)")
            return cached

        try:
            result = await self.provider.fetch(**kwargs)
            await cache.set(key, result)
            duration = (time.perf_counter() - t0) * 1000
            n = len(result) if hasattr(result, "__len__") else 1
            monitor.report_tool_end(
                self.name,
                summary=f"{provider_name}: {n} items in {duration:.0f}ms",
            )
            return result
        except Exception as e:
            logger.warning(f"{self.name} provider={provider_name} failed: {e}")
            if self.provider.fallback is not None:
                try:
                    result = await self.provider.fallback.fetch(**kwargs)
                    monitor.report_tool_end(self.name, summary=f"fallback used ({type(e).__name__})")
                    return result
                except Exception as fe:  # pragma: no cover
                    monitor.report_error(self.name, f"primary={e!r} fallback={fe!r}")
                    raise
            monitor.report_error(self.name, str(e))
            raise


class WeatherTool(TravelTool):
    name = "WeatherTool"


class FlightTool(TravelTool):
    name = "FlightTool"


class HotelTool(TravelTool):
    name = "HotelTool"


class POITool(TravelTool):
    name = "POITool"
