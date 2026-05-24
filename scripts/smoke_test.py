"""End-to-end smoke test running the plan_graph directly (no HTTP/WS).

Usage:
    PYTHONPATH=. python scripts/smoke_test.py

Ensures imports work, the graph compiles, and a Mock-mode plan completes
producing a Markdown report on disk.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Default to fully offline mock mode unless explicitly overridden.
os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("USE_MOCK_TOOLS", "true")

from agent.plan_agent import run_plan_agent  # noqa: E402
from agent.refine_agent import run_refine_agent  # noqa: E402


async def main() -> int:
    payload = {
        "conversation_name": "smoke-osaka",
        "bot_user_input": "想带 3 岁小孩，避免长途车程，预算每人 8000 元",
        "destination": "大阪",
        "departure": "上海",
        "days_num": 3,
        "people_num": 3,
        "start_date": "2026-07-15",
        "travel_theme": "亲子",
    }

    print("[smoke] running plan agent…")
    await run_plan_agent(payload, thread_id=payload["conversation_name"], trip_id="trp_smoke")

    out_dir = ROOT / "output" / f"session_{payload['conversation_name']}"
    print(f"[smoke] output dir: {out_dir}")
    if not out_dir.exists():
        print("[smoke] ❌ output dir not created")
        return 1

    files = sorted(p.name for p in out_dir.iterdir())
    print(f"[smoke] files: {files}")
    md_files = [f for f in files if f.endswith(".md")]
    if not md_files:
        print("[smoke] ❌ no markdown report produced")
        return 1
    md_path = out_dir / md_files[-1]
    md_text = md_path.read_text(encoding="utf-8")
    print(f"[smoke] {md_path.name} length={len(md_text)} chars, head:")
    print("\n".join(md_text.splitlines()[:10]))

    print("\n[smoke] running refine agent…")
    await run_refine_agent(
        instruction="把第3天改成室内活动，酒店换成离心斋桥近的",
        thread_id=payload["conversation_name"],
        trip_id="trp_refine",
    )
    files_after = sorted(p.name for p in out_dir.iterdir())
    new_files = sorted(set(files_after) - set(files))
    print(f"[smoke] new files: {new_files}")
    if not any(f.endswith(".md") and "v2" in f for f in new_files):
        print("[smoke] ❌ refine did not produce v2 markdown")
        return 1

    print("\n[smoke] ✅ pass")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
