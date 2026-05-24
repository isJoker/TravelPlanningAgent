"""Pydantic business models shared between tools, nodes, and PDF renderer."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class WeatherDay(BaseModel):
    date: str
    temp_high: float
    temp_low: float
    condition: str  # 晴 / 多云 / 雨 ...
    rain_prob: float = 0.0


class FlightOption(BaseModel):
    airline: str
    flight_no: str
    depart_time: str
    arrive_time: str
    duration_minutes: int
    price: float
    stops: int = 0
    direction: str = "outbound"  # outbound | return


class HotelOption(BaseModel):
    name: str
    area: str
    price_per_night: float
    rating: float
    kid_friendly: bool = False
    image_url: Optional[str] = None
    lng: float = 0.0
    lat: float = 0.0


class POI(BaseModel):
    name: str
    type: str  # 景点 / 餐厅 / 体验 / 购物
    area: str = ""
    lng: float = 0.0
    lat: float = 0.0
    rating: float = 0.0
    duration_minutes: int = 90
    ticket_price: float = 0.0
    indoor: bool = False
    suitable_for_kids: bool = True
    suggested_slot: Optional[str] = None  # morning | noon | afternoon | evening


class DaySlot(BaseModel):
    slot: str  # 上午 / 中午 / 下午 / 晚上
    poi: str
    type: str
    note: Optional[str] = None


class DayPlan(BaseModel):
    day_index: int
    date: str
    weather_summary: Optional[str] = None
    area: Optional[str] = None
    slots: List[DaySlot] = Field(default_factory=list)


class BudgetBreakdown(BaseModel):
    currency: str = "CNY"
    flights: float = 0.0
    hotels: float = 0.0
    pois: float = 0.0
    meals: float = 0.0
    transport: float = 0.0
    total: float = 0.0
    per_person: float = 0.0


class ErrorRecord(BaseModel):
    where: str
    message: str


class VersionMeta(BaseModel):
    version: int
    created_at: str
    summary: Optional[str] = None
