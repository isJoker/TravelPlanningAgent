"""Tool factories: hide Mock vs Real adapter selection from callers.

Selection rules (per tool):

  USE_MOCK_TOOLS=true                   → always Mock
  USE_MOCK_TOOLS=false (or unset)       → real provider, picked by
      ``select_provider(tool, destination)`` (DESIGN.md §5.3.9):

        weather domestic   → QWeather       (needs QWEATHER_API_KEY)
        weather overseas   → OpenWeatherMap (needs OPENWEATHER_API_KEY)
        flight  *          → Amadeus        (needs AMADEUS_API_KEY/SECRET)
        hotel   *          → Amadeus        (needs AMADEUS_API_KEY/SECRET)
        poi     domestic   → Amap           (needs AMAP_API_KEY)
        poi     overseas   → Amap (best-effort) → falls back to mock

If a real provider's required keys are missing we fall back to the mock
silently (with a warning), so the demo continues to work.

Each real provider also sets ``self.fallback = Mock...`` so transient
upstream failures degrade to mock data via ``tools.base.TravelTool``.
"""
from __future__ import annotations

import os

from core.logger import logger
from tools.providers.base import BaseProvider
from tools.providers.mocks.mock_flight import MockFlightProvider
from tools.providers.mocks.mock_hotel import MockHotelProvider
from tools.providers.mocks.mock_poi import MockPOIProvider
from tools.providers.mocks.mock_weather import MockWeatherProvider


def _truthy(v: str | None) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


_CN_CITIES = (
    "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "西安", "苏州", "南京",
    "厦门", "三亚", "青岛", "天津", "武汉", "长沙", "郑州", "合肥", "济南", "大连",
    "哈尔滨", "沈阳", "昆明", "贵阳", "南宁", "桂林", "拉萨", "丽江", "大理", "香港",
    "澳门", "台北",
)


def _is_china_city(name: str) -> bool:
    if not name:
        return False
    # Quick whitelist match...
    if any(c in name for c in _CN_CITIES):
        return True
    # ...then fall back to "any CJK character" as a heuristic. Imperfect for
    # mixed-language inputs, but correct for the curated demo cities.
    return any("\u4e00" <= ch <= "\u9fff" for ch in name)


def _use_mock() -> bool:
    return _truthy(os.getenv("USE_MOCK_TOOLS", "true"))


# ---------- per-tool resolution ----------
def get_weather_provider(destination: str) -> BaseProvider:
    if _use_mock():
        return MockWeatherProvider()
    domestic = _is_china_city(destination)
    if domestic and os.getenv("QWEATHER_API_KEY"):
        from tools.providers.real.qweather import QWeatherProvider
        return QWeatherProvider()
    if not domestic and os.getenv("OPENWEATHER_API_KEY"):
        from tools.providers.real.openweather import OpenWeatherProvider
        return OpenWeatherProvider()
    logger.warning(
        f"Real weather provider keys missing for destination={destination!r}; using mock"
    )
    return MockWeatherProvider()


def get_flight_provider(departure: str, destination: str) -> BaseProvider:
    if _use_mock():
        return MockFlightProvider()
    if os.getenv("AMADEUS_API_KEY") and os.getenv("AMADEUS_API_SECRET"):
        from tools.providers.real.amadeus import AmadeusFlightProvider
        return AmadeusFlightProvider()
    logger.warning(
        f"AMADEUS_API_KEY/SECRET missing (departure={departure!r} "
        f"destination={destination!r}); using mock"
    )
    return MockFlightProvider()


def get_hotel_provider(destination: str) -> BaseProvider:
    if _use_mock():
        return MockHotelProvider()
    if os.getenv("AMADEUS_API_KEY") and os.getenv("AMADEUS_API_SECRET"):
        from tools.providers.real.amadeus import AmadeusHotelProvider
        return AmadeusHotelProvider()
    logger.warning(f"AMADEUS_API_KEY/SECRET missing (destination={destination!r}); using mock")
    return MockHotelProvider()


def get_poi_provider(destination: str) -> BaseProvider:
    if _use_mock():
        return MockPOIProvider()
    domestic = _is_china_city(destination)
    if domestic and os.getenv("AMAP_API_KEY"):
        from tools.providers.real.amap import AmapPOIProvider
        return AmapPOIProvider()
    if not domestic:
        logger.warning(
            f"No overseas POI provider configured for destination={destination!r}; using mock"
        )
        return MockPOIProvider()
    logger.warning(f"AMAP_API_KEY missing (destination={destination!r}); using mock")
    return MockPOIProvider()
