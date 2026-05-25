"""Deterministic mock flight provider."""
from __future__ import annotations

import hashlib
import random
from typing import Any, List

from tools.providers.base import BaseProvider

_AIRLINES = [
    ("国航", "CA"), ("东航", "MU"), ("南航", "CZ"),
    ("春秋", "9C"), ("吉祥", "HO"), ("海航", "HU"),
]


def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class MockFlightProvider(BaseProvider):
    name = "mock"

    async def fetch(
        self,
        *,
        from_city: str,
        to_city: str,
        date: str,
        pax: int = 1,
        direction: str = "outbound",
        **_: Any,
    ) -> List[dict]:
        rng = random.Random(_seed(from_city, to_city, date, direction))
        out: list[dict] = []
        for _ in range(rng.randint(3, 5)):
            airline_name, code = _AIRLINES[rng.randint(0, len(_AIRLINES) - 1)]
            depart_h = rng.randint(6, 22)
            duration = rng.randint(110, 240)
            arrive_h = (depart_h * 60 + duration) // 60
            arrive_h = arrive_h % 24
            price = round(rng.uniform(680, 2400), 0)
            out.append(
                {
                    "airline": airline_name,
                    "flight_no": f"{code}{rng.randint(1000, 9999)}",
                    "depart_time": f"{depart_h:02d}:{rng.randint(0, 59):02d}",
                    "arrive_time": f"{arrive_h:02d}:{rng.randint(0, 59):02d}",
                    "duration_minutes": duration,
                    "price": price * pax,
                    "stops": 0 if rng.random() < 0.7 else 1,
                    "direction": direction,
                }
            )
        return sorted(out, key=lambda x: x["price"])
