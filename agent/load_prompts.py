"""Load prompt templates from prompt/prompts.yaml and render them.

We use a manual {var} substitution rather than ``str.format`` because the
templates contain literal JSON braces that would otherwise be misinterpreted.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

import yaml

_PROMPT_FILE = Path(__file__).parents[1] / "prompt" / "prompts.yaml"
_cache: Dict[str, Any] | None = None
_VAR_RE = re.compile(r"\{(\w+)\}")


def _load() -> Dict[str, Any]:
    global _cache
    if _cache is None:
        with open(_PROMPT_FILE, "r", encoding="utf-8") as f:
            _cache = yaml.safe_load(f) or {}
    return _cache


def _stringify(v: Any) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


def _substitute(template: str, kwargs: Dict[str, Any]) -> str:
    """Replace ``{name}`` only when ``name`` is in ``kwargs``; leave other braces intact."""

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key in kwargs:
            return _stringify(kwargs[key])
        return m.group(0)

    return _VAR_RE.sub(repl, template)


def render(name: str, **kwargs: Any) -> str:
    """Return ``system + user`` joined; only known {var} placeholders get substituted."""
    cfg = _load().get(name)
    if not cfg:
        raise KeyError(f"prompt '{name}' not found")
    system = (cfg.get("system") or "").strip()
    user = _substitute(cfg.get("user") or "", kwargs).strip()
    return f"{system}\n\n{user}".strip()
