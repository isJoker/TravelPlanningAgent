"""Refine-graph nodes.

Refine reuses the plan-graph's fetch / cluster / plan nodes via re-import; only
the entry, intent parser, and dispatcher are refine-specific.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.checkpointer import get_checkpointer
from core.logger import logger
from core.monitor import monitor
from agent import agents
from agent._timed import timed as _timed


class RefineStateMissingError(RuntimeError):
    """Raised when the saver has no checkpoint for the requested thread_id.

    Most commonly this happens after a process restart: ``InMemorySaver`` is
    in-process and does not persist across runs, so a previously-finished
    plan is gone even though its files remain on disk. We surface this so
    the API layer can tell the user to start a new plan rather than
    silently failing deep inside ``plan_itinerary``.
    """


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

    channel_values: Dict[str, Any] = {}
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

    # Detect a missing/stale state — InMemorySaver is process-local, so a
    # surviving session_dir on disk does not imply we still have the plan
    # state. Without ``destination`` / ``days_num`` the downstream nodes
    # would KeyError; surface a clean message instead.
    if not channel_values.get("destination") or not channel_values.get("days_num"):
        msg = (
            "会话状态已丢失（InMemorySaver 是进程内存储，重启后不保留 state）。"
            "请重新发起一次完整规划，再做调整。"
        )
        monitor.report_error("load_previous_state", msg)
        raise RefineStateMissingError(msg)

    prev_version = int(channel_values.get("version", 1))
    new_version = prev_version + 1
    return {
        "version": new_version,
        "retry_count": 0,
        # Reset the review pass flag so review_plan_lite is treated as a
        # fresh check (the previous run will have left ``review_passed=True``).
        "review_passed": False,
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
    """Decide which fetch / generator nodes to re-run based on ``dirty_nodes``.

    Returning a list of node names lets LangGraph fan out to all of them in
    parallel. If nothing in the dirty set is a fetch or a generator, we fall
    back to ``plan_itinerary`` (LangGraph will then converge to estimate_budget
    via the existing edges).
    """
    dirty = state.get("dirty_nodes") or set()
    next_nodes: List[str] = []
    for node in (
        "fetch_weather", "fetch_flights", "fetch_hotels", "fetch_pois",
        "generate_packing_list", "generate_cultural_tips", "generate_pre_trip_checklist",
    ):
        if node in dirty:
            next_nodes.append(node)
    if not next_nodes:
        return ["plan_itinerary"]
    return next_nodes
