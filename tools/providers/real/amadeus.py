"""Amadeus Self-Service provider — flights + hotels.

Both flight and hotel adapters share the same OAuth2 client-credentials
token (cached at module level until expiry).

Docs:
  - Auth:    https://developers.amadeus.com/self-service/apis-docs/guides/authorization-262
  - Flights: https://developers.amadeus.com/self-service/category/flights/api-doc/flight-offers-search
  - Hotels:  https://developers.amadeus.com/self-service/category/hotels/api-doc/hotel-search

Test base URL is ``https://test.api.amadeus.com`` (free 2000 calls / month);
production is ``https://api.amadeus.com``. Override via AMADEUS_BASE_URL.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, List, Optional

import httpx

from core.logger import logger
from tools.providers.base import BaseProvider
from tools.providers.mocks.mock_flight import MockFlightProvider
from tools.providers.mocks.mock_hotel import MockHotelProvider

_DEFAULT_BASE = "https://test.api.amadeus.com"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Module-level token cache, shared across both providers.
_token: dict[str, Any] = {"value": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()

# Tiny city → IATA cache (Amadeus city lookup is metered).
_iata_cache: dict[str, str] = {}


def _base_url() -> str:
    return os.getenv("AMADEUS_BASE_URL", _DEFAULT_BASE).rstrip("/")


def _creds() -> tuple[str, str]:
    return (
        os.getenv("AMADEUS_API_KEY", "").strip(),
        os.getenv("AMADEUS_API_SECRET", "").strip(),
    )


async def _get_access_token(http: httpx.AsyncClient) -> str:
    """Return a cached Amadeus OAuth2 token, refreshing 60s before expiry."""
    now = time.time()
    if _token["value"] and now < _token["expires_at"] - 60:
        return _token["value"]

    async with _token_lock:
        if _token["value"] and time.time() < _token["expires_at"] - 60:
            return _token["value"]
        key, secret = _creds()
        if not key or not secret:
            raise RuntimeError("AMADEUS_API_KEY / AMADEUS_API_SECRET missing")

        r = await http.post(
            f"{_base_url()}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": key,
                "client_secret": secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        body = r.json()
        _token["value"] = body["access_token"]
        _token["expires_at"] = time.time() + int(body.get("expires_in", 1800))
        return _token["value"]


async def _resolve_iata(http: httpx.AsyncClient, token: str, city: str) -> str:
    """City keyword → IATA city/airport code (e.g. '上海' → 'SHA', 'Tokyo' → 'TYO')."""
    if not city:
        raise RuntimeError("city is empty")
    cached = _iata_cache.get(city)
    if cached:
        return cached

    r = await http.get(
        f"{_base_url()}/v1/reference-data/locations",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "keyword": city,
            "subType": "CITY,AIRPORT",
            "page[limit]": 5,
            "view": "LIGHT",
        },
    )
    r.raise_for_status()
    body = r.json()
    items = body.get("data") or []
    if not items:
        raise RuntimeError(f"Amadeus location lookup empty for city={city!r}")
    # Prefer a CITY match; otherwise take the first AIRPORT.
    cities = [it for it in items if it.get("subType") == "CITY"]
    pick = cities[0] if cities else items[0]
    code = pick.get("iataCode") or (pick.get("address") or {}).get("cityCode")
    if not code:
        raise RuntimeError(f"Amadeus location has no IATA code: {pick}")
    _iata_cache[city] = code
    return code


# ---------- Flights ----------
def _iso_duration_to_minutes(s: str) -> int:
    """Convert ISO-8601 duration like 'PT2H30M' to total minutes."""
    if not s:
        return 0
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?", s)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    return h * 60 + mi


def _hhmm(dt: str) -> str:
    """Extract HH:MM from an ISO datetime '2026-07-15T08:30:00'."""
    if not dt or "T" not in dt:
        return "00:00"
    return dt.split("T", 1)[1][:5]


class AmadeusFlightProvider(BaseProvider):
    name = "amadeus_flight"

    def __init__(self) -> None:
        self.fallback = MockFlightProvider()
        if not all(_creds()):
            logger.warning(
                "AMADEUS_API_KEY/SECRET not set; AmadeusFlightProvider will fail and fall back"
            )

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
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            token = await _get_access_token(http)
            origin = await _resolve_iata(http, token, from_city)
            dest = await _resolve_iata(http, token, to_city)

            r = await http.get(
                f"{_base_url()}/v2/shopping/flight-offers",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "originLocationCode": origin,
                    "destinationLocationCode": dest,
                    "departureDate": date,
                    "adults": max(1, int(pax)),
                    "currencyCode": "CNY",
                    "max": 5,
                    "nonStop": "false",
                },
            )
            r.raise_for_status()
            body = r.json()

        offers = body.get("data") or []
        out: list[dict] = []
        for offer in offers:
            itineraries = offer.get("itineraries") or []
            if not itineraries:
                continue
            it = itineraries[0]
            segments = it.get("segments") or []
            if not segments:
                continue
            first, last = segments[0], segments[-1]
            carrier_code = first.get("carrierCode", "")
            number = first.get("number", "")
            duration = _iso_duration_to_minutes(it.get("duration", ""))
            try:
                price = float((offer.get("price") or {}).get("total", 0))
            except (TypeError, ValueError):
                price = 0.0
            out.append({
                "airline": carrier_code or "Unknown",
                "flight_no": f"{carrier_code}{number}",
                "depart_time": _hhmm((first.get("departure") or {}).get("at", "")),
                "arrive_time": _hhmm((last.get("arrival") or {}).get("at", "")),
                "duration_minutes": duration,
                "price": round(price, 0),
                "stops": max(0, len(segments) - 1),
                "direction": direction,
            })
        return sorted(out, key=lambda x: x["price"])


# ---------- Hotels ----------
class AmadeusHotelProvider(BaseProvider):
    name = "amadeus_hotel"

    def __init__(self) -> None:
        self.fallback = MockHotelProvider()
        if not all(_creds()):
            logger.warning(
                "AMADEUS_API_KEY/SECRET not set; AmadeusHotelProvider will fail and fall back"
            )

    async def fetch(
        self,
        *,
        city: str,
        checkin: str,
        checkout: str,
        pax: int = 2,
        theme: Optional[str] = None,
        **_: Any,
    ) -> List[dict]:
        nights = max(1, _nights(checkin, checkout))
        kid_theme = bool(theme and "亲子" in theme)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            token = await _get_access_token(http)
            city_code = await _resolve_iata(http, token, city)

            # Step 1: list of hotel IDs for the city.
            r1 = await http.get(
                f"{_base_url()}/v1/reference-data/locations/hotels/by-city",
                headers={"Authorization": f"Bearer {token}"},
                params={"cityCode": city_code, "radius": 20, "radiusUnit": "KM"},
            )
            r1.raise_for_status()
            hotels_meta = (r1.json().get("data") or [])[:25]
            hotel_ids = [h["hotelId"] for h in hotels_meta if h.get("hotelId")][:20]
            meta_by_id = {h["hotelId"]: h for h in hotels_meta if h.get("hotelId")}
            if not hotel_ids:
                return []

            # Step 2: priced offers for those hotels.
            r2 = await http.get(
                f"{_base_url()}/v3/shopping/hotel-offers",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "hotelIds": ",".join(hotel_ids),
                    "checkInDate": checkin,
                    "checkOutDate": checkout,
                    "adults": max(1, int(pax)),
                    "currency": "CNY",
                    "bestRateOnly": "true",
                },
            )
            r2.raise_for_status()
            offers_body = r2.json().get("data") or []

        out: list[dict] = []
        for entry in offers_body:
            hotel = entry.get("hotel") or {}
            offers = entry.get("offers") or []
            if not offers:
                continue
            offer = offers[0]
            try:
                total = float((offer.get("price") or {}).get("total", 0))
            except (TypeError, ValueError):
                total = 0.0
            if total <= 0:
                continue
            per_night = round(total / nights, 0)

            geo = meta_by_id.get(hotel.get("hotelId"), {}).get("geoCode") or {}
            try:
                lng = float(geo.get("longitude")) if geo.get("longitude") is not None else 0.0
                lat = float(geo.get("latitude")) if geo.get("latitude") is not None else 0.0
            except (TypeError, ValueError):
                lng, lat = 0.0, 0.0

            address_lines = ((hotel.get("address") or {}).get("lines") or [])
            area = address_lines[0] if address_lines else (hotel.get("cityCode") or "市中心")

            out.append({
                "name": hotel.get("name") or "Unnamed Hotel",
                "area": area,
                "price_per_night": per_night,
                "rating": 4.0,  # Amadeus offers payload does not include star ratings consistently.
                "kid_friendly": kid_theme,
                "image_url": None,
                "lng": lng,
                "lat": lat,
            })
        # Cheaper, then by name to keep ordering stable.
        return sorted(out, key=lambda x: (x["price_per_night"], x["name"]))


def _nights(checkin: str, checkout: str) -> int:
    from datetime import datetime
    try:
        a = datetime.strptime(checkin, "%Y-%m-%d")
        b = datetime.strptime(checkout, "%Y-%m-%d")
        return max(1, (b - a).days)
    except (TypeError, ValueError):
        return 1
