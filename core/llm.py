"""LLM provider abstraction.

Two modes:
  - MOCK_LLM=true (default) → MockLLM returns deterministic stub JSON so the
    demo runs end-to-end without any API key.
  - MOCK_LLM=false → real GPT-4o via LangChain 1.0's unified
    ``init_chat_model`` factory (the ``openai:`` provider routes to
    ``langchain-openai``). Falls back to MockLLM on init failure.

The public surface is intentionally small: ``llm.chat_json(prompt) -> dict``
and ``llm.chat(prompt) -> str``.
"""
from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Dict, List, Optional

from core.logger import logger


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
        if "packing advisor" in p or "打包顾问" in p:
            return self._mock_pack_list(prompt)
        if "cultural & safety advisor" in p or "文化与安全顾问" in p:
            return self._mock_cultural_tips(prompt)
        if "pre-trip planner" in p or "出行前准备顾问" in p:
            return self._mock_pre_trip(prompt)
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
        # Heuristic budget level — keeps the demo coherent without an LLM.
        if budget is None:
            budget_level = "mid-range"
        elif budget < 500 * 7:
            budget_level = "budget"
        elif budget > 1500 * 7:
            budget_level = "luxury"
        else:
            budget_level = "mid-range"
        return {
            "budget_per_person": budget,
            "budget_level": budget_level,
            "must_visit": [],
            "avoid": [],
            "pace": pace,
            "interests": ["亲子"] if with_kids else [],
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

        # Coarse budget-level sniff so daily_cost looks plausible.
        if "luxury" in prompt:
            base_cost = 900
        elif "budget" in prompt and "mid-range" not in prompt:
            base_cost = 280
        else:
            base_cost = 480

        slots = ["上午", "中午", "下午", "晚上"]
        plan: List[Dict[str, Any]] = []
        idx = 0
        for d in range(1, days + 1):
            day_slots = []
            day_pois: List[str] = []
            for s in slots:
                name = pool[idx % len(pool)]
                idx += 1
                day_pois.append(name)
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
                "meals": {
                    "breakfast": "酒店自助早餐",
                    "lunch": f"{day_pois[1]}（推荐当地特色）",
                    "dinner": f"{day_pois[3]}（建议提前订位）",
                },
                "transport_hint": "市内地铁 + 短途步行；机场建议出租车",
                "daily_cost_cny": base_cost + random.randint(-60, 80),
                "booking_notes": [f"{day_pois[0]}：建议提前 3 天网上购票"],
            })
        return {
            "itinerary": plan,
            "tips": [
                "热门景点提前 1-2 周线上购票，现场排队会浪费半天",
                "随身少量现金应对小摊不收移动支付的情况",
                "晚高峰避开主干道，走小巷反而更快",
                "下载本地交通 App 比 Google Maps 更准",
            ],
        }

    @staticmethod
    def _mock_pack_list(prompt: str) -> Dict[str, Any]:
        with_kids = "亲子" in prompt or "with_kids" in prompt and "true" in prompt.lower()
        rainy = "雷阵雨" in prompt or "rain" in prompt.lower()
        clothing = ["短袖 T 恤 ×4", "长裤 ×2", "外套 ×1", "舒适步行鞋 ×1", "睡衣 ×1"]
        if rainy:
            clothing.extend(["折叠伞 ×1", "速干外套 ×1"])
        activities = ["背包 / 单肩包", "充电宝（≤20000mAh，可上飞机）", "保温水壶"]
        if with_kids:
            activities.extend(["儿童推车 / 背带", "防走失绳", "儿童遮阳帽"])
        return {
            "essentials": [
                "护照 / 身份证（有效期 ≥ 6 个月）",
                "电子机票 / 酒店确认单（打印 + 离线截图）",
                "主用银行卡 + 备用信用卡",
                "境外旅行保险电子单",
                "通讯录纸质备份",
            ],
            "clothing": clothing,
            "toiletries": [
                "洗漱套装（≤100ml 分装）",
                "防晒霜 SPF50+",
                "常用药（感冒、肠胃、止痛）",
            ] + (["儿童退烧药、口腔体温计"] if with_kids else []),
            "electronics": [
                "万能转换插头（含 Type-A/C/G）",
                "手机 + 数据线",
                "充电宝",
                "降噪耳机（机舱睡眠用）",
            ],
            "health": [
                "肠胃药、晕车药",
                "创可贴、消毒湿巾",
            ] + (["驱蚊液（热带地区）"] if "tropical" in prompt.lower() else []),
            "activities": activities,
            "misc": [
                "等值约 ¥1500 现金（应急）",
                "购买当地 SIM / eSIM（机场柜台）",
                "下载本地交通 / 翻译 App",
            ],
        }

    @staticmethod
    def _mock_cultural_tips(prompt: str) -> Dict[str, Any]:
        with_kids = "with_kids" in prompt and "true" in prompt.lower()
        return {
            "dos": [
                "进入当地餐厅先等待引座",
                "公共场所保持低声交流",
                "尊重当地排队文化",
                "参观寺庙 / 教堂前确认着装要求",
                "出门随身备一份酒店地址截图给司机看",
            ],
            "donts": [
                "不要在博物馆 / 教堂内开闪光灯",
                "不要在地铁里大声打电话",
                "陌生人主动搭讪要求拍照需提防",
                "扒手高发地带不要把贵重物品放外侧口袋",
            ],
            "dining": {
                "meal_times": "午餐 12:00-14:00；晚餐 18:30-21:00（部分国家更晚）",
                "tipping": "账单含服务费时无需另给小费；不含时建议 5-10%",
                "must_try": ["当地代表菜 ×2", "当地饮品 ×1"],
                "etiquette": [
                    "结账时招手即可，不要喊服务员",
                    "桌上分食时使用公勺",
                ],
            },
            "religious_sites": [
                "进入需脱鞋 / 摘帽，部分需要遮肩遮腿",
                "拍摄主神像前确认是否禁止",
            ],
            "safety": {
                "common_scams": ["假冒警察检查证件", "热心带路索要小费", "出租车关闭计价器报高价"],
                "areas_to_watch": ["主要火车站周边", "热门景点入口"],
                "emergency_number": "112（多数欧洲）/ 110、119、120（中国）",
                "transport_apps": ["Uber / 当地网约车 App"],
            },
            "useful_phrases": [
                {"local": "Hello / 你好", "meaning": "你好"},
                {"local": "Thank you", "meaning": "谢谢"},
                {"local": "How much is it?", "meaning": "这个多少钱？"},
                {"local": "Help!", "meaning": "救命！"},
            ] + ([{"local": "Where is the bathroom?", "meaning": "洗手间在哪？"}] if with_kids else []),
        }

    @staticmethod
    def _mock_pre_trip(prompt: str) -> Dict[str, Any]:
        with_kids = "with_kids" in prompt and "true" in prompt.lower()
        return {
            "checklist": [
                {
                    "timeline": "2 个月前",
                    "tasks": [
                        "确认护照有效期 ≥ 6 个月，必要时换发",
                        "查询并提交目的地签证申请",
                        "比价下单往返机票",
                        "锁定首晚 / 末晚酒店（其余日期可后定）",
                        "购买全程旅行保险",
                    ],
                },
                {
                    "timeline": "1 个月前",
                    "tasks": [
                        "预订热门景点门票 / 演出（容易售罄的优先）",
                        "预约人均较高的网红餐厅",
                        "通知银行国际用卡，开通境外通知",
                        "申请 / 续期国际驾照（如需自驾）",
                    ] + (["购买儿童旅行险，备齐儿童常用药"] if with_kids else []),
                },
                {
                    "timeline": "2 周前",
                    "tasks": [
                        "再次确认所有预订（航班 / 酒店 / 门票）",
                        "兑换约 ¥1500 等值现金",
                        "下载离线地图 / 翻译 App",
                        "打印纸质行程单 1 份备用",
                    ],
                },
                {
                    "timeline": "1 周前",
                    "tasks": [
                        "在线值机选座（开放后立即办）",
                        "整理打包行李，按 checklist 勾选",
                        "购买 / 激活当地 eSIM",
                        "把行程单 / 紧急联系人发送给家人",
                    ],
                },
                {
                    "timeline": "出发前一天",
                    "tasks": [
                        "再次核对登机时间与机场航站楼",
                        "随身行李：护照、移动电源、转换头、必要药品",
                        "调整作息，避免熬夜",
                        "设置 2 个以上闹钟",
                    ],
                },
            ]
        }


