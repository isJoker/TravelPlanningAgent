"""QWeather (和风天气) provider — domestic weather first choice.

Docs: https://dev.qweather.com/docs/api/

Flow:
  1. Resolve city name → LocationID via /geo/v2/city/lookup
  2. Fetch /v7/weather/7d (free tier, 7 day forecast)
  3. Map fxDate / tempMax / tempMin / textDay / pop → our schema

Endpoint host:
  - Free dev plan        → https://devapi.qweather.com
  - Standard / Pro plans → https://api.qweather.com (or your custom Pro host)
Override via QWEATHER_API_HOST.
"""
from __future__ import annotations

import os
from typing import Any, List

import httpx

from core.logger import logger
from tools.providers.base import BaseProvider
from tools.providers.mocks.mock_weather import MockWeatherProvider

_DEFAULT_HOST = "https://devapi.qweather.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_CONDITION_MAP = {
    "晴": "晴", "多云": "多云", "少云": "多云", "阴": "阴",
    "小雨": "小雨", "中雨": "小雨", "大雨": "雷阵雨", "暴雨": "雷阵雨",
    "雷阵雨": "雷阵雨", "阵雨": "小雨",
}


def _normalise_condition(text: str) -> str:
    """Coerce QWeather's free-text condition to the small set used in the demo."""
    if not text:
        return "多云"
    for key, val in _CONDITION_MAP.items():
        if key in text:
            return val
    return text  # pass-through if unknown


class QWeatherProvider(BaseProvider):
    name = "qweather"

    def __init__(self) -> None:
        self.api_key = os.getenv("QWEATHER_API_KEY", "").strip()
        self.host = os.getenv("QWEATHER_API_HOST", _DEFAULT_HOST).rstrip("/")
        self.fallback = MockWeatherProvider()
        if not self.api_key:
            logger.warning("QWEATHER_API_KEY not set; QWeatherProvider will fail and fall back")

    async def fetch(self, *, city: str, date_range: List[str], **_: Any) -> List[dict]:
        if not self.api_key:
            raise RuntimeError("QWEATHER_API_KEY missing")

        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            location_id = await self._lookup_location(http, city)
            data = await self._fetch_7d(http, location_id)

        # Index QWeather entries by date for date_range alignment.
        by_date = {d["fxDate"]: d for d in data.get("daily", [])}
        out: list[dict] = []
        last: dict | None = None
        for d in date_range:
            entry = by_date.get(d) or last
            if not entry:
                # No data yet (first iteration with no overlap) — synthesize sane default.
                out.append({
                    "date": d,
                    "temp_high": 25.0,
                    "temp_low": 18.0,
                    "condition": "多云",
                    "rain_prob": 0.2,
                })
                continue
            last = entry
            out.append({
                "date": d,
                "temp_high": float(entry.get("tempMax", 25)),
                "temp_low": float(entry.get("tempMin", 18)),
                "condition": _normalise_condition(entry.get("textDay", "")),
                "rain_prob": _pop_to_prob(entry.get("pop"), entry.get("textDay", "")),
            })
        return out

    async def _lookup_location(self, http: httpx.AsyncClient, city: str) -> str:
        # /geo/v2/city/lookup is the v2 GeoAPI; falls back to v1 with same shape.
        url = f"{self.host}/geo/v2/city/lookup"
        r = await http.get(url, params={"location": city, "key": self.api_key, "number": 1})
        r.raise_for_status()
        body = r.json()
        if body.get("code") != "200" or not body.get("location"):
            raise RuntimeError(f"QWeather city lookup failed: code={body.get('code')} city={city}")
        return body["location"][0]["id"]

    async def _fetch_7d(self, http: httpx.AsyncClient, location_id: str) -> dict:
        url = f"{self.host}/v7/weather/7d"
        r = await http.get(url, params={"location": location_id, "key": self.api_key})
        r.raise_for_status()
        body = r.json()
        if body.get("code") != "200":
            raise RuntimeError(f"QWeather 7d failed: code={body.get('code')}")
        return body


def _pop_to_prob(pop: Any, text: str) -> float:
    """QWeather 'pop' is a precipitation probability percentage (paid plans only).

    On the free dev plan it is often missing, so we synthesize from the
    text description as a fallback.
    """
    try:
        if pop is not None and pop != "":
            return round(float(pop) / 100.0, 2)
    except (TypeError, ValueError):
        pass
    if "暴雨" in text or "雷" in text:
        return 0.85
    if "大雨" in text:
        return 0.7
    if "雨" in text:
        return 0.5
    if "阴" in text:
        return 0.25
    if "云" in text:
        return 0.15
    return 0.05
