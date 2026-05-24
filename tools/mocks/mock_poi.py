"""Mock POI provider backed by JSON fixtures + Faker fallback."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, List

from tools.providers.base import BaseProvider

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "poi"


def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _load_fixture(city: str) -> List[dict] | None:
    """Try Chinese first, then ASCII, then a default fallback."""
    candidates = [city, city.replace(" ", "").lower()]
    for stem in candidates:
        path = _FIXTURE_DIR / f"{stem}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def _synth(city: str, theme: str | None) -> List[dict]:
    rng = random.Random(_seed(city, theme or ""))
    types = ["景点", "景点", "餐厅", "餐厅", "体验", "购物"]
    areas = ["市中心", "老城区", "海滨", "山景", "近郊"]
    out: list[dict] = []
    for i in range(20):
        t = types[rng.randint(0, len(types) - 1)]
        out.append(
            {
                "name": f"{city}{t}·点{i + 1}",
                "type": t,
                "area": areas[rng.randint(0, len(areas) - 1)],
                "lng": round(rng.uniform(110, 140), 4),
                "lat": round(rng.uniform(20, 45), 4),
                "rating": round(rng.uniform(3.8, 4.9), 1),
                "duration_minutes": rng.choice([60, 90, 120, 150]),
                "ticket_price": float(rng.choice([0, 0, 0, 30, 60, 120, 200])),
                "indoor": rng.random() < 0.4,
                "suitable_for_kids": rng.random() < 0.7,
            }
        )
    return out


class MockPOIProvider(BaseProvider):
    name = "mock"

    async def fetch(self, *, city: str, theme: str | None = None, **_: Any) -> List[dict]:
        data = _load_fixture(city)
        if data is None:
            data = _synth(city, theme)
        # Light theme-aware filtering (gives a sane signal without overfitting).
        if theme and "亲子" in theme:
            data = [p for p in data if p.get("suitable_for_kids", True)]
        elif theme and "美食" in theme:
            data = sorted(data, key=lambda p: 0 if p.get("type") == "餐厅" else 1)
        return data
