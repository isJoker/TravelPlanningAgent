"""Async entry point for refine (multi-turn adjustment)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from core.context import (
    reset_session_context,
    set_session_context,
    set_thread_context,
)
from core.logger import logger
from core.monitor import monitor
from agent.refine_graph import build_refine_graph
from agent.refine_nodes import RefineStateMissingError

PROJECT_ROOT = Path(__file__).parents[1].resolve()
OUTPUT_DIR = PROJECT_ROOT / "output"


async def run_refine_agent(instruction: str, thread_id: str, *, trip_id: str | None = None) -> None:
    session_dir = OUTPUT_DIR / f"session_{thread_id}"
    if not session_dir.exists():
        # No prior session — caller should retry as a plan. We surface an error.
        monitor.report_error(
            "refine",
            f"会话 {thread_id} 已过期 (InMemorySaver 不持久化跨进程 state)。请重新生成行程。",
        )
        return

    s_token = set_session_context(str(session_dir))
    t_token = set_thread_context(thread_id)
    monitor.report_session_dir(str(session_dir))

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    graph = build_refine_graph()

    # Patch the existing state with the new refine_request; LangGraph merges with checkpoint.
    patch: Dict[str, Any] = {"refine_request": instruction}

    try:
        logger.info(f"[refine] start thread_id={thread_id} trip_id={trip_id}")
        await graph.ainvoke(patch, config=config)
        logger.info(f"[refine] done thread_id={thread_id}")
    except RefineStateMissingError as e:
        # The user-facing event is already published from the node; just log here.
        logger.warning(f"[refine] state missing thread_id={thread_id}: {e}")
    except Exception as e:
        logger.exception(f"[refine] failed thread_id={thread_id}: {e}")
        monitor.report_error("refine_graph", str(e))
    finally:
        reset_session_context(s_token, t_token)
