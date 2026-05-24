"""Plan-graph nodes (one function per node, all in one file for demo clarity).

Each node is an async function ``(state) -> partial_state``. Side effects
(WS push) go through the ``monitor`` singleton; reading the current
session_dir / thread_id goes through ``api.context``. Tools call the
``monitor`` themselves so we don't have to push tool events here.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List
from urllib.parse import quote

from api.context import get_session_dir, get_thread_id
from api.logger import logger
from api.monitor import monitor
from agent import agents
from services.pdf_renderer import render_report
from tools.base import FlightTool, HotelTool, POITool, WeatherTool
from tools.factory import (
    get_flight_provider,
    get_hotel_provider,
    get_poi_provider,
    get_weather_provider,
)


# ---------- decorators ----------
def _timed(node_name: str):
    """Wrap a node coroutine so it emits node_start / node_end events automatically."""

    def deco(fn: Callable[..., Awaitable[Dict[str, Any]]]):
        async def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            monitor.report_node_start(node_name)
            t0 = time.perf_counter()
            try:
                result = await fn(state)
            except Exception as e:
                monitor.report_error(node_name, str(e))
                raise
            duration = (time.perf_counter() - t0) * 1000
            summary = result.pop("_summary", None) if isinstance(result, dict) else None
            monitor.report_node_end(node_name, duration, summary)
            return result or {}

        wrapper.__name__ = node_name
        return wrapper

    return deco


# ---------- helpers ----------
def _date_range(start: str, days: int) -> List[str]:
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d")
    except (TypeError, ValueError):
        d0 = datetime.now() + timedelta(days=14)
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]


# ============================================================
#  validate_input
# ============================================================
@_timed("validate_input")
async def validate_input(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("destination"):
        raise ValueError("destination is required")
    if not state.get("days_num"):
        raise ValueError("days_num is required")
    if not state.get("people_num"):
        raise ValueError("people_num is required")

    start_date = state.get("start_date") or (
        (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    )
    days_num = int(state["days_num"])
    return {
        "start_date": start_date,
        "date_range": _date_range(start_date, days_num),
        "departure": state.get("departure") or "上海",
        "version": state.get("version", 1),
        "retry_count": 0,
        "errors": [],
        "_summary": f"{state['destination']} · {days_num}天 · {state['people_num']}人",
    }


# ============================================================
#  parse_intent
# ============================================================
@_timed("parse_intent")
async def parse_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    result = await agents.parse_intent(state)
    result["_summary"] = f"识别 {len(result.get('constraints', {}))} 项约束"
    return result


# ============================================================
#  fetch_weather
# ============================================================
@_timed("fetch_weather")
async def fetch_weather(state: Dict[str, Any]) -> Dict[str, Any]:
    tool = WeatherTool(provider=get_weather_provider(state["destination"]))
    try:
        weather = await tool.fetch(city=state["destination"], date_range=state["date_range"])
        return {"weather": weather, "_summary": f"{len(weather)} 天天气"}
    except Exception as e:
        return {
            "weather": [],
            "errors": [{"where": "fetch_weather", "message": str(e)}],
            "_summary": "降级：未取到天气",
        }


# ============================================================
#  fetch_flights (round-trip)
# ============================================================
@_timed("fetch_flights")
async def fetch_flights(state: Dict[str, Any]) -> Dict[str, Any]:
    tool = FlightTool(provider=get_flight_provider(state["departure"], state["destination"]))
    out: List[Dict[str, Any]] = []
    try:
        outbound = await tool.fetch(
            from_city=state["departure"],
            to_city=state["destination"],
            date=state["date_range"][0],
            pax=state["people_num"],
            direction="outbound",
        )
        inbound = await tool.fetch(
            from_city=state["destination"],
            to_city=state["departure"],
            date=state["date_range"][-1],
            pax=state["people_num"],
            direction="return",
        )
        out = outbound + inbound
        return {"flights": out, "_summary": f"{len(out)} 个航班候选"}
    except Exception as e:
        return {
            "flights": [],
            "errors": [{"where": "fetch_flights", "message": str(e)}],
            "_summary": "降级：未取到航班",
        }


# ============================================================
#  fetch_hotels
# ============================================================
@_timed("fetch_hotels")
async def fetch_hotels(state: Dict[str, Any]) -> Dict[str, Any]:
    tool = HotelTool(provider=get_hotel_provider(state["destination"]))
    try:
        hotels = await tool.fetch(
            city=state["destination"],
            checkin=state["date_range"][0],
            checkout=state["date_range"][-1],
            pax=state["people_num"],
            theme=state.get("travel_theme"),
        )
        return {"hotels": hotels, "_summary": f"{len(hotels)} 个酒店候选"}
    except Exception as e:
        return {
            "hotels": [],
            "errors": [{"where": "fetch_hotels", "message": str(e)}],
            "_summary": "降级：未取到酒店",
        }


# ============================================================
#  fetch_pois
# ============================================================
@_timed("fetch_pois")
async def fetch_pois(state: Dict[str, Any]) -> Dict[str, Any]:
    tool = POITool(provider=get_poi_provider(state["destination"]))
    try:
        pois = await tool.fetch(city=state["destination"], theme=state.get("travel_theme"))
        return {"pois": pois, "_summary": f"{len(pois)} 个 POI"}
    except Exception as e:
        return {
            "pois": [],
            "errors": [{"where": "fetch_pois", "message": str(e)}],
            "_summary": "降级：未取到 POI",
        }


# ============================================================
#  cluster_pois  (group by area, then split into N day-buckets)
# ============================================================
@_timed("cluster_pois")
async def cluster_pois(state: Dict[str, Any]) -> Dict[str, Any]:
    pois: List[Dict[str, Any]] = state.get("pois") or []
    days = int(state["days_num"])
    by_area: Dict[str, List[Dict[str, Any]]] = {}
    for p in pois:
        by_area.setdefault(p.get("area") or "其他", []).append(p)

    # Sort areas by size desc; round-robin assign across days.
    areas = sorted(by_area.keys(), key=lambda a: -len(by_area[a]))
    clustered: Dict[str, List[Dict[str, Any]]] = {f"day_{i + 1}": [] for i in range(days)}
    for idx, area in enumerate(areas):
        # If we have more areas than days, pack extras into the matching modulo bucket.
        bucket = f"day_{(idx % days) + 1}"
        clustered[bucket].extend(by_area[area])

    return {
        "pois_clustered": clustered,
        "_summary": f"{len(areas)} 个片区聚类到 {days} 天",
    }


# ============================================================
#  plan_itinerary
# ============================================================
@_timed("plan_itinerary")
async def plan_itinerary(state: Dict[str, Any]) -> Dict[str, Any]:
    result = await agents.plan_itinerary(state)
    itinerary = result.get("itinerary") or []
    tips = result.get("tips") or []

    # Fallback: synthesise from pois_clustered if LLM returned empty.
    if not itinerary:
        itinerary = _fallback_itinerary(state)
        tips = ["保持手机充电", "预留缓冲时间", "贵重物品随身"]

    # Backfill date strings from date_range when LLM returns placeholders.
    date_range = state.get("date_range") or []
    for i, d in enumerate(itinerary):
        if i < len(date_range):
            d.setdefault("date", date_range[i])
        d.setdefault("day_index", i + 1)

    summary = (
        f"为 {state['people_num']} 人规划了 {state['destination']} {state['days_num']} 天行程"
    )
    return {
        "itinerary": itinerary,
        "tips": tips,
        "summary": summary,
        "_summary": f"生成 {len(itinerary)} 天行程",
    }


def _fallback_itinerary(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    days = int(state["days_num"])
    clustered = state.get("pois_clustered") or {}
    weather = state.get("weather") or []
    out: List[Dict[str, Any]] = []
    for i in range(days):
        bucket = clustered.get(f"day_{i + 1}", [])
        slots: List[Dict[str, Any]] = []
        slot_names = ["上午", "中午", "下午", "晚上"]
        for idx, slot_name in enumerate(slot_names):
            if idx < len(bucket):
                p = bucket[idx]
                slots.append({
                    "slot": slot_name,
                    "poi": p["name"],
                    "type": p.get("type", "景点"),
                    "note": None,
                })
            else:
                slots.append({"slot": slot_name, "poi": "自由活动", "type": "自由", "note": None})
        out.append(
            {
                "day_index": i + 1,
                "date": (state.get("date_range") or ["—"] * days)[i],
                "weather_summary": (weather[i].get("condition") if i < len(weather) else None),
                "area": (bucket[0].get("area") if bucket else "—"),
                "slots": slots,
            }
        )
    return out


# ============================================================
#  estimate_budget
# ============================================================
@_timed("estimate_budget")
async def estimate_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    flights = state.get("flights") or []
    hotels = state.get("hotels") or []
    days = int(state["days_num"])
    pax = int(state["people_num"])
    pois = state.get("pois") or []

    flight_cost = 0.0
    if flights:
        outbound = next((f for f in flights if f.get("direction") == "outbound"), flights[0])
        ret = next((f for f in flights if f.get("direction") == "return"), flights[-1])
        flight_cost = float(outbound.get("price", 0)) + float(ret.get("price", 0))

    hotel_cost = 0.0
    if hotels:
        # Take median-priced hotel as representative.
        avg = sorted(h.get("price_per_night", 0) for h in hotels[:5])
        if avg:
            hotel_cost = avg[len(avg) // 2] * max(1, days - 1)

    poi_cost = sum(p.get("ticket_price", 0) for p in pois[:days * 2]) * pax * 0.5
    meals = days * pax * 180
    transport = days * pax * 80

    total = round(flight_cost + hotel_cost + poi_cost + meals + transport, 0)
    per_person = round(total / max(1, pax), 0)
    budget = {
        "currency": "CNY",
        "flights": round(flight_cost, 0),
        "hotels": round(hotel_cost, 0),
        "pois": round(poi_cost, 0),
        "meals": round(meals, 0),
        "transport": round(transport, 0),
        "total": total,
        "per_person": per_person,
    }
    return {"budget": budget, "_summary": f"总预算 {total} CNY (人均 {per_person})"}


# ============================================================
#  review_plan  (LLM check; can request retry)
# ============================================================
@_timed("review_plan")
async def review_plan(state: Dict[str, Any]) -> Dict[str, Any]:
    result = await agents.review_plan(state)
    passed = result.get("review_passed", True)
    feedback = result.get("review_feedback", "")
    iteration = int(state.get("retry_count", 0)) + 1

    monitor.report_review(iteration=iteration, passed=passed, feedback=feedback or None)
    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "retry_count": iteration,
        "_summary": f"iter#{iteration} {'PASSED' if passed else 'NEED_RETRY'}",
    }


# ============================================================
#  render_pdf
# ============================================================
@_timed("render_pdf")
async def render_pdf(state: Dict[str, Any]) -> Dict[str, Any]:
    session_dir = get_session_dir()
    if not session_dir:
        raise RuntimeError("session_dir not set in context")
    out_dir = Path(session_dir)
    version = int(state.get("version", 1))

    paths = render_report(
        ctx={
            "destination": state["destination"],
            "departure": state.get("departure"),
            "people_num": state["people_num"],
            "days_num": state["days_num"],
            "start_date": state.get("start_date"),
            "travel_theme": state.get("travel_theme"),
            "summary": state.get("summary"),
            "review_feedback": state.get("review_feedback"),
            "itinerary": state.get("itinerary") or [],
            "flights": state.get("flights") or [],
            "hotels": state.get("hotels") or [],
            "tips": state.get("tips") or [],
            "errors": state.get("errors") or [],
            "budget": state.get("budget") or {"currency": "CNY", "total": 0, "per_person": 0,
                                              "flights": 0, "hotels": 0, "pois": 0, "meals": 0, "transport": 0},
            "title": f"{state['destination']} {state['days_num']}天行程",
        },
        output_dir=out_dir,
        version=version,
    )

    files: List[Dict[str, Any]] = []
    for kind in ("md_path", "pdf_path"):
        p = paths.get(kind)
        if not p:
            continue
        path = Path(p)
        files.append(
            {
                "name": path.name,
                "path": str(path),
                "url": f"/api/download?path={quote(str(path))}",
                "size": path.stat().st_size,
                "mtime": path.stat().st_mtime,
            }
        )

    summary = (
        "PDF + Markdown 已生成"
        if paths.get("pdf_path")
        else "Markdown 已生成（PDF 跳过：未检测到可用的 PDF 转换引擎，详见日志）"
    )
    return {
        "pdf_path": paths.get("pdf_path") or "",
        "md_path": paths.get("md_path") or "",
        "files": files,
        "_summary": summary,
    }


# ============================================================
#  finalize  (push task_result to client)
# ============================================================
@_timed("finalize")
async def finalize(state: Dict[str, Any]) -> Dict[str, Any]:
    version = int(state.get("version", 1))
    files: List[Dict[str, Any]] = state.get("files") or []
    summary = state.get("summary") or f"{state['destination']} {state['days_num']}天行程已生成"

    monitor.report_task_result(result=summary, version=version, files=files)

    return {
        "history": [
            {
                "version": version,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "summary": summary,
            }
        ],
        "_summary": f"v{version} done · {len(files)} 个产物",
    }


# ============================================================
#  Conditional helper for review→retry
# ============================================================
def review_router(state: Dict[str, Any]) -> str:
    if state.get("review_passed"):
        return "render_pdf"
    if int(state.get("retry_count", 0)) < 2:
        return "plan_itinerary"
    return "render_pdf"
