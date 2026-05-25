"""Deterministic mock hotel provider."""
from __future__ import annotations

import hashlib
import random
from typing import Any, List

from tools.providers.base import BaseProvider

_AREAS = ["市中心", "老城区", "海滨", "山景", "近机场", "商务区"]
_ADJ = ["亲子", "精品", "豪华", "舒适", "城景", "全景", "亲水"]


def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class MockHotelProvider(BaseProvider):
    name = "mock"

    async def fetch(
        self,
        *,
        city: str,
        checkin: str,
        checkout: str,
        pax: int = 2,
        theme: str | None = None,
        **_: Any,
    ) -> List[dict]:
        rng = random.Random(_seed(city, checkin, checkout, theme or ""))
        kid = (theme or "").startswith("亲子")
        out: list[dict] = []
        for i in range(rng.randint(5, 8)):
            area = _AREAS[rng.randint(0, len(_AREAS) - 1)]
            adj = _ADJ[rng.randint(0, len(_ADJ) - 1)]
            base = rng.uniform(380, 1500)
            if kid:
                base *= 1.1
            out.append(
                {
                    "name": f"{city}{adj}酒店·{area}店{i + 1}",
                    "area": area,
                    "price_per_night": round(base, 0),
                    "rating": round(rng.uniform(4.0, 4.9), 1),
                    "kid_friendly": kid or rng.random() < 0.4,
                    "image_url": None,
                    "lng": round(rng.uniform(110, 140), 4),
                    "lat": round(rng.uniform(20, 45), 4),
                }
            )
        return sorted(out, key=lambda x: -x["rating"])
