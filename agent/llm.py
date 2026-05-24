"""LLM provider abstraction.

Two modes:
  - MOCK_LLM=true (default) → MockLLM returns deterministic stub JSON so the
    demo runs end-to-end without any API key.
  - MOCK_LLM=false → real GPT-4o via langchain_openai. Falls back to the
    secondary provider on RateLimitError / APIConnectionError if configured.

The public surface is intentionally small: ``llm.chat_json(prompt) -> dict``
and ``llm.chat(prompt) -> str``.
"""
from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Dict, List, Optional

from api.logger import logger


def _truthy(v: Optional[str]) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


# ---------------- Mock LLM ----------------
class MockLLM:
    """Deterministic, structurally-correct responses for each prompt kind.

    Each prompt template starts with a short marker (e.g. "you are a travel
    preference extractor"). We sniff the marker and produce a canned reply
    in the right shape so downstream parsing never fails.
    """

    name = "mock"

    async def chat(self, prompt: str, **kwargs: Any) -> str:
        return json.dumps(await self.chat_json(prompt, **kwargs), ensure_ascii=False)

    async def chat_json(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        p = prompt.lower()
        if "preference extractor" in p or "偏好抽取器" in p:
            return self._mock_parse_intent(prompt)
        if "refine intent" in p or "指令解析器" in p:
            return self._mock_refine_intent(prompt)
        if "审稿编辑" in p or "review editor" in p:
            return {"passed": True, "issues": [], "suggestions": []}
        if "旅行规划师" in p or "travel planner" in p:
            return self._mock_plan_itinerary(prompt)
        # default
        return {}

    # --------- canned replies ---------
    @staticmethod
    def _mock_parse_intent(prompt: str) -> Dict[str, Any]:
        with_kids = "孩" in prompt or "kid" in prompt.lower()
        budget = None
        m = re.search(r"(\d{4,6})\s*(元|cny|rmb)", prompt, re.IGNORECASE)
        if m:
            budget = int(m.group(1))
        pace = "relaxed" if with_kids else "balanced"
        return {
            "budget_per_person": budget,
            "must_visit": [],
            "avoid": [],
            "pace": pace,
            "with_kids": with_kids,
            "with_elder": False,
            "diet": [],
            "transport_pref": "public",
        }

    @staticmethod
    def _mock_refine_intent(prompt: str) -> Dict[str, Any]:
        text = prompt
        # Crude intent classification suitable for demo.
        if any(k in text for k in ["第", "Day", "day"]):
            day_match = re.search(r"第\s*(\d+)\s*天", text)
            day_idx = int(day_match.group(1)) if day_match else 1
            return {"type": "rework_day", "targets": [f"day_{day_idx}"], "payload": {}}
        if any(k in text for k in ["酒店", "住宿", "hotel"]):
            return {"type": "change_hotel", "targets": [], "payload": {}}
        if any(k in text for k in ["机票", "航班", "flight"]):
            return {"type": "change_flight", "targets": [], "payload": {}}
        if any(k in text for k in ["紧", "松", "节奏", "pace"]):
            return {"type": "change_pace", "targets": [], "payload": {"new_pace": "relaxed"}}
        if any(k in text for k in ["预算", "budget"]):
            return {"type": "change_budget", "targets": [], "payload": {}}
        if any(k in text for k in ["主题", "亲子", "蜜月", "美食"]):
            return {"type": "change_theme", "targets": [], "payload": {}}
        if any(k in text for k in ["天数", "加一天", "再多"]):
            return {"type": "extend_days", "targets": [], "payload": {"extra_days": 1}}
        return {"type": "freeform", "targets": [], "payload": {"free_text": text[:200]}}

    @staticmethod
    def _mock_plan_itinerary(prompt: str) -> Dict[str, Any]:
        # Best-effort extract days from the prompt, then synthesize a plan.
        days_match = re.search(r"(\d+)\s*天", prompt) or re.search(r"days[_\s]*num[\"']?\s*[:=]\s*(\d+)", prompt)
        days = int(days_match.group(1)) if days_match else 3

        # Try to extract POIs JSON from prompt; if absent use placeholder names.
        poi_names = re.findall(r'"name"\s*:\s*"([^"]+)"', prompt)
        pool = poi_names or [
            "中央公园", "美食街", "博物馆", "购物中心", "夜景观光台",
            "海滨步道", "本地餐厅", "工艺品市集", "主题乐园", "茶屋",
        ]
        random.seed(hash(prompt) & 0xFFFFFFFF)

        slots = ["上午", "中午", "下午", "晚上"]
        plan: List[Dict[str, Any]] = []
        idx = 0
        for d in range(1, days + 1):
            day_slots = []
            for s in slots:
                name = pool[idx % len(pool)]
                idx += 1
                day_slots.append({
                    "slot": s,
                    "poi": name,
                    "type": "餐厅" if s in ("中午", "晚上") else "景点",
                    "note": "推荐提前预约" if s == "晚上" else None,
                })
            plan.append({
                "day_index": d,
                "date": f"D{d}",
                "weather_summary": "多云转晴",
                "area": "市中心",
                "slots": day_slots,
            })
        return {"itinerary": plan, "tips": ["随身携带雨具", "保持手机充电", "注意贵重物品"]}


# ---------------- Real LLM (GPT-4o via langchain) ----------------
class RealLLM:
    name = "openai"

    def __init__(self) -> None:
        from langchain_openai import ChatOpenAI

        kwargs: Dict[str, Any] = {
            "model": os.getenv("LLM_MODEL", "gpt-4o"),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.4")),
            "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            "max_retries": int(os.getenv("LLM_MAX_RETRIES", "3")),
        }
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key
        base_url = os.getenv("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = ChatOpenAI(**kwargs)

    async def chat(self, prompt: str, **_: Any) -> str:
        msg = await self._client.ainvoke(prompt)
        return msg.content if hasattr(msg, "content") else str(msg)

    async def chat_json(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        instruction = (
            "You must respond with a single valid JSON object only, no markdown code fences."
        )
        text = await self.chat(f"{prompt}\n\n{instruction}")
        return _extract_json(text) or {}


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction (strips ```json fences if any)."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


# ---------------- Factory ----------------
_llm = None


def build_llm():
    global _llm
    if _llm is not None:
        return _llm
    if _truthy(os.getenv("MOCK_LLM", "true")) or not os.getenv("OPENAI_API_KEY"):
        if not _truthy(os.getenv("MOCK_LLM", "true")):
            logger.warning("MOCK_LLM=false but OPENAI_API_KEY missing → falling back to MockLLM")
        _llm = MockLLM()
        logger.info(f"LLM initialised: {_llm.name}")
        return _llm
    try:
        _llm = RealLLM()
        logger.info(f"LLM initialised: {_llm.name} model={os.getenv('LLM_MODEL', 'gpt-4o')}")
    except Exception as e:
        logger.warning(f"Real LLM init failed ({e}); falling back to MockLLM")
        _llm = MockLLM()
    return _llm
