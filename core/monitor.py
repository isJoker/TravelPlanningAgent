"""Singleton ToolMonitor.

Any node / tool can call ``monitor.report_*`` to push a structured event to
the websocket of the currently running thread. The monitor reads thread_id
from ContextVar and dispatches to the connection manager via
``asyncio.run_coroutine_threadsafe`` so it works from sync code too.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from core.context import get_thread_id
from core.logger import logger


class ToolMonitor:
    def __init__(self) -> None:
        self._manager = None  # set during FastAPI startup

    def set_websocket_manager(self, manager) -> None:
        self._manager = manager

    # ----- internal -----
    def _push(self, payload: Dict[str, Any]) -> None:
        thread_id = get_thread_id()
        if not thread_id:
            logger.debug(f"[Monitor] no thread_id in context, dropping event {payload.get('event')}")
            return
        if self._manager is None:
            logger.debug("[Monitor] websocket manager not bound yet")
            return
        loop = self._manager.loop
        if loop is None:
            logger.debug("[Monitor] event loop not bound")
            return
        coro = self._manager.send_to_thread(payload, thread_id)
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[Monitor] dispatch failed: {e}")

    @staticmethod
    def _now() -> float:
        return time.time()

    # ----- public event API -----
    def report_session_dir(self, path: str) -> None:
        self._push({"event": "session_created", "data": {"path": path}})

    def report_node_start(self, node: str) -> None:
        self._push({"event": "node_start", "data": {"node": node, "ts": self._now()}})

    def report_node_end(self, node: str, duration_ms: float, summary: Optional[str] = None) -> None:
        self._push(
            {
                "event": "node_end",
                "data": {"node": node, "duration_ms": round(duration_ms, 2), "summary": summary},
            }
        )

    def report_tool_start(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> None:
        self._push({"event": "tool_start", "data": {"tool_name": tool_name, "args": args or {}}})

    def report_tool_end(self, tool_name: str, summary: Optional[str] = None) -> None:
        self._push({"event": "tool_end", "data": {"tool_name": tool_name, "summary": summary}})

    def report_review(self, iteration: int, passed: bool, feedback: Optional[str] = None) -> None:
        self._push(
            {
                "event": "review_iteration",
                "data": {"iteration": iteration, "passed": passed, "feedback": feedback},
            }
        )

    def report_partial_thought(self, text: str) -> None:
        self._push({"event": "partial_thought", "data": {"text": text}})

    def report_task_result(
        self,
        result: str,
        version: int,
        files: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        self._push(
            {
                "event": "task_result",
                "data": {"result": result, "version": version, "files": files or []},
            }
        )

    def report_error(self, where: str, message: str) -> None:
        self._push({"event": "error", "data": {"where": where, "message": message}})


# Singleton
monitor = ToolMonitor()
