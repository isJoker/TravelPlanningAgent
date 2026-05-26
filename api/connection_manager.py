"""WebSocket connection manager keyed by thread_id.

Stores at most one active websocket per thread_id and exposes a
coroutine to send a payload to a specific thread. Background coroutines
running outside the request scope can use:

    asyncio.run_coroutine_threadsafe(
        manager.send_to_thread(payload, thread_id),
        manager.loop,
    )

to push events from any depth back to the right client.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import WebSocket

from core.logger import logger


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, WebSocket] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def connect(self, websocket: WebSocket, thread_id: str) -> None:
        await websocket.accept()
        # Replace any existing connection for the same thread_id (e.g. page reload).
        old = self.active_connections.get(thread_id)
        if old is not None:
            try:
                await old.close()
            except Exception:  # pragma: no cover
                pass
        self.active_connections[thread_id] = websocket
        logger.info(f"[WS] connected thread_id={thread_id}, total={len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket, thread_id: str) -> None:
        cur = self.active_connections.get(thread_id)
        if cur is websocket:
            self.active_connections.pop(thread_id, None)
        logger.info(f"[WS] disconnected thread_id={thread_id}, total={len(self.active_connections)}")

    async def send_to_thread(self, payload: Dict[str, Any], thread_id: str) -> None:
        ws = self.active_connections.get(thread_id)
        if ws is None:
            # Not necessarily an error: client may not have connected yet.
            logger.debug(f"[WS] no active connection for thread_id={thread_id}")
            return
        try:
            await ws.send_json(payload)
        except Exception as e:
            logger.warning(f"[WS] send failed thread_id={thread_id}: {e}")
            # Drop a broken connection to avoid spamming logs.
            self.active_connections.pop(thread_id, None)
