"""LLM agents: parse_intent, plan_itinerary, review_plan, parse_refine_intent.

Each agent calls the LLM through the process-wide singleton returned by
``build_llm()``. Splitting them into separate variables would be misleading
(``build_llm`` caches a single instance), so we use one shared handle here
and let prompt rendering be the differentiator.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.logger import logger
from core import prompts
from core.llm import build_llm
from domain.refine import DIRTY_MAP


# Single shared LLM handle (build_llm caches a singleton).
_llm = build_llm()


# ============================================================
#  parse_intent
# ============================================================
async def parse_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    bot_input = state.get("bot_user_input") or ""
    if not bot_input.strip():
        return {"parsed_intent": {}, "constraints": {}}

    prompt = prompts.render("parse_intent", bot_user_input=bot_input)
    try:
        intent = await _llm.chat_json(prompt)
    except Exception as e:
        logger.warning(f"parse_intent LLM failed: {e}")
        intent = {}

    constraints: Dict[str, Any] = {}
    if intent.get("budget_per_person"):
        constraints["budget_per_person"] = intent["budget_per_person"]
    if intent.get("budget_level"):
        constraints["budget_level"] = intent["budget_level"]
    if intent.get("pace"):
        constraints["pace"] = intent["pace"]
    if intent.get("with_kids"):
        constraints["with_kids"] = True
    if intent.get("with_elder"):
        constraints["with_elder"] = True
    if intent.get("avoid"):
        constraints["avoid"] = intent["avoid"]
    if intent.get("must_visit"):
        constraints["must_visit"] = intent["must_visit"]
    if intent.get("interests"):
        constraints["interests"] = intent["interests"]
    if intent.get("diet"):
        constraints["diet"] = intent["diet"]

    return {
        "parsed_intent": intent,
        "constraints": constraints,
    }


# ============================================================
#  plan_itinerary
# ============================================================
async def plan_itinerary(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt = prompts.render(
        "plan_itinerary",
        days_num=state["days_num"],
        destination=state["destination"],
        departure=state.get("departure") or "—",
        people_num=state["people_num"],
        date_range=state.get("date_range") or [],
        travel_theme=state.get("travel_theme") or "通用",
        weather=state.get("weather") or [],
        pois_clustered=state.get("pois_clustered") or {},
        constraints=state.get("constraints") or {},
    )

    try:
        out = await _llm.chat_json(prompt)
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
#  generate_packing_list
# ============================================================
async def generate_packing_list(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt = prompts.render(
        "pack_list",
        destination=state["destination"],
        date_range=state.get("date_range") or [],
        weather=state.get("weather") or [],
        travel_theme=state.get("travel_theme") or "通用",
        constraints=state.get("constraints") or {},
        days_num=state["days_num"],
        people_num=state["people_num"],
    )
    try:
        out = await _llm.chat_json(prompt)
    except Exception as e:
        logger.warning(f"generate_packing_list LLM failed: {e}")
        out = {}
    if not isinstance(out, dict):
        out = {}
    # Normalise: every category is a list, even when LLM returns a string by mistake.
    keys = ("essentials", "clothing", "toiletries", "electronics", "health", "activities", "misc")
    return {"packing_list": {k: list(out.get(k) or []) for k in keys}}


# ============================================================
#  generate_cultural_tips
# ============================================================
async def generate_cultural_tips(state: Dict[str, Any]) -> Dict[str, Any]:
    constraints = state.get("constraints") or {}
    prompt = prompts.render(
        "cultural_tips",
        destination=state["destination"],
        travel_theme=state.get("travel_theme") or "通用",
        with_kids=constraints.get("with_kids", False),
        constraints=constraints,
    )
    try:
        out = await _llm.chat_json(prompt)
    except Exception as e:
        logger.warning(f"generate_cultural_tips LLM failed: {e}")
        out = {}
    if not isinstance(out, dict):
        out = {}
    out.setdefault("dos", [])
    out.setdefault("donts", [])
    out.setdefault("dining", {})
    out.setdefault("religious_sites", [])
    out.setdefault("safety", {})
    out.setdefault("useful_phrases", [])
    return {"cultural_tips": out}


# ============================================================
#  generate_pre_trip_checklist
# ============================================================
async def generate_pre_trip_checklist(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt = prompts.render(
        "pre_trip_checklist",
        destination=state["destination"],
        start_date=state.get("start_date") or "",
        days_num=state["days_num"],
        people_num=state["people_num"],
        travel_theme=state.get("travel_theme") or "通用",
        constraints=state.get("constraints") or {},
    )
    try:
        out = await _llm.chat_json(prompt)
    except Exception as e:
        logger.warning(f"generate_pre_trip_checklist LLM failed: {e}")
        out = {}
    checklist = (out or {}).get("checklist") or []
    if not isinstance(checklist, list):
        checklist = []
    return {"pre_trip_checklist": checklist}


# ============================================================
#  review_plan
# ============================================================
async def review_plan(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt = prompts.render(
        "review_plan",
        itinerary=state.get("itinerary") or [],
        weather=state.get("weather") or [],
        travel_theme=state.get("travel_theme") or "通用",
        budget=state.get("budget") or {},
    )
    try:
        out = await _llm.chat_json(prompt)
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
    prompt = prompts.render(
        "parse_refine_intent",
        days_num=state.get("days_num", 0),
        itinerary_summary=summary,
        refine_request=request,
    )
    try:
        intent = await _llm.chat_json(prompt)
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
