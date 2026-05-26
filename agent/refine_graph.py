"""Refine graph.

Topology:

  load_previous_state → parse_refine_intent
                            │
                            ├── (any of fetch_*) ─→ join → plan_itinerary
                            └── (or skip)        ─→         + generators
                                                     │
                                       estimate_budget → review_plan_lite
                                                              ↓
                                                         render_pdf → finalize
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent import nodes, refine_nodes
from core.checkpointer import get_checkpointer
from agent.state import TripState

_compiled = None


def build_refine_graph():
    global _compiled
    if _compiled is not None:
        return _compiled

    g = StateGraph(TripState)

    # entry-only nodes
    g.add_node("load_previous_state", refine_nodes.load_previous_state)
    g.add_node("parse_refine_intent", refine_nodes.parse_refine_intent)

    # reuse plan-graph nodes
    g.add_node("fetch_weather", nodes.fetch_weather)
    g.add_node("fetch_flights", nodes.fetch_flights)
    g.add_node("fetch_hotels", nodes.fetch_hotels)
    g.add_node("fetch_pois", nodes.fetch_pois)
    g.add_node("cluster_pois", nodes.cluster_pois)
    g.add_node("plan_itinerary", nodes.plan_itinerary)
    g.add_node("generate_packing_list", nodes.generate_packing_list)
    g.add_node("generate_cultural_tips", nodes.generate_cultural_tips)
    g.add_node("generate_pre_trip_checklist", nodes.generate_pre_trip_checklist)
    g.add_node("estimate_budget", nodes.estimate_budget)
    g.add_node("review_plan_lite", nodes.review_plan)  # lite = same fn, single iteration
    g.add_node("render_pdf", nodes.render_pdf)
    g.add_node("finalize", nodes.finalize)

    g.add_edge(START, "load_previous_state")
    g.add_edge("load_previous_state", "parse_refine_intent")

    # parse_refine_intent fans out to whichever fetch / generator nodes the
    # intent flagged dirty. If nothing is dirty we still rerun plan_itinerary
    # (so the user always gets a fresh plan rendered).
    g.add_conditional_edges(
        "parse_refine_intent",
        refine_nodes.dispatcher_router,
        {
            "fetch_weather": "fetch_weather",
            "fetch_flights": "fetch_flights",
            "fetch_hotels": "fetch_hotels",
            "fetch_pois": "fetch_pois",
            "plan_itinerary": "plan_itinerary",
            "generate_packing_list": "generate_packing_list",
            "generate_cultural_tips": "generate_cultural_tips",
            "generate_pre_trip_checklist": "generate_pre_trip_checklist",
        },
    )

    # fetches converge into cluster_pois → plan_itinerary
    for fetch in ("fetch_weather", "fetch_flights", "fetch_hotels"):
        g.add_edge(fetch, "plan_itinerary")
    g.add_edge("fetch_pois", "cluster_pois")
    g.add_edge("cluster_pois", "plan_itinerary")

    # All four generators (plan + 3 content nodes) converge into estimate_budget.
    g.add_edge("plan_itinerary", "estimate_budget")
    g.add_edge("generate_packing_list", "estimate_budget")
    g.add_edge("generate_cultural_tips", "estimate_budget")
    g.add_edge("generate_pre_trip_checklist", "estimate_budget")

    g.add_edge("estimate_budget", "review_plan_lite")
    g.add_edge("review_plan_lite", "render_pdf")
    g.add_edge("render_pdf", "finalize")
    g.add_edge("finalize", END)

    _compiled = g.compile(checkpointer=get_checkpointer())
    return _compiled
