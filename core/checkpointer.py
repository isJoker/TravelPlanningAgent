"""Process-wide singleton InMemorySaver.

Per the v0.3 design, we deliberately use the in-memory checkpointer to keep
the demo dependency-free. A SqliteSaver / PostgresSaver swap is a one-liner
when persistence is needed.

In LangGraph 1.0, ``InMemorySaver`` is the canonical in-process checkpointer
and lives at ``langgraph.checkpoint.memory.InMemorySaver``.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

_saver: InMemorySaver | None = None


def get_checkpointer() -> InMemorySaver:
    global _saver
    if _saver is None:
        _saver = InMemorySaver()
    return _saver
