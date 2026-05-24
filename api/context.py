"""ContextVar-based session isolation.

Used so that any tool / node deep in the call stack can read the current
session_dir and thread_id without parameter threading. Each asyncio task
gets its own ContextVar view, which is the basis of our multi-user safety.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_session_dir_ctx: ContextVar[Optional[str]] = ContextVar("session_dir", default=None)
_thread_id_ctx: ContextVar[Optional[str]] = ContextVar("thread_id", default=None)


def set_session_context(path: str) -> Token:
    return _session_dir_ctx.set(path)


def set_thread_context(thread_id: str) -> Token:
    return _thread_id_ctx.set(thread_id)


def get_session_dir() -> Optional[str]:
    return _session_dir_ctx.get()


def get_thread_id() -> Optional[str]:
    return _thread_id_ctx.get()


def reset_session_context(session_token: Token, thread_token: Token) -> None:
    _session_dir_ctx.reset(session_token)
    _thread_id_ctx.reset(thread_token)
