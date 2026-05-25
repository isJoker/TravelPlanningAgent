"""In-process HTTP/WS smoke test against the FastAPI app.

Exercises the real route handlers without binding a TCP port — useful in
sandboxed environments where running uvicorn as a child process is unreliable.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("USE_MOCK_TOOLS", "true")
os.environ.setdefault("ALLOW_ORIGINS", "*")

import httpx  # noqa: E402


async def main() -> int:
    from api.server import app  # noqa: E402

    # ---- HTTP via httpx + ASGITransport ----
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/health")
        assert r.status_code == 200, r.text
        print("[http] /api/health →", r.json())

        body = {
            "conversation_name": "http-osaka",
            "bot_user_input": "想带 3 岁小孩",
            "destination": "大阪",
            "departure": "上海",
            "days_num": 3,
            "people_num": 3,
            "travel_theme": "亲子",
        }
        r = await c.post("/api/trip", json=body)
        assert r.status_code == 200, r.text
        data = r.json()
        print("[http] /api/trip →", data)
        thread_id = data["thread_id"]

        # The agent runs as an asyncio.create_task. Wait for it.
        for _ in range(60):
            await asyncio.sleep(0.5)
            r = await c.get("/api/files", params={"thread_id": thread_id})
            files = r.json().get("files", [])
            if any(f["name"].endswith(".md") for f in files):
                break
        else:
            print("[http] ❌ no markdown file produced")
            return 1
        print(f"[http] files: {[f['name'] for f in files]}")

        r = await c.get(f"/api/trip/{thread_id}/versions")
        print("[http] versions →", r.json())

        # Refine
        r = await c.post(f"/api/trip/{thread_id}/refine", json={"instruction": "把第3天改成室内活动"})
        assert r.status_code == 200, r.text
        print("[http] refine →", r.json())
        for _ in range(60):
            await asyncio.sleep(0.5)
            r = await c.get("/api/files", params={"thread_id": thread_id})
            files = r.json().get("files", [])
            if any(f["name"] == "trip_v2.md" for f in files):
                break
        else:
            print("[http] ❌ refine did not produce v2")
            return 1
        print(f"[http] files after refine: {[f['name'] for f in files]}")

    # ---- WebSocket pipeline test (direct: bypass TestClient quirks) ----
    # We bind a fake "websocket" object to the ConnectionManager and verify that
    # tool/node/task events flow from inside the agent to the WS via the monitor
    # singleton. This is the real path used in production.
    print("\n[ws] direct pipeline test…")

    from api.connection_manager import ConnectionManager
    from core.monitor import monitor as global_monitor
    from agent.plan_agent import run_plan_agent

    captured: list[dict] = []

    class FakeWebSocket:
        async def send_json(self, payload):
            captured.append(payload)

        async def close(self):
            pass

    mgr = ConnectionManager()
    mgr.set_loop(asyncio.get_running_loop())
    mgr.active_connections["ws-direct"] = FakeWebSocket()  # type: ignore
    global_monitor.set_websocket_manager(mgr)

    await run_plan_agent(
        {
            "destination": "北京",
            "departure": "上海",
            "days_num": 2,
            "people_num": 2,
            "travel_theme": "美食",
        },
        thread_id="ws-direct",
        trip_id="trp_ws_direct",
    )
    # Drain the run_coroutine_threadsafe queue.
    await asyncio.sleep(0.1)

    events_seen: dict[str, int] = {}
    for p in captured:
        events_seen[p.get("event", "?")] = events_seen.get(p.get("event", "?"), 0) + 1
    print(f"[ws] events captured: {events_seen}")
    assert "session_created" in events_seen, "no session_created"
    assert "tool_start" in events_seen, "no tool_start"
    assert "node_start" in events_seen, "no node_start"
    assert "task_result" in events_seen, "no task_result"

    print("\n[smoke_http] ✅ pass")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