# ---------------- Real LLM (GPT-4o via langchain 1.0) ----------------
class RealLLM:
    """Real chat model wrapper using the LangChain 1.0 ``init_chat_model`` factory.

    LangChain 1.0 introduced a unified provider-prefixed entry point
    (``init_chat_model("openai:gpt-4o", ...)``) that replaces the
    provider-specific constructors of 0.x. We still depend on
    ``langchain-openai`` so the underlying ``ChatOpenAI`` class is available
    to the factory; we just no longer instantiate it directly.

    Messages are sent as a ``[HumanMessage(...)]`` list (the 1.0 idiom) rather
    than a bare prompt string.
    """

    name = "openai"

    def __init__(self) -> None:
        from langchain.chat_models import init_chat_model

        model_name = os.getenv("LLM_MODEL", "gpt-4o")
        kwargs: Dict[str, Any] = {
            "model_provider": "openai",
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
        # init_chat_model returns a BaseChatModel (here ChatOpenAI under the hood).
        self._client = init_chat_model(model_name, **kwargs)

    async def chat(self, prompt: str, **_: Any) -> str:
        from langchain_core.messages import HumanMessage

        msg = await self._client.ainvoke([HumanMessage(content=prompt)])
        # In 1.0, AIMessage.content can be either a str or a list of content
        # blocks. Normalise to plain text.
        return _content_to_text(getattr(msg, "content", msg))

    async def chat_json(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        instruction = (
            "You must respond with a single valid JSON object only, no markdown code fences."
        )
        text = await self.chat(f"{prompt}\n\n{instruction}")
        return _extract_json(text) or {}


def _content_to_text(content: Any) -> str:
    """LangChain 1.0 messages may carry list-of-blocks content; flatten to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # text block: {"type": "text", "text": "..."}
                if "text" in block:
                    parts.append(str(block["text"]))
                elif "content" in block:
                    parts.append(str(block["content"]))
        return "".join(parts)
    return str(content)


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
