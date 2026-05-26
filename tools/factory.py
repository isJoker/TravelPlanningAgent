"""Tool factories: hide Mock vs Real adapter selection from callers.

Today (USE_MOCK_TOOLS=true) all tools resolve to mock providers. When
flipped to false, ``select_provider`` consults a routing table that maps
(tool, is_domestic) → provider name.
"""
from __future__ import annotations

import os
from typing import Any

from core.logger import logger
from tools.providers.base import BaseProvider
from tools.providers.mocks.mock_flight import MockFlightProvider
from tools.providers.mocks.mock_hotel import MockHotelProvider
from tools.providers.mocks.mock_poi import MockPOIProvider
from tools.providers.mocks.mock_weather import MockWeatherProvider


def _truthy(v: str | None) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


def _is_china_city(name: str) -> bool:
    cn = ["北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "西安", "苏州", "南京",
          "厦门", "三亚", "青岛", "天津", "武汉", "长沙", "郑州", "合肥", "济南", "大连"]
    return any(c in (name or "") for c in cn)


# ---------- per-tool resolution ----------
def get_weather_provider(destination: str) -> BaseProvider:
    if _truthy(os.getenv("USE_MOCK_TOOLS", "true")):
        return MockWeatherProvider()
    # Real provider routing left as a stub — see DESIGN.md §5.3.
    logger.warning("USE_MOCK_TOOLS=false but real Weather provider not wired in demo; using mock")
    return MockWeatherProvider()


def get_flight_provider(departure: str, destination: str) -> BaseProvider:
    if _truthy(os.getenv("USE_MOCK_TOOLS", "true")):
        return MockFlightProvider()
    logger.warning("Real Flight provider not wired in demo; using mock")
    return MockFlightProvider()


def get_hotel_provider(destination: str) -> BaseProvider:
    if _truthy(os.getenv("USE_MOCK_TOOLS", "true")):
        return MockHotelProvider()
    logger.warning("Real Hotel provider not wired in demo; using mock")
    return MockHotelProvider()


def get_poi_provider(destination: str) -> BaseProvider:
    if _truthy(os.getenv("USE_MOCK_TOOLS", "true")):
        return MockPOIProvider()
    logger.warning("Real POI provider not wired in demo; using mock")
    return MockPOIProvider()
