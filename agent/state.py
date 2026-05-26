"""TripState — the LangGraph shared state for both plan_graph and refine_graph."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def _replace(_a: Any, b: Any) -> Any:
    """Reducer that overwrites the existing channel value.

    LangGraph defaults a channel without an explicit reducer to "last write
    wins", but only when the channel is written by **at most one node per
    superstep**. ``dirty_nodes`` is written exclusively by
    ``parse_refine_intent``, so a replace-style reducer is the desired
    semantics: every new refine starts from a clean slate.

    The previous ``set-union`` reducer accumulated dirty entries across
    refines (e.g. after change_hotel → change_flight, the second run would
    see ``{fetch_hotels, fetch_flights}`` and needlessly re-fetch hotels).
    """
    return b


class TripState(TypedDict, total=False):
    # ===== input =====
    conversation_name: str
    bot_user_input: str
    destination: str
    departure: Optional[str]
    days_num: int
    people_num: int
    start_date: Optional[str]
    travel_theme: Optional[str]

    # ===== parsed / intermediate =====
    parsed_intent: Dict[str, Any]
    date_range: List[str]
    constraints: Dict[str, Any]

    # ===== gathered =====
    weather: List[Dict[str, Any]]
    flights: List[Dict[str, Any]]
    hotels: List[Dict[str, Any]]
    pois: List[Dict[str, Any]]
    pois_clustered: Dict[str, List[Dict[str, Any]]]

    # ===== plan results =====
    itinerary: List[Dict[str, Any]]
    budget: Dict[str, Any]
    daily_costs: List[float]
    tips: List[str]
    summary: str
    packing_list: Dict[str, List[str]]
    cultural_tips: Dict[str, Any]
    pre_trip_checklist: List[Dict[str, Any]]

    # ===== review =====
    review_passed: bool
    review_feedback: str
    retry_count: int

    # ===== refine =====
    version: int
    history: Annotated[List[Dict[str, Any]], operator.add]
    refine_request: str
    refine_intent: Dict[str, Any]
    dirty_nodes: Annotated[set, _replace]

    # ===== output =====
    pdf_path: str
    md_path: str
    files: Annotated[List[Dict[str, Any]], operator.add]
    errors: Annotated[List[Dict[str, Any]], operator.add]
