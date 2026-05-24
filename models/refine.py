"""Structured RefineIntent for multi-turn adjustments."""
from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

RefineType = Literal[
    "swap_poi",
    "rework_day",
    "change_hotel",
    "change_flight",
    "change_pace",
    "change_theme",
    "change_budget",
    "extend_days",
    "freeform",
]

# RefineType -> set of plan-graph node names that must be re-run.
DIRTY_MAP: Dict[str, set[str]] = {
    "swap_poi": {"plan_itinerary"},
    "rework_day": {"plan_itinerary"},
    "change_hotel": {"fetch_hotels", "plan_itinerary"},
    "change_flight": {"fetch_flights"},
    "change_pace": {"plan_itinerary"},
    "change_theme": {"fetch_pois", "cluster_pois", "plan_itinerary"},
    "change_budget": {"fetch_hotels", "plan_itinerary"},
    "extend_days": {
        "fetch_weather",
        "fetch_flights",
        "fetch_hotels",
        "fetch_pois",
        "cluster_pois",
        "plan_itinerary",
    },
    "freeform": {"plan_itinerary"},
}


class RefineIntent(BaseModel):
    type: RefineType = "freeform"
    targets: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
