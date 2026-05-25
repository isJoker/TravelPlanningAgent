"""FastAPI entry: REST endpoints + WebSocket /ws/{thread_id}."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.connection_manager import ConnectionManager
from core.logger import logger
from core.monitor import monitor
from api.schemas import (
    FileItem,
    FilesResponse,
    RefineRequest,
    TripRequest,
    TripResponse,
    VersionItem,
    VersionsResponse,
)

# Load .env from project root before importing modules that read env.
load_dotenv(Path(__file__).parents[1] / ".env")


# Defer agent imports until after .env is loaded.
from agent.plan_agent import run_plan_agent  # noqa: E402
from agent.refine_agent import run_refine_agent  # noqa: E402

PROJECT_ROOT = Path(__file__).parents[1].resolve()
OUTPUT_DIR = PROJECT_ROOT / "output"

manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    monitor.set_websocket_manager(manager)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("FastAPI started, ws manager bound to event loop")
    yield
    logger.info("FastAPI shutdown")


app = FastAPI(title="Travel Planning Agent (Demo)", version="0.3.0", lifespan=lifespan)


_origins_env = os.getenv("ALLOW_ORIGINS", "*")
_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# ---------- helpers ----------
def _session_dir_for(thread_id: str) -> Path:
    return OUTPUT_DIR / f"session_{thread_id}"


def _safe_path(p: str) -> Path:
    """Resolve a download path while ensuring it stays inside OUTPUT_DIR."""
    target = Path(p).resolve()
    try:
        target.relative_to(OUTPUT_DIR)
    except ValueError as e:
        raise HTTPException(status_code=403, detail="path outside allowed root") from e
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return target


def _file_item(p: Path) -> FileItem:
    rel = p.relative_to(OUTPUT_DIR)
    return FileItem(
        name=p.name,
        path=str(p),
        url=f"/api/download?path={quote(str(p))}",
        size=p.stat().st_size,
        mtime=p.stat().st_mtime,
    )


def _list_session_files(thread_id: str) -> list[FileItem]:
    sd = _session_dir_for(thread_id)
    if not sd.exists():
        return []
    return [
        _file_item(p)
        for p in sorted(sd.iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]


# ---------- REST ----------
@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "ts": time.time()}


@app.post("/api/trip", response_model=TripResponse)
async def create_trip(req: TripRequest) -> TripResponse:
    thread_id = req.conversation_name or f"trip-{uuid.uuid4().hex[:8]}"
    trip_id = f"trp_{uuid.uuid4().hex[:10]}"
    payload = req.model_dump()
    payload["conversation_name"] = thread_id

    asyncio.create_task(run_plan_agent(payload, thread_id, trip_id=trip_id))
    return TripResponse(trip_id=trip_id, thread_id=thread_id, status="started", version=1)


@app.post("/api/trip/{thread_id}/refine", response_model=TripResponse)
async def refine_trip(thread_id: str, req: RefineRequest) -> TripResponse:
    trip_id = f"trp_{uuid.uuid4().hex[:10]}"
    asyncio.create_task(run_refine_agent(req.instruction, thread_id, trip_id=trip_id))
    return TripResponse(trip_id=trip_id, thread_id=thread_id, status="started", version=0)


@app.get("/api/trip/{thread_id}/versions", response_model=VersionsResponse)
async def list_versions(thread_id: str) -> VersionsResponse:
    sd = _session_dir_for(thread_id)
    if not sd.exists():
        return VersionsResponse(versions=[])

    by_version: dict[int, VersionItem] = {}
    for p in sorted(sd.iterdir()):
        if not p.is_file():
            continue
        if not p.name.startswith("trip_v"):
            continue
        try:
            v = int(p.stem.split("_v")[1])
        except (IndexError, ValueError):
            continue
        item = by_version.setdefault(
            v,
            VersionItem(version=v, created_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))),
        )
        if p.suffix == ".pdf":
            item.pdf_path = str(p)
        elif p.suffix == ".md":
            item.md_path = str(p)
    return VersionsResponse(versions=sorted(by_version.values(), key=lambda x: x.version))


@app.get("/api/files", response_model=FilesResponse)
async def list_files(thread_id: str) -> FilesResponse:
    return FilesResponse(files=_list_session_files(thread_id))


@app.get("/api/download")
async def download(path: str = Query(...)) -> FileResponse:
    target = _safe_path(path)
    media = "application/pdf" if target.suffix == ".pdf" else "application/octet-stream"
    if target.suffix == ".md":
        media = "text/markdown; charset=utf-8"
    return FileResponse(target, media_type=media, filename=target.name)


# ---------- WebSocket ----------
@app.websocket("/ws/{thread_id}")
async def ws_endpoint(websocket: WebSocket, thread_id: str) -> None:
    await manager.connect(websocket, thread_id)
    try:
        while True:
            msg = await websocket.receive_text()
            # Echo "ping" as "pong" for keep-alive; ignore everything else.
            if msg == "ping":
                await websocket.send_json({"event": "pong", "data": {}})
    except WebSocketDisconnect:
        manager.disconnect(websocket, thread_id)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[WS] handler error thread_id={thread_id}: {e}")
        manager.disconnect(websocket, thread_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
