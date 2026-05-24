"""LLM agents: parse_intent, plan_itinerary, review_plan, parse_refine_intent.

These four agents are called by LangGraph nodes to interact with the LLM.
Each agent has its own LLM instance.
"""
from __future__ import annotations

from typing import Any, Dict, List

from api.logger import logger
from agent import load_prompts
from agent.llm import build_llm
from models.refine import DIRTY_MAP


# Four independent LLM instances, one per agent
_llm_parse_intent = build_llm()
_llm_plan_itinerary = build_llm()
_llm_review_plan = build_llm()
_llm_parse_refine_intent = build_llm()


# ============================================================
#  parse_intent
# ============================================================
async def parse_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    bot_input = state.get("bot_user_input") or ""
    if not bot_input.strip():
        return {"parsed_intent": {}, "constraints": {}}

    prompt = load_prompts.render("parse_intent", bot_user_input=bot_input)
    try:
        intent = await _llm_parse_intent.chat_json(prompt)
    except Exception as e:
        logger.warning(f"parse_intent LLM failed: {e}")
        intent = {}

    constraints: Dict[str, Any] = {}
    if intent.get("budget_per_person"):
        constraints["budget_per_person"] = intent["budget_per_person"]
    if intent.get("pace"):
        constraints["pace"] = intent["pace"]
    if intent.get("with_kids"):
        constraints["with_kids"] = True
    if intent.get("avoid"):
        constraints["avoid"] = intent["avoid"]

    return {
        "parsed_intent": intent,
        "constraints": constraints,
    }


# ============================================================
#  plan_itinerary
# ============================================================
async def plan_itinerary(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt = load_prompts.render(
        "plan_itinerary",
        days_num=state["days_num"],
        destination=state["destination"],
        people_num=state["people_num"],
        travel_theme=state.get("travel_theme") or "通用",
        weather=state.get("weather") or [],
        pois_clustered=state.get("pois_clustered") or {},
        constraints=state.get("constraints") or {},
    )

    try:
        out = await _llm_plan_itinerary.chat_json(prompt)
        itinerary = out.get("itinerary") or []
        tips = out.get("tips") or []
    except Exception as e:
        logger.warning(f"plan_itinerary LLM failed: {e}")
        itinerary = []
        tips = []

    return {
        "itinerary": itinerary,
        "tips": tips,
    }


# ============================================================
#  review_plan
# ============================================================
async def review_plan(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt = load_prompts.render(
        "review_plan",
        itinerary=state.get("itinerary") or [],
        weather=state.get("weather") or [],
        travel_theme=state.get("travel_theme") or "通用",
        budget=state.get("budget") or {},
    )
    try:
        out = await _llm_review_plan.chat_json(prompt)
    except Exception as e:
        logger.warning(f"review_plan LLM failed: {e}")
        out = {"passed": True, "issues": [], "suggestions": []}

    passed = bool(out.get("passed", True))
    feedback_parts = []
    if out.get("issues"):
        feedback_parts.append("issues: " + "; ".join(out["issues"]))
    if out.get("suggestions"):
        feedback_parts.append("suggestions: " + "; ".join(out["suggestions"]))
    feedback = " | ".join(feedback_parts)

    return {
        "review_passed": passed,
        "review_feedback": feedback,
    }


# ============================================================
#  parse_refine_intent
# ============================================================
async def parse_refine_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    request = state.get("refine_request") or ""
    summary = _itinerary_summary(state.get("itinerary") or [])
    prompt = load_prompts.render(
        "parse_refine_intent",
        days_num=state.get("days_num", 0),
        itinerary_summary=summary,
        refine_request=request,
    )
    try:
        intent = await _llm_parse_refine_intent.chat_json(prompt)
        if not isinstance(intent, dict) or not intent.get("type"):
            intent = {"type": "freeform", "targets": [], "payload": {"free_text": request}}
    except Exception as e:
        logger.warning(f"parse_refine_intent LLM failed: {e}; using freeform")
        intent = {"type": "freeform", "targets": [], "payload": {"free_text": request}}

    dirty = DIRTY_MAP.get(intent["type"], DIRTY_MAP["freeform"])
    return {
        "refine_intent": intent,
        "dirty_nodes": set(dirty),
    }


def _itinerary_summary(itinerary: List[Dict[str, Any]]) -> str:
    if not itinerary:
        return "(empty)"
    parts: List[str] = []
    for d in itinerary[:7]:
        slots = "、".join(s.get("poi", "") for s in d.get("slots", [])[:4])
        parts.append(f"D{d.get('day_index')}: {slots}")
    return " | ".join(parts)
