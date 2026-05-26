"""Cross-cutting runtime infrastructure.

This package is the *leaf* of the dependency graph: it depends only on stdlib
and 3rd-party libraries, never on ``agent``, ``api``, ``services``, ``tools``
or ``domain``. Every other package is free to import from here without risk
of circular dependencies.

Modules:
  - ``logger``       Loguru sink configuration (singleton ``logger``).
  - ``context``      ``ContextVar``-based per-coroutine session isolation.
  - ``monitor``      Process-wide ``ToolMonitor`` singleton; reverse-pushes
                     events to the active WebSocket via the bound manager.
  - ``llm``          ``MockLLM`` / ``RealLLM`` + ``build_llm()`` factory.
  - ``checkpointer`` ``InMemorySaver`` singleton factory shared by both graphs.
  - ``prompts``      YAML prompt loader with safe ``{var}`` substitution.
"""
