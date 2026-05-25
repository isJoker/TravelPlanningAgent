"""Async entry point for first-time planning.

Bound to a single ``thread_id``. Wraps the graph invocation in a ContextVar
session so any tool / monitor call can find session_dir and thread_id.
"""
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
from agent.plan_graph import build_plan_graph

PROJECT_ROOT = Path(__file__).parents[1].resolve()
OUTPUT_DIR = PROJECT_ROOT / "output"


async def run_plan_agent(input_data: Dict[str, Any], thread_id: str, *, trip_id: str | None = None) -> None:
    session_dir = OUTPUT_DIR / f"session_{thread_id}"
    session_dir.mkdir(parents=True, exist_ok=True)

    s_token = set_session_context(str(session_dir))
    t_token = set_thread_context(thread_id)
    monitor.report_session_dir(str(session_dir))

    initial: Dict[str, Any] = dict(input_data)
    initial.setdefault("version", 1)
    initial.setdefault("retry_count", 0)
    initial["conversation_name"] = thread_id

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    graph = build_plan_graph()

    try:
        logger.info(f"[plan] start thread_id={thread_id} trip_id={trip_id}")
        await graph.ainvoke(initial, config=config)
        logger.info(f"[plan] done thread_id={thread_id}")
    except Exception as e:
        logger.exception(f"[plan] failed thread_id={thread_id}: {e}")
        monitor.report_error("plan_graph", str(e))
    finally:
        reset_session_context(s_token, t_token)
