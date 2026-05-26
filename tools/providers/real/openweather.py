"""OpenWeatherMap provider — overseas weather first choice.

Free plan endpoints used:
  - /geo/1.0/direct          (city → lat/lon)
  - /data/2.5/forecast       (5 day / 3 hour forecast)

We aggregate the 3-hour rows into per-day high / low / condition / pop.

Docs:
  - https://openweathermap.org/api/geocoding-api
  - https://openweathermap.org/forecast5
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, List

import httpx

from core.logger import logger
from tools.providers.base import BaseProvider
from tools.providers.mocks.mock_weather import MockWeatherProvider

_BASE = "https://api.openweathermap.org"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Map OpenWeather "main" conditions to our small condition set.
_OWM_MAIN_MAP = {
    "Clear": "晴",
    "Clouds": "多云",
    "Mist": "阴", "Fog": "阴", "Haze": "阴", "Smoke": "阴",
    "Drizzle": "小雨", "Rain": "小雨",
    "Thunderstorm": "雷阵雨",
    "Snow": "小雨",  # demo schema doesn't have snow; keep "小雨" so downstream still parses.
}


class OpenWeatherProvider(BaseProvider):
    name = "openweather"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        self.fallback = MockWeatherProvider()
        if not self.api_key:
            logger.warning(
                "OPENWEATHER_API_KEY not set; OpenWeatherProvider will fail and fall back"
            )

    async def fetch(self, *, city: str, date_range: List[str], **_: Any) -> List[dict]:
        if not self.api_key:
            raise RuntimeError("OPENWEATHER_API_KEY missing")

        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            lat, lon = await self._geocode(http, city)
            buckets = await self._daily_buckets(http, lat, lon)

        out: list[dict] = []
        last: dict | None = None
        for d in date_range:
            entry = buckets.get(d) or last
            if not entry:
                # Outside the 5-day forecast window — degrade with a generic default.
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
                "temp_high": round(float(entry["temp_high"]), 1),
                "temp_low": round(float(entry["temp_low"]), 1),
                "condition": entry["condition"],
                "rain_prob": round(float(entry["rain_prob"]), 2),
            })
        return out

    async def _geocode(self, http: httpx.AsyncClient, city: str) -> tuple[float, float]:
        url = f"{_BASE}/geo/1.0/direct"
        r = await http.get(url, params={"q": city, "limit": 1, "appid": self.api_key})
        r.raise_for_status()
        body = r.json()
        if not body:
            raise RuntimeError(f"OpenWeather geocode returned empty for city={city}")
        return float(body[0]["lat"]), float(body[0]["lon"])

    async def _daily_buckets(
        self, http: httpx.AsyncClient, lat: float, lon: float
    ) -> dict[str, dict]:
        url = f"{_BASE}/data/2.5/forecast"
        r = await http.get(
            url,
            params={
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric",
                "lang": "zh_cn",
            },
        )
        r.raise_for_status()
        body = r.json()

        # Group 3-hour rows by YYYY-MM-DD (UTC; close enough for this demo).
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in body.get("list", []):
            dt_txt = row.get("dt_txt", "")  # "2026-07-15 12:00:00"
            day = dt_txt.split(" ")[0] if dt_txt else None
            if day:
                groups[day].append(row)

        out: dict[str, dict] = {}
        for day, rows in groups.items():
            highs = [r.get("main", {}).get("temp_max") for r in rows if r.get("main")]
            lows = [r.get("main", {}).get("temp_min") for r in rows if r.get("main")]
            highs = [t for t in highs if isinstance(t, (int, float))]
            lows = [t for t in lows if isinstance(t, (int, float))]
            pops = [float(r.get("pop", 0) or 0) for r in rows]
            mains = [
                (r.get("weather") or [{}])[0].get("main", "")
                for r in rows
                if r.get("weather")
            ]
            out[day] = {
                "temp_high": max(highs) if highs else 25.0,
                "temp_low": min(lows) if lows else 18.0,
                "rain_prob": max(pops) if pops else 0.0,
                "condition": _OWM_MAIN_MAP.get(_dominant(mains), _dominant(mains) or "多云"),
            }
        return out


def _dominant(items: list[str]) -> str:
    if not items:
        return ""
    counts: dict[str, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]
