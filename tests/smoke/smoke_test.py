"""End-to-end smoke test running the plan_graph directly (no HTTP/WS).

Usage:
    PYTHONPATH=. python tests/smoke/smoke_test.py

Ensures imports work, the graph compiles, and a Mock-mode plan completes
producing a Markdown report on disk.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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

    # ---- Verify dirty_nodes does NOT accumulate across refines (regression) ----
    from core.checkpointer import get_checkpointer

    saver = get_checkpointer()
    cfg = {"configurable": {"thread_id": payload["conversation_name"]}}

    # First refine targets hotel; second targets flight. With the old reducer
    # the second snapshot would contain {fetch_hotels, fetch_flights}; with
    # the replace-style reducer only the most-recent intent's dirty set
    # should be present.
    await run_refine_agent("换一个酒店", thread_id=payload["conversation_name"], trip_id="trp_h")
    snap = await saver.aget_tuple(cfg)
    dirty1 = (snap.checkpoint or {}).get("channel_values", {}).get("dirty_nodes") or set()
    await run_refine_agent("换一个航班", thread_id=payload["conversation_name"], trip_id="trp_f")
    snap = await saver.aget_tuple(cfg)
    dirty2 = (snap.checkpoint or {}).get("channel_values", {}).get("dirty_nodes") or set()
    print(f"[smoke] dirty after refine#hotel: {dirty1}")
    print(f"[smoke] dirty after refine#flight: {dirty2}")
    if "fetch_hotels" in dirty2 and "fetch_flights" in dirty2:
        print("[smoke] ❌ dirty_nodes accumulated across refines")
        return 1

    print("\n[smoke] ✅ pass")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
