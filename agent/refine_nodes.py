"""Refine-graph nodes.

Refine reuses the plan-graph's fetch / cluster / plan nodes via re-import; only
the entry, intent parser, and dispatcher are refine-specific.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.checkpointer import get_checkpointer
from core.logger import logger
from agent import agents
from agent._timed import timed as _timed


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
    result = await agents.parse_refine_intent(state)
    intent = result.get("refine_intent", {})
    dirty = result.get("dirty_nodes", set())
    return {
        "refine_intent": intent,
        "dirty_nodes": dirty,
        "_summary": f"intent={intent.get('type', 'freeform')} dirty={sorted(dirty)}",
    }


# ============================================================
#  dispatcher_router  (LangGraph conditional-edge function)
# ============================================================
def dispatcher_router(state: Dict[str, Any]) -> List[str]:
    """Decide which fetch nodes to re-run based on ``dirty_nodes``.

    Returning a list of node names lets LangGraph fan out to all of them in
    parallel. If nothing needs to be re-fetched we jump straight to
    ``plan_itinerary``.
    """
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
        return ["plan_itinerary"]
    return next_nodes
