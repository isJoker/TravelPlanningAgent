"""TripState — the LangGraph shared state for both plan_graph and refine_graph."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def _set_union(a: set, b: set) -> set:
    return (a or set()) | (b or set())


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
    tips: List[str]
    summary: str

    # ===== review =====
    review_passed: bool
    review_feedback: str
    retry_count: int

    # ===== refine =====
    version: int
    history: Annotated[List[Dict[str, Any]], operator.add]
    refine_request: str
    refine_intent: Dict[str, Any]
    dirty_nodes: Annotated[set, _set_union]

    # ===== output =====
    pdf_path: str
    md_path: str
    files: Annotated[List[Dict[str, Any]], operator.add]
    errors: Annotated[List[Dict[str, Any]], operator.add]
