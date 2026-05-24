"""Refine-graph nodes.

Refine reuses the plan-graph's fetch / cluster / plan nodes via re-import; only
the entry, intent parser, and dispatcher are refine-specific.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, List

from api.logger import logger
from api.monitor import monitor
from agent import load_prompts
from agent.checkpointer import get_checkpointer
from agent.llm import build_llm
from models.refine import DIRTY_MAP


def _timed(node_name: str):
    def deco(fn: Callable[..., Awaitable[Dict[str, Any]]]):
        async def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            monitor.report_node_start(node_name)
            t0 = time.perf_counter()
            try:
                out = await fn(state)
            except Exception as e:
                monitor.report_error(node_name, str(e))
                raise
            duration = (time.perf_counter() - t0) * 1000
            summary = out.pop("_summary", None) if isinstance(out, dict) else None
            monitor.report_node_end(node_name, duration, summary)
            return out or {}
        wrapper.__name__ = node_name
        return wrapper
    return deco


# ============================================================
#  load_previous_state
# ============================================================
@_timed("load_previous_state")
async def load_previous_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Load the latest checkpointed TripState for this thread_id.

    LangGraph automatically runs the graph against the latest snapshot when
    we invoke with the same thread_id, but we still need to ensure the
    ``refine_request`` field from the new invocation is merged onto the old
    state. Returning an empty patch is enough — InMemorySaver merges.

    LangGraph 1.0 exposes ``aget_tuple(config) -> CheckpointTuple | None``
    as the recommended async API for inspecting a saved checkpoint; the
    ``CheckpointTuple.checkpoint`` field carries the channel values.
    """
    saver = get_checkpointer()
    config = {"configurable": {"thread_id": state.get("conversation_name", "")}}
    try:
        snap = await saver.aget_tuple(config)
    except Exception as e:  # pragma: no cover
        logger.warning(f"load_previous_state: aget_tuple() failed: {e}")
        snap = None

    prev_version = 1
    if snap is not None:
        # CheckpointTuple in LangGraph 1.0: dataclass-like with a .checkpoint
        # attribute (a Checkpoint TypedDict) that holds channel_values. We
        # also defensively support the legacy shape where snap itself is the
        # checkpoint dict.
        try:
            checkpoint = getattr(snap, "checkpoint", None)
            if checkpoint is None and isinstance(snap, dict):
                checkpoint = snap
            channel_values = (checkpoint or {}).get("channel_values", {}) or {}
        except Exception:
            channel_values = {}
        prev_version = int(channel_values.get("version", 1))

    new_version = prev_version + 1
    return {
        "version": new_version,
        "retry_count": 0,
        "_summary": f"加载 v{prev_version} → 计划生成 v{new_version}",
    }


# ============================================================
#  parse_refine_intent
# ============================================================
@_timed("parse_refine_intent")
async def parse_refine_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    request = state.get("refine_request") or ""
    summary = _itinerary_summary(state.get("itinerary") or [])
    llm = build_llm()
    prompt = load_prompts.render(
        "parse_refine_intent",
        days_num=state.get("days_num", 0),
        itinerary_summary=summary,
        refine_request=request,
    )
    try:
        intent = await llm.chat_json(prompt)
        if not isinstance(intent, dict) or not intent.get("type"):
            intent = {"type": "freeform", "targets": [], "payload": {"free_text": request}}
    except Exception as e:
        logger.warning(f"parse_refine_intent LLM failed: {e}; using freeform")
        intent = {"type": "freeform", "targets": [], "payload": {"free_text": request}}

    dirty = DIRTY_MAP.get(intent["type"], DIRTY_MAP["freeform"])
    return {
        "refine_intent": intent,
        "dirty_nodes": set(dirty),
        "_summary": f"intent={intent['type']} dirty={sorted(dirty)}",
    }


def _itinerary_summary(itinerary: List[Dict[str, Any]]) -> str:
    if not itinerary:
        return "(empty)"
    parts: List[str] = []
    for d in itinerary[:7]:
        slots = "、".join(s.get("poi", "") for s in d.get("slots", [])[:4])
        parts.append(f"D{d.get('day_index')}: {slots}")
    return " | ".join(parts)


# ============================================================
#  route_refine_dispatcher  (decides which fetch nodes to run)
# ============================================================
@_timed("route_refine_dispatcher")
async def route_refine_dispatcher(state: Dict[str, Any]) -> Dict[str, Any]:
    dirty = state.get("dirty_nodes") or set()
    return {"_summary": f"派发：{sorted(dirty)}"}


def dispatcher_router(state: Dict[str, Any]) -> List[str]:
    """Return the next-hop node list. LangGraph supports list outputs for fan-out."""
    dirty = state.get("dirty_nodes") or set()
    next_nodes: List[str] = []
    if "fetch_weather" in dirty:
        next_nodes.append("fetch_weather")
    if "fetch_flights" in dirty:
        next_nodes.append("fetch_flights")
    if "fetch_hotels" in dirty:
        next_nodes.append("fetch_hotels")
    if "fetch_pois" in dirty:
        next_nodes.append("fetch_pois")
    if not next_nodes:
        # No fetches needed: jump straight to plan_itinerary.
        return ["plan_itinerary"]
    return next_nodes
