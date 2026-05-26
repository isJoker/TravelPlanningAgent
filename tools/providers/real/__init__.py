"""Real (production) provider adapters.

Each adapter implements ``BaseProvider`` and normalises the upstream
response into the same schema as the corresponding mock provider, so the
upstream nodes are oblivious to the source.
"""
from tools.providers.real.amadeus import AmadeusFlightProvider, AmadeusHotelProvider
from tools.providers.real.amap import AmapPOIProvider
from tools.providers.real.openweather import OpenWeatherProvider
from tools.providers.real.qweather import QWeatherProvider

__all__ = [
    "AmadeusFlightProvider",
    "AmadeusHotelProvider",
    "AmapPOIProvider",
    "OpenWeatherProvider",
    "QWeatherProvider",
]
