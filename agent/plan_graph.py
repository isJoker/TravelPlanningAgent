"""Plan graph: validate → parse_intent → 4-way fan-out → cluster → plan → review (loop) → render → finalize."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent import nodes
from agent.checkpointer import get_checkpointer
from agent.state import TripState

_compiled = None


def build_plan_graph():
    global _compiled
    if _compiled is not None:
        return _compiled

    g = StateGraph(TripState)

    g.add_node("validate_input", nodes.validate_input)
    g.add_node("parse_intent", nodes.parse_intent)
    g.add_node("fetch_weather", nodes.fetch_weather)
    g.add_node("fetch_flights", nodes.fetch_flights)
    g.add_node("fetch_hotels", nodes.fetch_hotels)
    g.add_node("fetch_pois", nodes.fetch_pois)
    g.add_node("cluster_pois", nodes.cluster_pois)
    g.add_node("plan_itinerary", nodes.plan_itinerary)
    g.add_node("estimate_budget", nodes.estimate_budget)
    g.add_node("review_plan", nodes.review_plan)
    g.add_node("render_pdf", nodes.render_pdf)
    g.add_node("finalize", nodes.finalize)

    g.add_edge(START, "validate_input")
    g.add_edge("validate_input", "parse_intent")

    # Fan-out 4 fetchers in parallel from parse_intent, then join at cluster_pois.
    for fetch in ("fetch_weather", "fetch_flights", "fetch_hotels", "fetch_pois"):
        g.add_edge("parse_intent", fetch)
        g.add_edge(fetch, "cluster_pois")

    g.add_edge("cluster_pois", "plan_itinerary")
    g.add_edge("plan_itinerary", "estimate_budget")
    g.add_edge("estimate_budget", "review_plan")

    g.add_conditional_edges(
        "review_plan",
        nodes.review_router,
        {"plan_itinerary": "plan_itinerary", "render_pdf": "render_pdf"},
    )
    g.add_edge("render_pdf", "finalize")
    g.add_edge("finalize", END)

    _compiled = g.compile(checkpointer=get_checkpointer())
    return _compiled
