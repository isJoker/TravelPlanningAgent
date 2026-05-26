"""Amap (高德地图) Web Service POI provider.

Docs: https://lbs.amap.com/api/webservice/guide/api/search

Endpoint: GET /v3/place/text
We pick keywords from the travel theme, query the city, then map the
result rows into our POI schema. Rating / duration / ticket_price are
not exposed by Amap's free POI search, so we synthesize sensible defaults
based on POI type (consistent with the mock provider).

Amap is a domestic-China service; for overseas destinations the factory
should pick a different provider (or fall back to mock).
"""
from __future__ import annotations

import os
from typing import Any, List, Tuple

import httpx

from core.logger import logger
from tools.providers.base import BaseProvider
from tools.providers.mocks.mock_poi import MockPOIProvider

_BASE = "https://restapi.amap.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _theme_keywords(theme: str | None) -> str:
    """Map a high-level travel theme to Amap-friendly keyword filters."""
    if not theme:
        return "景点|景区|公园|博物馆"
    if "亲子" in theme:
        return "亲子|乐园|动物园|公园|科技馆"
    if "美食" in theme:
        return "餐厅|美食|小吃|地方菜"
    if "户外" in theme:
        return "公园|登山|徒步|海滨|湖泊"
    if "蜜月" in theme or "情侣" in theme:
        return "夜景|海滨|地标|观景台"
    if "文化" in theme or "历史" in theme:
        return "博物馆|古迹|寺庙|历史"
    return "景点|景区|公园|博物馆"


def _classify_type(amap_type: str) -> str:
    """Coerce Amap's nested type string ('餐饮服务;中餐厅;...') to our small set."""
    if not amap_type:
        return "景点"
    head = amap_type.split(";", 1)[0]
    if "餐" in head or "美食" in amap_type:
        return "餐厅"
    if "购物" in head:
        return "购物"
    if "体育" in head or "娱乐" in head:
        return "体验"
    return "景点"


def _ticket_for(t: str) -> float:
    if t == "餐厅":
        return 0.0
    if t == "购物":
        return 0.0
    if t == "体验":
        return 60.0
    return 30.0  # generic 景点 default


def _duration_for(t: str) -> int:
    return {"餐厅": 60, "购物": 90, "体验": 120, "景点": 120}.get(t, 90)


def _split_location(loc: str) -> Tuple[float, float]:
    """Amap returns 'lng,lat' as a string."""
    if not loc or "," not in loc:
        return 0.0, 0.0
    try:
        lng_s, lat_s = loc.split(",", 1)
        return float(lng_s), float(lat_s)
    except ValueError:
        return 0.0, 0.0


class AmapPOIProvider(BaseProvider):
    name = "amap"

    def __init__(self) -> None:
        self.api_key = os.getenv("AMAP_API_KEY", "").strip()
        self.fallback = MockPOIProvider()
        if not self.api_key:
            logger.warning("AMAP_API_KEY not set; AmapPOIProvider will fail and fall back")

    async def fetch(self, *, city: str, theme: str | None = None, **_: Any) -> List[dict]:
        if not self.api_key:
            raise RuntimeError("AMAP_API_KEY missing")

        keywords = _theme_keywords(theme)
        kid = bool(theme and "亲子" in theme)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.get(
                f"{_BASE}/v3/place/text",
                params={
                    "key": self.api_key,
                    "keywords": keywords,
                    "city": city,
                    "citylimit": "true",
                    "extensions": "base",
                    "offset": 25,
                    "page": 1,
                    "output": "JSON",
                },
            )
            r.raise_for_status()
            body = r.json()

        if str(body.get("status")) != "1":
            raise RuntimeError(
                f"Amap POI search failed: status={body.get('status')} info={body.get('info')}"
            )

        out: list[dict] = []
        for row in body.get("pois", []):
            t = _classify_type(row.get("type", ""))
            lng, lat = _split_location(row.get("location") or "")
            area = row.get("business_area") or row.get("adname") or row.get("address") or "市中心"
            indoor = t in {"餐厅", "购物", "体验"} or "博物馆" in str(row.get("type", ""))
            out.append({
                "name": row.get("name") or "未命名地点",
                "type": t,
                "area": area if isinstance(area, str) else "市中心",
                "lng": lng,
                "lat": lat,
                "rating": 4.3,  # Amap free tier doesn't expose ratings; placeholder.
                "duration_minutes": _duration_for(t),
                "ticket_price": _ticket_for(t),
                "indoor": indoor,
                "suitable_for_kids": kid or t != "体验",
            })

        # Light theme-aware re-ranking, mirroring the mock provider's behaviour.
        if theme and "亲子" in theme:
            out = [p for p in out if p.get("suitable_for_kids", True)]
        elif theme and "美食" in theme:
            out.sort(key=lambda p: 0 if p.get("type") == "餐厅" else 1)
        return out
