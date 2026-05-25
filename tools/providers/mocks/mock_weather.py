"""Deterministic mock weather provider.

The output schema mirrors the real ``QWeather/OpenWeatherMap`` adapters so a
downstream switch costs zero changes upstream.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, List

from tools.providers.base import BaseProvider


_CONDITIONS = [("晴", 0.05), ("多云", 0.15), ("阴", 0.25), ("小雨", 0.55), ("雷阵雨", 0.75)]


def _seed(*parts: Any) -> int:
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.sha1(raw.encode()).hexdigest()[:8], 16)


class MockWeatherProvider(BaseProvider):
    name = "mock"

    async def fetch(self, *, city: str, date_range: List[str], **_: Any) -> List[dict]:
        out: list[dict] = []
        for d in date_range:
            rng = random.Random(_seed(city, d))
            condition, rain = _CONDITIONS[rng.randint(0, len(_CONDITIONS) - 1)]
            high = rng.randint(20, 33)
            low = high - rng.randint(5, 12)
            out.append(
                {
                    "date": d,
                    "temp_high": float(high),
                    "temp_low": float(low),
                    "condition": condition,
                    "rain_prob": rain,
                }
            )
        return out
