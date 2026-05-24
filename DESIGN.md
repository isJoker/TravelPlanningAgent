# 智能旅行助手 Agent — 技术方案

> 版本: v0.3 (含决策更新 + 前端方案 + 架构对齐 DeepSearchResearcher)
> 编写日期: 2026-05-24
> 适用范围: 基于 LangGraph 的旅行规划 Agent，输出行程 PDF；前端实时展示思维链与工具调用
> 主架构: **异步任务 + WebSocket 实时推送 + 多轮调整 + Mock-to-Real 数据源切换 + Vue 3 前端**

---

## 0. 决策日志 (Decisions Log)

| # | 决策 | 状态 | 说明 |
|---|------|------|------|
| D-01 | 默认 LLM 使用 GPT-4o | ✅ 已确认 | `LLM_PROVIDER=openai` `LLM_MODEL=gpt-4o`；DeepSeek-V3 / Qwen-Max 作为兜底 |
| D-02 | 机票 / 酒店初期使用 Mock 数据 | ✅ 已确认 | `USE_MOCK_TOOLS=true` 切换；真实 API 接入方案见 §5.3 |
| D-03 | 支持多轮调整 | ✅ 已确认 | `refine` 子图，按用户指令做最小化重算 |
| D-04 | 主架构使用异步 | ✅ 已确认 | `asyncio.create_task` 直接调度（不引入 Celery），WebSocket 推送进度 |
| D-05 | **Checkpointer 使用 InMemorySaver** | ✅ 已确认 | 不引入 Redis；State 由进程内内存保存，按 `thread_id` 隔离 |
| D-06 | **新增 Vue 3 Web 前端** | ✅ 已确认 | 参考 Kiro 风格：输入框 + 历史消息 + 思维链 + 工具调用卡片，全程 WebSocket 双向 |
| D-07 | **整体架构对齐 DeepSearchResearcher** | ✅ 已确认 | ContextVar 协程隔离 + 单例 Monitor 推送 + WebSocket `/ws/{thread_id}` |

---

## 1. 项目目标

构建一个智能旅行助手 Agent。用户在 Web 前端用自然语言或表单提交诉求（出发地、目的地、天数、人数、主题等），
Agent 自动完成 **天气查询 / 机票查询 / 酒店查询 / 景点攻略 / 行程编排 / 预算估算**，
并最终生成一份可下载的 **旅行方案 PDF**；用户可对生成的方案做**多轮调整**，全程在前端实时看到工具调用与思维链。

### 1.1 核心需求

| 编号 | 需求 | 说明 |
|------|------|------|
| F-01 | 多源信息聚合 | 调用天气 / 机票 / 酒店 / POI 等外部 API |
| F-02 | 智能行程编排 | 根据天数 / 人数 / 主题 / POI 距离编排日程 |
| F-03 | 主题适配 | 亲子 / 蜜月 / 美食 / 户外 / 文化等主题影响 POI 选择和节奏 |
| F-04 | PDF 输出 | 结构化 PDF，含封面、概览、日程、酒店、机票、预算、注意事项 |
| F-05 | 可观测 | 每一步可追踪（LangSmith / 日志），便于调试 |
| F-06 | 失败可恢复 | 单一外部 API 失败时降级，不阻塞整体流程 |
| F-07 | 多轮调整 | 用户对已生成方案做局部修改（换酒店、改某天、调节奏），仅重算受影响的部分 |
| F-08 | 异步执行 | 一次规划过程 30~120s，必须异步执行 + 进度可见 |
| F-09 | **Web 前端** | Kiro 风格 UI：输入框、历史聊天记录、思维链折叠面板、工具调用卡片、文件预览、PDF 下载 |
| F-10 | **WebSocket 实时推送** | 思维链 / 工具调用 / 子智能体调用 / 最终结果，全程实时推送到前端 |

### 1.2 非功能需求

- **响应时延**: 5 天行程 p95 ≤ 60s；refine p95 ≤ 20s
- **可扩展**: 节点 / 工具松耦合，新增数据源不影响主图
- **缓存**: 相同查询参数 30min 内复用结果（进程内 LRU + TTL）
- **可重入**: 同一会话期内（进程未重启）支持多轮调整；进程重启后 State 丢失（InMemorySaver 限制，见 §4.6）
- **数据源可切换**: Mock ↔ Real 通过环境变量切换，Tool 接口对图层透明
- **多用户并发**: 通过 `ContextVar` 实现协程级会话隔离，避免串数据

---

## 2. 输入与输出

### 2.1 输入参数（与图一一致）

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `CONVERSATION_NAME` | string | 否 | 会话标识（即 `thread_id`），用于多轮 | `trip_2026_summer` |
| `BOT_USER_INPUT` | string | 否 | 用户自然语言补充诉求 | "想带 3 岁小孩，避免长途车程" |
| `destination` | string | **是** | 目的地（城市 / 区域） | `大阪` |
| `departure` | string | 否 | 出发地，缺省由用户补充或取常驻地 | `上海` |
| `days_num` | int | **是** | 游玩天数 | `5` |
| `people_num` | int | **是** | 出行人数 | `2` |
| `start_date` | string (YYYY-MM-DD) | 否 | 出发日期，缺省取当前日 +14d | `2026-07-15` |
| `travel_theme` | string | 否 | 主题，影响 POI 选择 | `亲子` / `美食` / `户外` |

### 2.2 输出（HTTP）

```jsonc
{
  "status": "started",
  "trip_id": "trp_abc123",
  "thread_id": "trip_2026_summer",
  "version": 1
}
```

最终结果与中间过程通过 WebSocket 推送（见 §3.4 / §10）。

---

## 3. 整体架构

整体架构对齐 DeepSearchResearcher，采用**FastAPI + WebSocket + LangGraph + InMemorySaver + 单例 Monitor + Vue 3 前端**的分层模式。

### 3.1 架构分层

```
┌──────────────────────────────────────────────────────────────────┐
│  Web Frontend (Vue 3 + TS + Vite)                                │
│  - Kiro 风格 UI: 输入框 / 历史聊天 / 思维链 / 工具调用卡片        │
│  - WebSocket Client (ws://host/ws/{thread_id})                   │
│  - PDF / 文件预览与下载                                          │
└──────────────┬───────────────────────────────────────────────────┘
               │ HTTP (axios) + WebSocket
┌──────────────▼───────────────────────────────────────────────────┐
│  FastAPI Service Layer (api/server.py)                           │
│  - REST: /api/trip /api/refine /api/files /api/download          │
│  - WebSocket: /ws/{thread_id} + ConnectionManager                │
│  - 启动 asyncio.create_task 调度 Agent                            │
└──────────────┬───────────────────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────────────┐
│  LangGraph Agent Orchestration Layer (agent/)                    │
│  - plan_graph + refine_graph                                     │
│  - InMemorySaver (按 thread_id 隔离的 State)                     │
│  - LLM Provider 抽象（GPT-4o + fallback）                         │
└──┬─────────┬──────────┬──────────┬──────────────────────────────┘
   │         │          │          │
   ▼         ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│Weather│ │Flight│ │Hotel │ │ POI  │   每个节点内调用 monitor.report_xxx()
│ Tool │ │ Tool │ │ Tool │ │ Tool │   把工具调用 / 子任务推送到前端
└──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
   │        │        │        │
   ▼        ▼        ▼        ▼
┌──────────────────────────────────┐
│ Provider Adapter (Mock | Real)   │
└──────────────────────────────────┘
   │
   ▼
外部 API（和风 / Amadeus / Booking / 高德 ...）

┌──────────────────────────────────────────────────────────────────┐
│  Cross-cutting                                                    │
│  - ContextVar(session_dir, thread_id)  → 协程级隔离              │
│  - Monitor 单例 → asyncio.run_coroutine_threadsafe → WebSocket    │
│  - PDF Renderer (Jinja2 + WeasyPrint)                             │
│  - Local FS: output/session_{thread_id}/  /  updated/session_xxx/│
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 技术栈

| 类别 | 选型 | 理由 |
|------|------|------|
| 后端语言 | Python 3.11+ | LangGraph 原生支持 |
| Agent 框架 | LangGraph 0.2+ + LangChain | 状态机模型适合工作流型 Agent |
| LLM | **OpenAI GPT-4o（默认）** / DeepSeek-V3 / Qwen-Max（备选） | LLM Provider 抽象，可替换 |
| Web 框架 | FastAPI + Uvicorn | 异步 / WebSocket / OpenAPI |
| 异步任务 | **asyncio.create_task**（不引入 Celery） | 简单直接，与 DeepSearchResearcher 一致；后续如需多 worker 可平滑替换 |
| Checkpointer | **`langgraph.checkpoint.memory.InMemorySaver`** | 进程内内存，按 `thread_id` 隔离；不依赖外部存储 |
| 数据校验 | Pydantic v2 | 与 LangGraph State 天然集成 |
| 实时通信 | **原生 WebSocket** | 与前端原生 `WebSocket` API 直接对接，无需 socket.io 客户端 |
| 会话隔离 | **`contextvars.ContextVar`** | 协程级隔离 `session_dir` / `thread_id` |
| 缓存 | `cachetools.TTLCache`（进程内）| 不引入 Redis |
| PDF 渲染 | Jinja2 + WeasyPrint | HTML/CSS 模板，中文友好 |
| 可观测 | LangSmith + Loguru | Trace + 结构化日志 |
| 配置 | pydantic-settings + .env | 12-factor |
| 包管理 | uv（首选）/ pip + requirements.txt | 简单 |
| 容器 | Docker + docker-compose | 后端 + 前端联合部署 |
| 前端 | **Vue 3 + TypeScript + Vite + axios + marked** | 与 DeepSearchResearcher UI 一致，迁移成本最低 |

### 3.3 LLM Provider 抽象

```python
# app/core/llm.py
from langchain.chat_models import init_chat_model

def build_llm():
    return FallbackLLM(
        primary  = init_chat_model(model=settings.LLM_MODEL),     # gpt-4o
        fallback = init_chat_model(model="deepseek-chat", model_provider="deepseek")
                   if settings.LLM_FALLBACK_PROVIDER else None,
        retry    = ExponentialBackoff(max_attempts=3),
    )
```

`.env.example` 关键配置：

```env
# ===== LLM =====
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=
LLM_FALLBACK_PROVIDER=deepseek
DEEPSEEK_API_KEY=
LLM_TEMPERATURE=0.4
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=3

# ===== 数据源开关 =====
USE_MOCK_TOOLS=true

# ===== 服务 =====
HOST=0.0.0.0
PORT=8000
ALLOW_ORIGINS=*
```

**触发 fallback 的条件**：HTTP 429 / 5xx / 超时 / `RateLimitError` / `APIConnectionError`。

### 3.4 实时通信总览

```
[Tool Node 内部]
    monitor.report_tool("WeatherTool", {...})
        │
        ▼
[Monitor 单例]
    根据 ContextVar 拿到 thread_id
        │
        ▼
    asyncio.run_coroutine_threadsafe(
        manager.send_to_thread(payload, thread_id),
        manager.loop                  ← 启动时绑定的 FastAPI loop
    )
        │
        ▼
[ConnectionManager.send_to_thread]
    websocket = self.active_connections[thread_id]
    await websocket.send_json(payload)
        │
        ▼
[前端 ws.onmessage]
    根据 event 类型更新 messages[].logs / files / content
```

**关键点**：
- Monitor 是单例，全局可 `from app.api.monitor import monitor` 直接用
- `set_websocket_manager(manager)` 在 FastAPI `startup` 钩子中绑定 loop，避免启动顺序导致的 loop 不一致
- 节点 / 工具内部都是普通 `def` 或 `async def`，不需要持有 websocket 引用
- 通过 ContextVar 自动找到对应连接，避免参数透传

---

## 4. LangGraph 工作流设计

整体由两张图组成：
- **`plan_graph`** — 首次生成完整方案
- **`refine_graph`** — 多轮调整，基于 InMemorySaver 中已存在的 State 做最小化重算

两张图共享同一个 `TripState` 和同一份 `InMemorySaver`，通过 `thread_id`（即 `conversation_name`）关联。

### 4.1 状态定义 (`TripState`)

```python
# app/agent/state.py
import operator
from typing import Annotated, TypedDict

class TripState(TypedDict, total=False):
    # ===== 输入 =====
    conversation_name: str
    bot_user_input: str
    destination: str
    departure: str | None
    days_num: int
    people_num: int
    start_date: str | None
    travel_theme: str | None

    # ===== 解析 / 中间态 =====
    parsed_intent: dict
    date_range: list[str]
    constraints: dict

    # ===== 信息聚合 =====
    weather: list[WeatherDay]
    flights: list[FlightOption]
    hotels: list[HotelOption]
    pois: list[POI]
    pois_clustered: dict

    # ===== 规划结果 =====
    itinerary: list[DayPlan]
    budget: BudgetBreakdown
    tips: list[str]

    # ===== 反思 =====
    review_passed: bool
    review_feedback: str
    retry_count: int

    # ===== 多轮调整 =====
    version: int
    history: list[VersionMeta]
    refine_request: str
    refine_intent: RefineIntent
    dirty_nodes: Annotated[set[str], lambda a, b: a | b]

    # ===== 输出 =====
    pdf_path: str
    pdf_url: str
    errors: Annotated[list[ErrorRecord], operator.add]
```

### 4.2 Plan 图节点列表

| 节点 | 职责 | 调用 LLM | 失败策略 |
|------|------|---------|---------|
| `validate_input` | 校验必填、补默认值 | 否 | 致命 |
| `parse_intent` | 从 `bot_user_input` 抽取隐式约束 | 是 | 失败则用默认 |
| `fetch_weather` | 调用天气 API | 否 | 降级：历史同期均值 |
| `fetch_flights` | 调用机票 API | 否 | 降级：价格区间提示 |
| `fetch_hotels` | 调用酒店 API | 否 | 降级：区域推荐 |
| `fetch_pois` | 拉取 POI（景点+餐厅+体验） | 否 | 降级：本地知识库 |
| `cluster_pois` | 按地理片区+主题+时段聚类 | 否（可选 LLM 排序） | 致命 |
| `plan_itinerary` | LLM 规划每日行程 | 是 | 致命 |
| `estimate_budget` | 汇总各项费用 | 否 | 致命 |
| `review_plan` | 自反思：节奏/距离/天气/主题契合度 | 是 | 不通过则回到 `plan_itinerary`（最多 2 次） |
| `render_pdf` | Jinja2 → WeasyPrint → PDF | 否 | 致命 |
| `finalize` | 落盘 / 推送结果 | 否 | 致命 |

### 4.3 Plan 图结构（含并行 fan-out）

```
                START
                  │
                  ▼
         validate_input
                  │
                  ▼
         parse_intent
                  │
       ┌──────────┼──────────┬──────────┐
       ▼          ▼          ▼          ▼
  fetch_weather fetch_flights fetch_hotels fetch_pois  (并行)
       └──────────┴──────────┴──────────┘
                  │  (join)
                  ▼
            cluster_pois
                  │
                  ▼
          plan_itinerary ◄─────┐
                  │            │
                  ▼            │
         estimate_budget       │
                  │            │
                  ▼            │
           review_plan ────────┘  (failed & retry<2)
                  │ (passed)
                  ▼
              render_pdf
                  │
                  ▼
              finalize
                  │
                  ▼
                 END
```

### 4.4 Refine 图（多轮调整）

#### 4.4.1 核心思路

- 用 `conversation_name` 作为 LangGraph 的 `thread_id`，从 `InMemorySaver` 加载上一版完整 `TripState`
- LLM 把用户的调整指令解析成结构化的 `RefineIntent`
- `route_refine_dispatcher` 决定哪些节点需要重算（写入 `dirty_nodes`），跳过其他节点
- 重算完成后统一走 `estimate_budget` → `review_plan(lite)` → `render_pdf` → `finalize`，并 `version+1`

#### 4.4.2 RefineIntent 类型

```python
# app/models/refine.py
from typing import Literal
from pydantic import BaseModel

class RefineIntent(BaseModel):
    type: Literal[
        "swap_poi", "rework_day", "change_hotel", "change_flight",
        "change_pace", "change_theme", "change_budget",
        "extend_days", "freeform",
    ]
    targets: list[str] = []
    payload: dict = {}
```

#### 4.4.3 dirty_nodes 映射表

| RefineIntent.type | dirty_nodes |
|-------------------|-------------|
| `swap_poi` | `plan_itinerary`（局部）|
| `rework_day` | `plan_itinerary`（仅 targets 指定的天）|
| `change_hotel` | `fetch_hotels`, `plan_itinerary` |
| `change_flight` | `fetch_flights` |
| `change_pace` | `plan_itinerary` |
| `change_theme` | `fetch_pois`, `cluster_pois`, `plan_itinerary` |
| `change_budget` | `fetch_hotels`, `plan_itinerary` |
| `extend_days` | 全部（实际上回到 plan_graph）|
| `freeform` | `plan_itinerary` |

> 所有 refine 类型都会**强制重算** `estimate_budget`、`review_plan`、`render_pdf`、`finalize`。

#### 4.4.4 Refine 图结构

```
            START
              │
              ▼
   load_previous_state    (从 InMemorySaver 取 v_n by thread_id)
              │
              ▼
   parse_refine_intent    (LLM → RefineIntent)
              │
              ▼
   route_refine_dispatcher  (写 dirty_nodes，决定下一步)
              │
   ┌──────────┼─────────────┬──────────┐
   ▼          ▼             ▼          ▼
fetch_flights fetch_hotels fetch_pois → cluster   (按需触发)
   └──────────┴─────────────┴──────────┘
              │
              ▼
      plan_itinerary (partial)   (支持局部重排)
              │
              ▼
     estimate_budget
              │
              ▼
      review_plan (lite)
              │
              ▼
        render_pdf
              │
              ▼
       finalize (v_n+1)
              │
              ▼
             END
```

#### 4.4.5 关键约束

- 同一个 `thread_id` 同时只能有一个任务在跑（用 `asyncio.Lock` per thread_id）
- 历史版本 PDF 保留最近 5 版（`output/session_xxx/trip_v1.pdf`, `_v2.pdf`, ...）
- Refine 失败不污染当前已发布版本（先生成临时 PDF，成功后再切 current 指针）
- LLM 解析 RefineIntent 失败时回退为 `freeform`，把原始指令注入 plan prompt

### 4.5 Reducer / 合并策略

```python
errors:        Annotated[list[ErrorRecord], operator.add]
history:       Annotated[list[VersionMeta], operator.add]
dirty_nodes:   Annotated[set[str], lambda a, b: a | b]
```

### 4.6 InMemorySaver 限制与权衡

| 维度 | 影响 | 处置 |
|------|------|------|
| 进程重启 | 所有会话 State 丢失 | 1) 重启前 finalize 的 PDF 已落盘到 `output/`；2) 后续可平滑切换 `SqliteSaver` 或自定义 Persistent Saver，接口兼容 |
| 多 worker 部署 | 不同 worker 之间 State 不共享 | 通过反向代理做 sticky session（按 `thread_id` 哈希） 或暂时单 worker 部署 |
| 内存增长 | 长时间运行后 State 累积 | 定期清理（LRU + 24h TTL，自定义包装 `InMemorySaver`）|

```python
# app/agent/checkpointer.py
from langgraph.checkpoint.memory import InMemorySaver

# 全局单例（进程内）
_saver: InMemorySaver | None = None

def get_checkpointer() -> InMemorySaver:
    global _saver
    if _saver is None:
        _saver = InMemorySaver()
    return _saver
```

> **生产升级路径**：将 `get_checkpointer()` 切换为 `SqliteSaver.from_conn_string("checkpoints.db")` 即可，无需改业务代码。

---

## 5. 工具 (Tools) 设计

### 5.1 通用 Tool 接口（含 Mock/Real 切换 + 监控埋点）

```python
# app/tools/base.py
from app.api.monitor import monitor

class BaseTravelTool(BaseTool):
    cache_ttl: int = 1800
    provider: BaseProvider           # MockProvider | RealProvider

    async def _arun(self, **kwargs) -> dict:
        # 1) 推送工具开始事件 → WebSocket
        monitor.report_tool(self.name, kwargs)

        cache_key = self._make_key(kwargs)
        if cached := await cache.get(cache_key):
            monitor.report_tool_end(self.name, summary="hit cache")
            return cached
        try:
            result = await self.provider.fetch(**kwargs)
            await cache.set(cache_key, result, self.cache_ttl)
            monitor.report_tool_end(self.name, summary=f"got {len(result)} items")
            return result
        except Exception as e:
            logger.warning(f"{self.name} provider={self.provider.name} failed: {e}")
            if self.provider.fallback:
                return await self.provider.fallback.fetch(**kwargs)
            monitor.report_error(self.name, str(e))
            raise
```

### 5.2 工具清单

| 工具 | Mock 实现 | 真实 API（生产） | 输入 | 输出 |
|------|-----------|------------------|------|------|
| `WeatherTool` | 基于历史季节的伪随机生成 | 和风天气（国内）/ OpenWeatherMap（海外） | city, date_range | `{date, temp_high, temp_low, condition, rain_prob}` |
| `FlightTool` | Faker 生成 3~5 个候选 | **Amadeus Flight Offers**（海外）/ **携程开放平台 / 去哪儿** （国内）/ **Skyscanner RapidAPI** | from, to, date, pax | top-K `{airline, flight_no, depart_time, arrive_time, duration, price, stops}` |
| `HotelTool` | Faker 生成 5~10 个候选 | **Booking.com Affiliate / RapidAPI** / **Agoda** / **携程酒店 API** | city, checkin, checkout, pax, theme | top-K `{name, area, price, rating, kid_friendly, lng, lat, image_url}` |
| `POITool` | 离线 JSON 知识库（80 个热门城市） | **高德地图 Place Search**（国内）/ **TripAdvisor Content API**（海外）/ **Google Places API** | city, theme, kid? | `{name, type, lng, lat, rating, duration_minutes, ticket_price, opening_hours}` |
| `RouteTool` | 基于 lng/lat 估算直线距离 + 倍率 | **高德路径规划**（国内）/ **Google Directions API**（海外） | poi_a, poi_b, mode | `{distance_km, duration_minutes}` |
| `CurrencyTool` | 固定汇率表 | **exchangerate.host**（免费） | base, target | rate |

### 5.3 真实 API 接入详细方案

> 上线时通过 `USE_MOCK_TOOLS=false` 切换；以下为各 Provider 的接入要点。

#### 5.3.1 机票 — Amadeus Flight Offers Search（海外首选）

- **文档**: https://developers.amadeus.com/self-service/category/flights
- **认证**: OAuth2 Client Credentials（`AMADEUS_API_KEY` + `AMADEUS_API_SECRET`）
- **关键端点**: `GET /v2/shopping/flight-offers`
- **配额**: Test 环境免费 2000 次/月；生产付费按调用计费
- **限流**: 10 QPS，用 token bucket 限流
- **字段映射**:
  | Amadeus 字段 | TripState 字段 |
  |--------------|----------------|
  | `itineraries[].segments[].carrierCode + number` | `flight_no` |
  | `itineraries[].segments[].departure.at` | `depart_time` |
  | `price.total` (EUR) | `price` (转 CNY) |

#### 5.3.2 机票 — 携程开放平台（国内首选）

- **文档**: https://open.ctrip.com/
- **认证**: 商家入驻审核（5~15 工作日），获取 `appId` + `secretKey`，签名算法 HMAC-SHA256
- **关键端点**: `POST /flight/search`
- **配额**: 根据合作等级，初期约 10 万次/天
- **风险**: 审核周期长，建议先用 Amadeus 做主，国内航线再走携程

#### 5.3.3 酒店 — Booking.com Affiliate Partner（海外首选）

- **文档**: https://developers.booking.com/connectivity/docs/affiliate-api
- **认证**: 注册 Affiliate 账号 + 申请 API 权限
- **关键端点**: `GET /hotels/search`
- **限制**: 必须显示 Booking.com 来源；不能缓存价格超过 24h

#### 5.3.4 酒店 — Agoda / 携程（备选）

- Agoda Affiliate: https://partners.agoda.com/，申请较快（1~3 天）
- 携程酒店：与机票同入驻流程

#### 5.3.5 POI — 高德地图 Web 服务 API（国内首选）

- **文档**: https://lbs.amap.com/api/webservice/summary
- **认证**: `AMAP_KEY`（个人开发者免费 30 万次/天）
- **关键端点**:
  - `GET /v3/place/text`（关键词搜索）
  - `GET /v3/place/around`（周边搜索）
  - `GET /v3/direction/walking`（步行路径，给 RouteTool 用）

#### 5.3.6 POI — TripAdvisor Content API（海外首选）

- **文档**: https://www.tripadvisor.com/developers
- **认证**: 申请 Content API key（需审核，免费 5000 次/月起）
- **限制**: 必须显示 TripAdvisor 评分和链接

#### 5.3.7 天气 — 和风天气（国内首选）

- **文档**: https://dev.qweather.com/
- **认证**: `QWEATHER_KEY`（开发者免费 1000 次/天）
- **关键端点**:
  - `GET /v7/weather/7d`（7 天预报）
  - `GET /v7/weather/15d`（付费）

#### 5.3.8 天气 — OpenWeatherMap（海外首选）

- **文档**: https://openweathermap.org/api
- **认证**: `OWM_KEY`（免费版 1000 次/天）
- **关键端点**: `GET /data/3.0/onecall`（含未来 8 天）

#### 5.3.9 切换策略 (Provider Routing)

```python
# app/tools/factory.py
def select_provider(tool: str, destination: str) -> str:
    if settings.USE_MOCK_TOOLS:
        return "mock"
    is_domestic = is_china_city(destination)
    return {
        ("weather", True):  "qweather",
        ("weather", False): "openweather",
        ("flight",  True):  "ctrip",
        ("flight",  False): "amadeus",
        ("hotel",   True):  "ctrip",
        ("hotel",   False): "booking",
        ("poi",     True):  "amap",
        ("poi",     False): "tripadvisor",
    }[(tool, is_domestic)]
```

#### 5.3.10 Mock-to-Real 切换检查清单

- [ ] 真实 API key 已配置到 Secret Manager / `.env`
- [ ] 各 Provider 的字段映射单测通过（输入/输出 schema 与 Mock 等价）
- [ ] 限流配置（per-tool、per-provider）已设置
- [ ] 缓存 TTL 满足平台 ToS（Booking 价格 ≤ 24h 等）
- [ ] 错误率告警阈值：单 provider 5xx > 5% 时自动降级到 fallback provider
- [ ] 在 staging 环境跑过完整 e2e（5 天行程）

### 5.4 Mock 数据生成器

```
app/tools/mocks/
├── mock_weather.py
├── mock_flight.py
├── mock_hotel.py
├── mock_poi.py
└── fixtures/
    └── poi/
        ├── osaka.json
        ├── beijing.json
        ├── tokyo.json
        └── ...
```

Mock 数据原则：
- **结构与真实 API 一致**（共用 Pydantic Model）
- **随机但稳定**：相同输入返回相同输出（hash 种子），便于 e2e 测试
- PDF 中带"演示数据"水印

### 5.5 缓存策略

- Key: `tool_name + provider + sha1(canonical(kwargs))`
- TTL：天气 6h / 机票/酒店 30min / POI 24h
- 存储：`cachetools.TTLCache`（进程内，无 Redis 依赖）

---

## 6. Prompt 设计

### 6.1 `parse_intent`（结构化抽取）

```text
你是旅行偏好抽取器。从用户输入中抽取结构化字段，缺失字段输出 null。
输出 JSON：
{
  "budget_per_person": number | null,
  "must_visit": [string],
  "avoid": [string],
  "pace": "relaxed" | "balanced" | "intense" | null,
  "with_kids": boolean | null,
  "with_elder": boolean | null,
  "diet": [string],
  "transport_pref": "self_drive" | "public" | "taxi" | null
}
用户输入：{bot_user_input}
```

### 6.2 `plan_itinerary`（行程编排）

```text
你是资深旅行规划师。给定以下材料，生成 {days_num} 天的行程。

【目的地】{destination}
【人数】{people_num}
【主题】{travel_theme}
【日期与天气】{weather}
【候选 POI（按片区聚类）】{pois_clustered}
【约束】{constraints}

要求：
1. 每天划分为 上午 / 中午 / 下午 / 晚上 四个时段。
2. 同一天的 POI 应在同一片区，避免长距离折返。
3. 雨天优先安排室内 POI。
4. 主题为"亲子"时降低强度，单日步行距离 ≤ 5km。
5. 输出 JSON 数组，元素为 DayPlan。
```

### 6.3 `parse_refine_intent`

```text
你是旅行助手的指令解析器。用户已经有一份 {days_num} 天的行程，现在希望调整。

【当前行程摘要】{current_itinerary_summary}
【用户调整指令】{refine_request}

请输出 JSON：
{
  "type": "swap_poi" | "rework_day" | "change_hotel" | "change_flight"
        | "change_pace" | "change_theme" | "change_budget"
        | "extend_days" | "freeform",
  "targets": [string],
  "payload": { "new_pace": "relaxed", "new_budget": 8000, ... }
}
```

### 6.4 `review_plan`

```text
作为审稿编辑，检查行程是否存在问题：
- 同一天 POI 跨片区导致来回奔波
- 餐饮与景点冲突 / 营业时间冲突
- 天气与活动不匹配（雨天户外）
- 主题契合度低
- 预算严重超支

输出：
{ "passed": bool, "issues": [string], "suggestions": [string] }
```

---

## 7. PDF 渲染设计

### 7.1 文档结构

1. 封面：目的地大图 + 标题 + 日期 + 出行人数
2. 概览页：路线缩略图 + 关键数字
3. 行程页（每天一节）：天气 + 时段表 + POI 卡片 + 餐饮推荐 + 当日交通 tips
4. 机票页 / 酒店页 / 预算页 / 实用信息页
5. 封底：生成时间 + **版本号** + 免责声明

### 7.2 实现

```python
# app/services/pdf_renderer.py
from weasyprint import HTML, CSS

def render_pdf(plan, output_path):
    html = jinja_env.get_template("trip_report.html.j2").render(plan=plan)
    HTML(string=html, base_url=ASSETS_DIR).write_pdf(
        output_path,
        stylesheets=[CSS(filename=CSS_FILE)],
    )
```

- 模板：`templates/trip_report.html.j2` / `trip_report.css`
- 字体：Docker 中预装 `fonts-noto-cjk` 解决中文显示
- Mock 模式下渲染水印 "DEMO DATA — 演示数据，请勿用于真实出行"
- PDF 输出到 `output/session_{thread_id}/trip_v{N}.pdf`，前端通过 `/api/download` 拉取

---

## 8. 后端项目结构（对齐 DeepSearchResearcher）

```
TravelPlanningAgent/
├── DESIGN.md
├── README.md
├── pyproject.toml / requirements.txt
├── .env.example
├── docker-compose.yml
├── Dockerfile
│
├── api/                         # FastAPI 服务层
│   ├── server.py                # 入口（REST + WebSocket）
│   ├── monitor.py               # 单例 ToolMonitor，跨协程定向推送
│   ├── context.py               # ContextVar(session_dir, thread_id)
│   ├── connection_manager.py    # WebSocket 连接管理
│   └── logger.py
│
├── agent/                       # 智能体编排层
│   ├── plan_agent.py            # 入口：run_plan_agent(input, thread_id)
│   ├── refine_agent.py          # 入口：run_refine_agent(refine_request, thread_id)
│   ├── plan_graph.py            # build_plan_graph()
│   ├── refine_graph.py          # build_refine_graph()
│   ├── state.py                 # TripState
│   ├── checkpointer.py          # InMemorySaver 工厂
│   ├── llm.py                   # LLM Provider
│   ├── load_prompts.py          # YAML 提示词加载
│   └── nodes/
│       ├── validate.py
│       ├── parse_intent.py
│       ├── parse_refine_intent.py
│       ├── route_refine_dispatcher.py
│       ├── load_previous_state.py
│       ├── fetch_weather.py
│       ├── fetch_flights.py
│       ├── fetch_hotels.py
│       ├── fetch_pois.py
│       ├── cluster_pois.py
│       ├── plan_itinerary.py
│       ├── estimate_budget.py
│       ├── review_plan.py
│       ├── render_pdf.py
│       └── finalize.py
│
├── tools/                       # 工具集（统一注入 monitor）
│   ├── base.py
│   ├── factory.py               # build_xxx_tool() + provider 路由
│   ├── cache.py                 # TTLCache
│   ├── weather_tool.py
│   ├── flight_tool.py
│   ├── hotel_tool.py
│   ├── poi_tool.py
│   ├── route_tool.py
│   ├── currency_tool.py
│   ├── pdf_tool.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── amadeus.py
│   │   ├── booking.py
│   │   ├── ctrip.py
│   │   ├── amap.py
│   │   ├── tripadvisor.py
│   │   ├── qweather.py
│   │   └── openweather.py
│   └── mocks/
│       ├── mock_weather.py
│       ├── mock_flight.py
│       ├── mock_hotel.py
│       ├── mock_poi.py
│       └── fixtures/
│
├── prompt/
│   └── prompts.yaml             # 集中式提示词
│
├── models/                      # Pydantic 业务模型
│   ├── trip.py
│   ├── poi.py
│   ├── flight.py
│   ├── hotel.py
│   ├── weather.py
│   └── refine.py                # RefineIntent
│
├── services/
│   ├── pdf_renderer.py          # WeasyPrint 渲染
│   ├── storage.py               # 本地 / OSS
│   └── trip_repo.py             # SQLite 任务/版本元数据（轻量）
│
├── templates/
│   ├── trip_report.html.j2
│   ├── trip_report.css
│   └── assets/
│
├── output/                      # 按 session 隔离的输出
│   └── session_{thread_id}/
│       ├── trip_v1.pdf
│       └── ...
│
├── updated/                     # 用户上传文件（如自定义 POI 列表、签证扫描件）
│   └── session_{thread_id}/
│
├── ui/                          # Vue 3 前端（见 §9）
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── scripts/
    ├── run_local.sh
    ├── sample_request.json
    └── sample_refine.json
```

---

## 9. Web 前端技术方案 (Vue 3 + TS + Vite)

### 9.1 设计目标

- 视觉风格参考 Kiro / DeepSearchResearcher：**简洁、深色优雅、对话式**
- 首屏为欢迎页（中央输入框）；提交后转换为聊天布局
- 实时展示 Agent 的**思维链**和**工具调用**（折叠面板形式）
- 多轮对话：每轮 user / ai 消息显示在同一会话流，支持 refine
- 历史会话列表（左侧抽屉）：基于 localStorage + 后端 `thread_id`
- 文件区（右侧抽屉）：实时显示 `output/session_{thread_id}/` 中的 PDF / 其他生成物
- 全局基于 WebSocket，刷新页面后自动重连

### 9.2 技术栈

| 类别 | 选型 | 备注 |
|------|------|------|
| 框架 | **Vue 3 + Composition API** | `<script setup lang="ts">` |
| 语言 | TypeScript 5+ | 严格模式 |
| 构建 | Vite | 热重载 / 极速冷启 |
| 状态管理 | **Pinia** | 比 vuex 更轻；多组件共享聊天历史 / 设置 |
| HTTP | axios | REST 调用（创建任务、上传、下载） |
| WebSocket | **原生 `WebSocket` API** | 与后端 `/ws/{thread_id}` 对接，自动重连 |
| Markdown | marked + DOMPurify | 渲染 AI 回复（XSS 防护） |
| 表单 / 输入参数 | 原生 + 自定义组件 | 不引入大型 UI 库，保持 Kiro 风格 |
| 图标 | 内联 SVG | 与 DeepSearchResearcher 一致 |
| 样式 | **CSS Variables + Scoped CSS** | 深色 / 浅色主题切换 |
| 国际化 | vue-i18n（可选，二期） | 中文为主，后续加英文 |

### 9.3 页面结构

```
┌─────────────────────────────────────────────────────────────────┐
│ ┌─[左侧抽屉]──┐ ┌─[主内容]──────────────────┐ ┌─[右侧抽屉]──┐  │
│ │ History     │ │  Welcome / Chat Stream     │ │ Files       │  │
│ │ - 大阪 5天  │ │  ┌──────────────────────┐  │ │ trip_v1.pdf │  │
│ │ - 北京 3天  │ │  │ user: "5 天大阪..."   │  │ │ trip_v2.pdf │  │
│ │ - ...       │ │  │ ai:                  │  │ │ map.png     │  │
│ │ + 新会话    │ │  │  ▼ 思维链 (5 步)      │  │ │             │  │
│ │             │ │  │   🔧 fetch_weather   │  │ │             │  │
│ │             │ │  │   🔧 fetch_flights   │  │ │             │  │
│ │             │ │  │   🤖 plan_itinerary  │  │ │             │  │
│ │             │ │  │  Markdown 文本回复    │  │ │             │  │
│ │             │ │  │  📄 trip_v1.pdf 卡片 │  │ │             │  │
│ │             │ │  └──────────────────────┘  │ │             │  │
│ │             │ │  ┌──────────────────────┐  │ │             │  │
│ │             │ │  │ user: "改第3天"      │  │ │             │  │
│ │             │ │  │ ai: ... (refine)     │  │ │             │  │
│ │             │ │  └──────────────────────┘  │ │             │  │
│ │             │ │                            │ │             │  │
│ │             │ │  ┌──── Input ───────────┐  │ │             │  │
│ │             │ │  │ 表单（折叠）         │  │ │             │  │
│ │             │ │  │ ┌──────────────────┐ │  │ │             │  │
│ │             │ │  │ │ 📎 输入框 [发送] │ │  │ │             │  │
│ │             │ │  │ └──────────────────┘ │  │ │             │  │
│ │             │ │  └──────────────────────┘  │ │             │  │
│ └─────────────┘ └────────────────────────────┘ └─────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 9.4 前端目录结构

```
ui/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── public/
│   └── favicon.svg
└── src/
    ├── main.ts
    ├── App.vue
    ├── style.css                       # 全局样式 + CSS 变量
    ├── api/
    │   ├── http.ts                     # axios 实例 + baseURL
    │   ├── trip.ts                     # createTrip / refine / listVersions / downloadPdf
    │   └── ws.ts                       # WebSocket 客户端（重连 + 事件路由）
    ├── stores/
    │   ├── chat.ts                     # Pinia: messages / status / threadId
    │   ├── history.ts                  # Pinia: 会话列表（localStorage 持久化）
    │   └── settings.ts                 # Pinia: 主题 / 语言 / Mock 开关
    ├── components/
    │   ├── WelcomeScreen.vue           # 首屏欢迎页（标题 + 中央输入）
    │   ├── ChatStream.vue              # 聊天流容器
    │   ├── MessageUser.vue             # 用户消息气泡
    │   ├── MessageAi.vue               # AI 消息（含思维链 + 文件卡片）
    │   ├── ThoughtProcess.vue          # 思维链折叠面板（<details>）
    │   ├── ToolCallCard.vue            # 单个工具调用卡片
    │   ├── NodeCallCard.vue            # 单个 LangGraph 节点卡片
    │   ├── FileCard.vue                # PDF / 文件下载卡片
    │   ├── InputBox.vue                # 输入框（含表单、上传、发送）
    │   ├── TripFormInline.vue          # 内联表单（destination / days / people / theme）
    │   ├── HistorySidebar.vue          # 左侧历史会话列表
    │   ├── FilesSidebar.vue            # 右侧文件列表
    │   └── icons/                      # 内联 SVG
    ├── composables/
    │   ├── useWebSocket.ts             # WS 自动重连 + 事件分发
    │   ├── useTripTask.ts              # 提交 / 监听 / 完成
    │   └── useScrollToBottom.ts
    └── types/
        ├── chat.ts                     # Message / LogItem / FileItem
        ├── ws.ts                       # WSEvent / Payload
        └── trip.ts                     # TripRequest / TripVersion
```

### 9.5 核心数据模型（前端）

```typescript
// src/types/chat.ts
export interface LogItem {
  type: 'tool' | 'node' | 'agent' | 'info' | 'success' | 'error'
  title: string                       // "调用工具：fetch_weather"
  details?: any
  duration_ms?: number
  timestamp: string
}

export interface FileItem {
  name: string
  path: string
  url: string
  size?: number
  mtime?: number
}

export interface Message {
  role: 'user' | 'ai' | 'system'
  content: string                     // markdown
  logs?: LogItem[]
  files?: FileItem[]
  version?: number                    // 用于显示 "v1 / v2"
  timestamp: number
  status?: 'pending' | 'streaming' | 'done' | 'error'
}

// src/types/ws.ts
export type WSEvent =
  | { event: 'session_created';   data: { path: string } }
  | { event: 'node_start';        data: { node: string; ts: number } }
  | { event: 'node_end';          data: { node: string; duration_ms: number; summary?: string } }
  | { event: 'tool_start';        data: { tool_name: string; args?: any } }
  | { event: 'tool_end';          data: { tool_name: string; summary?: string } }
  | { event: 'review_iteration';  data: { iteration: number; passed: boolean; feedback?: string } }
  | { event: 'partial_thought';   data: { text: string } }       // 流式思维链
  | { event: 'task_result';       data: { result: string; version: number; pdf_url?: string } }
  | { event: 'error';             data: { message: string; node?: string } }
```

### 9.6 WebSocket 客户端（核心实现）

```typescript
// src/api/ws.ts
import type { WSEvent } from '@/types/ws'

export class TripWS {
  private ws: WebSocket | null = null
  private threadId: string
  private url: string
  private reconnectDelay = 3000
  private listeners = new Map<string, Set<(e: WSEvent) => void>>()
  private alive = true

  constructor(threadId: string, baseUrl = import.meta.env.VITE_WS_BASE) {
    this.threadId = threadId
    this.url = `${baseUrl}/ws/${threadId}`
    this.connect()
  }

  private connect() {
    this.ws = new WebSocket(this.url)
    this.ws.onopen = () => console.log('[WS] connected', this.threadId)
    this.ws.onmessage = (e) => {
      try {
        const payload: WSEvent = JSON.parse(e.data)
        this.dispatch(payload)
      } catch (err) {
        console.error('[WS] parse error', err)
      }
    }
    this.ws.onclose = () => {
      if (this.alive) setTimeout(() => this.connect(), this.reconnectDelay)
    }
    this.ws.onerror = (e) => console.error('[WS] error', e)
  }

  on(event: string, fn: (e: WSEvent) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set())
    this.listeners.get(event)!.add(fn)
    return () => this.listeners.get(event)!.delete(fn)
  }

  private dispatch(e: WSEvent) {
    this.listeners.get(e.event)?.forEach(fn => fn(e))
    this.listeners.get('*')?.forEach(fn => fn(e))
  }

  close() {
    this.alive = false
    this.ws?.close()
  }
}
```

### 9.7 关键交互流程

#### 9.7.1 首次规划

```
1. 用户在 WelcomeScreen 输入 / 填表 → 点击 [发送]
2. 前端生成 thread_id（uuid 或用户填写的 conversation_name）
3. 建立 WebSocket /ws/{thread_id}（先 ws 后 http，确保不丢消息）
4. POST /api/trip { destination, days_num, ..., thread_id }
5. 后端返回 { trip_id, status: "started", thread_id, version: 1 }
6. 前端立即在 ChatStream 插入：
   - 用户消息（用户输入文本 / 表单摘要）
   - 空 AI 消息占位（status=streaming）
7. WebSocket 推送 session_created / node_start / tool_start / ...
   每个事件追加到当前 AI 消息的 logs[] 中
8. WebSocket 推送 task_result：
   - 设置 ai_message.content = result
   - 推入 files[]: trip_v1.pdf
   - status=done
9. 右侧文件抽屉自动刷新
```

#### 9.7.2 多轮调整 (Refine)

```
1. 用户继续在同一会话输入 "把第3天改成室内活动"
2. 前端 POST /api/trip/{thread_id}/refine { instruction }
3. 后端返回 { trip_id, version: 2, status: "started" }
4. 复用同一个 WebSocket 连接（thread_id 不变）
5. 后端事件流与首次规划一致
6. 前端在 ChatStream 追加新一轮 user/ai 消息
7. 文件抽屉刷新出现 trip_v2.pdf
```

#### 9.7.3 历史会话恢复

```
1. localStorage 中保存 {thread_id, title, last_active, summary}[]
2. 用户从 HistorySidebar 点击某个会话
3. 切换 chat store 的 currentThreadId
4. 关闭旧 WebSocket，建立新的 /ws/{new_thread_id}
5. （可选）GET /api/trip/{thread_id}/history 拉取历史消息（如未持久化则只显示新轮次）
```

> **注意**: 因为后端 InMemorySaver 不持久化，所以历史会话在**进程重启后**只能从前端 localStorage 看标题，但无法继续 refine 旧 state。这一点会在 UI 上显式提示：「该会话已过期，新的指令会重新规划」。

### 9.8 Kiro 风格的视觉规范

| 元素 | 设计 |
|------|------|
| 主色 | 深色背景 `#131314`；强调色蓝紫渐变 `#4E75F6 → #E3557A`（与参考一致） |
| 字体 | "Google Sans", "Roboto", -apple-system, "Helvetica Neue", sans-serif |
| 圆角 | 输入框 32px / 卡片 12px / 气泡 18px（user 右下角 4px 缺口） |
| 思维链 | `<details>` 折叠，summary 含 spinner（运行中），打开后展示步骤树 |
| 工具卡片 | 圆角 8px 浅灰底（dark mode），工具名 + 参数 JSON 折叠 |
| 文件卡片 | 图标 + 文件名 + 类型标签，点击下载或预览 |
| 运行状态 | 输入框右上小圆点：灰=空闲 / 蓝呼吸=运行 / 红=错误 |
| 主题切换 | CSS 变量 + `data-theme` 切换；默认 dark |

### 9.9 前端环境变量

```env
# ui/.env
VITE_API_BASE=http://localhost:8000
VITE_WS_BASE=ws://localhost:8000
```

### 9.10 开发与构建

```bash
# 开发
cd ui && npm install && npm run dev      # → http://localhost:5173

# 构建（生成 dist/，由 FastAPI 通过 StaticFiles 挂载）
cd ui && npm run build
# 后端启动时通过 app.mount("/", StaticFiles(directory="ui/dist", html=True))
```

### 9.11 一键启动（docker-compose）

```yaml
# docker-compose.yml
services:
  backend:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./output:/app/output
      - ./updated:/app/updated

  frontend:
    image: node:20-alpine
    working_dir: /ui
    volumes: ["./ui:/ui"]
    command: sh -c "npm install && npm run dev -- --host 0.0.0.0"
    ports: ["5173:5173"]
    depends_on: [backend]
```

---

## 10. 关键接口

### 10.1 REST 接口

```http
# 1. 创建规划任务
POST /api/trip
Content-Type: application/json
{
  "conversation_name": "trip_2026_summer",   // 可选；缺省为 server 生成 uuid
  "bot_user_input": "想带 3 岁小孩，避免长途车程",
  "destination": "大阪",
  "departure": "上海",
  "days_num": 5,
  "people_num": 3,
  "start_date": "2026-07-15",
  "travel_theme": "亲子"
}
→ 200 OK
{
  "trip_id": "trp_abc123",
  "thread_id": "trip_2026_summer",
  "status": "started",
  "version": 1
}
```

```http
# 2. 多轮调整
POST /api/trip/{thread_id}/refine
{
  "instruction": "把第3天改成室内活动，酒店换成离心斋桥近的"
}
→ 202 Accepted
{
  "trip_id": "trp_abc123",
  "thread_id": "trip_2026_summer",
  "status": "started",
  "version": 2,
  "based_on_version": 1
}
```

```http
# 3. 查询版本列表
GET /api/trip/{thread_id}/versions
→ { "versions": [
     {"version":1,"created_at":"...","pdf_path":"..."},
     {"version":2,"created_at":"...","pdf_path":"..."}
   ]}
```

```http
# 4. 文件列表
GET /api/files?path=/abs/path/output/session_xxx
→ { "files": [...] }

# 5. 文件下载（路径白名单校验）
GET /api/download?path=/abs/path/output/session_xxx/trip_v1.pdf
→ application/pdf

# 6. 上传（自定义 POI 等）
POST /api/upload  multipart/form-data: thread_id + files[]
```

### 10.2 WebSocket

```http
WS /ws/{thread_id}
```

**服务器 → 客户端 事件清单**：

| 事件 | payload |
|------|---------|
| `session_created` | `{ path: "output/session_xxx" }` |
| `node_start` | `{ node, ts }` |
| `node_end` | `{ node, duration_ms, summary? }` |
| `tool_start` | `{ tool_name, args }` |
| `tool_end` | `{ tool_name, summary? }` |
| `review_iteration` | `{ iteration, passed, feedback }` |
| `partial_thought` | `{ text }`（可选：流式思维链）|
| `task_result` | `{ result, version, pdf_url }` |
| `error` | `{ message, node? }` |

**客户端 → 服务器**：仅心跳 `ping`，业务请求走 REST。

### 10.3 同步 Debug 端点（仅开发）

```http
POST /api/debug/trip:plan-sync
```

直接同步执行图，方便本地调试。

---

## 11. 错误与降级

| 场景 | 策略 |
|------|------|
| 必填字段缺失 | 返回 422，不进入图 |
| 单一 fetch 工具失败 | 节点内 try/except，state.errors 累加，使用降级值，PDF 中标"信息暂缺" |
| LLM 限流 / 超时 | 指数退避重试 3 次；触发 fallback Provider；review_plan 失败时直接通过原计划 |
| review_plan 不通过 | 最多回环 2 次，超出后保留最后一版并附"待优化建议" |
| Refine 解析失败 | 回退为 `freeform`，原始指令注入 plan prompt |
| Refine 中途失败 | 不污染当前版本；返回 failed 并保留 v_n 不变 |
| PDF 渲染失败 | 回退为 Markdown 文件，HTTP 返回降级响应 |
| WebSocket 断连 | 前端 3s 自动重连，复用 `thread_id` |
| 进程重启 | InMemorySaver State 丢失：前端显示"会话已过期"提示，新指令重新走 plan_graph |

---

## 12. 可观测

- **Trace**: LangSmith（每次 graph run = 1 trace；每个 node = 1 span；refine 与 plan 区分 metadata）
- **Metrics**（结构化日志聚合，初期不引入 Prometheus）：
  - `trip_plan_total{status,mode=plan|refine}` / `trip_plan_duration_seconds`
  - `tool_call_total{tool,provider,status}` / `tool_call_duration_seconds`
  - `llm_tokens_total{model,kind=prompt|completion}` / `llm_fallback_total{from,to,reason}`
  - `refine_intent_total{type}`
- **Log**: Loguru 结构化 JSON，`trip_id + thread_id + version` 作为 trace key

---

## 13. 安全与合规

- API Key 仅放 `.env` / Secret Manager
- 用户输入做长度限制 + Prompt Injection 防护（在 LLM 调用前对 user 段做 XML 包裹）
- WebSocket 鉴权（M9）：`?token=...` 校验 JWT；公网部署必做
- 路径下载白名单：`/api/download` 必须以 `output/` 为前缀，防穿越
- 输出 PDF 含免责声明：行程仅供参考、价格非实时
- Mock 模式 PDF 显著水印
- 第三方数据使用遵守 ToS（Booking 价格缓存 ≤ 24h 等）
- 前端 marked 渲染前过 DOMPurify，防 XSS

---

## 14. 里程碑

| 阶段 | 交付物 | 估时 |
|------|--------|------|
| M1 — 后端骨架 | FastAPI + LangGraph plan 图 + InMemorySaver + ContextVar + 单 Mock 节点跑通 | 1d |
| M2 — Mock 工具 | 4 个 Mock Provider + 字段 schema 与真实 API 对齐 | 1.5d |
| M3 — 编排 | parse_intent / cluster_pois / plan_itinerary / review_plan | 2d |
| M4 — PDF | Jinja 模板 + WeasyPrint + 中文字体 + 水印 | 1d |
| M5 — Refine | refine 子图 + RefineIntent + dispatcher + API | 2d |
| M6 — Monitor & WebSocket | ConnectionManager + Monitor 单例 + 9 类事件 | 1d |
| **M7 — 前端骨架** | Vue 3 + Vite + 路由 + Pinia + ChatStream / WelcomeScreen | 1.5d |
| **M8 — 前端实时** | WebSocket 客户端 + 思维链折叠 + 工具卡片 + 文件区 | 2d |
| **M9 — 前端历史 / 多轮** | HistorySidebar + 多轮 refine UI + localStorage 持久化 | 1d |
| M10 — 观测 | LangSmith + 日志 + 关键指标 | 0.5d |
| M11 — 加固 | 错误降级、Prompt 注入防护、压测、WS 鉴权 | 1d |
| M12 — 真实 API（按需） | 接入 Amadeus / 高德 / 和风 / Booking | 3~5d（含审核等待） |

合计骨架 + 多轮 + Mock + 前端 ≈ **14.5 人日**；真实 API 接入按平台审核进度独立排期。

---

## 15. 已决策事项与剩余风险

### 15.1 已决策（见 §0 决策日志）

1. ✅ LLM 默认 GPT-4o
2. ✅ 机票 / 酒店初期 Mock，真实 API 方案见 §5.3
3. ✅ 支持多轮调整（refine 子图）
4. ✅ 主架构异步（asyncio + WebSocket）
5. ✅ Checkpointer 使用 `InMemorySaver`
6. ✅ 新增 Vue 3 前端
7. ✅ 整体架构对齐 DeepSearchResearcher

### 15.2 剩余风险

- **InMemorySaver 重启丢 State**：前端需明确提示用户；如二期需要持久化可平滑切换 `SqliteSaver`
- **真实 API 审核周期**：携程 / Booking / TripAdvisor 审核 1~3 周，需提前并行启动
- **多 worker 部署**：当前架构单 worker 简单，扩展时需要按 `thread_id` 哈希 sticky session
- **国际化目的地**：货币、时区、签证信息（M12 之后）
- **PDF 国际化字体**：日韩 / 阿拉伯目标地名需对应字体集
- **多轮调整边界**：refine 跨度过大（如 5→10 天）阈值化处理，超过后直接走 plan_graph
- **成本监控**：GPT-4o 单次完整规划 ≈ 30K~50K tokens，需要预算告警

---

## 16. 附：最小可运行示例

### 16.1 LangGraph 图（伪代码）

```python
# app/agent/plan_graph.py
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from app.agent.state import TripState
from app.agent.checkpointer import get_checkpointer
from app.agent.nodes import (
    validate_input, parse_intent,
    fetch_weather, fetch_flights, fetch_hotels, fetch_pois,
    cluster_pois, plan_itinerary, estimate_budget,
    review_plan, render_pdf, finalize,
)

def build_plan_graph():
    g = StateGraph(TripState)
    for n in [validate_input, parse_intent, fetch_weather, fetch_flights,
              fetch_hotels, fetch_pois, cluster_pois, plan_itinerary,
              estimate_budget, review_plan, render_pdf, finalize]:
        g.add_node(n.__name__, n)

    g.add_edge(START, "validate_input")
    g.add_edge("validate_input", "parse_intent")

    for n in ["fetch_weather", "fetch_flights", "fetch_hotels", "fetch_pois"]:
        g.add_edge("parse_intent", n)
        g.add_edge(n, "cluster_pois")

    g.add_edge("cluster_pois", "plan_itinerary")
    g.add_edge("plan_itinerary", "estimate_budget")
    g.add_edge("estimate_budget", "review_plan")

    g.add_conditional_edges(
        "review_plan",
        lambda s: "plan_itinerary" if (not s["review_passed"] and s["retry_count"] < 2) else "render_pdf",
    )
    g.add_edge("render_pdf", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=get_checkpointer())
```

### 16.2 Agent 入口（异步执行 + ContextVar + Monitor）

```python
# app/agent/plan_agent.py
import asyncio
from pathlib import Path
from app.agent.plan_graph import build_plan_graph
from app.api.context import set_session_context, set_thread_context, reset_session_context
from app.api.monitor import monitor

plan_graph = build_plan_graph()
PROJECT_ROOT = Path(__file__).parents[2].resolve()

async def run_plan_agent(input_data: dict, thread_id: str):
    session_dir = PROJECT_ROOT / "output" / f"session_{thread_id}"
    session_dir.mkdir(parents=True, exist_ok=True)

    s_token = set_session_context(str(session_dir))
    t_token = set_thread_context(thread_id)
    monitor.report_session_dir(str(session_dir))

    config = {"configurable": {"thread_id": thread_id}}

    try:
        async for chunk in plan_graph.astream(input_data, config=config):
            for node_name, state in chunk.items():
                # 节点级事件已通过 monitor 在节点内部上报
                # 这里仅做兜底日志
                pass
        # 任务结束，最后取一次完整 state
        final = await plan_graph.aget_state(config)
        monitor.report_task_result(final.values.get("summary", ""))
    except Exception as e:
        monitor.report_error("plan_graph", str(e))
    finally:
        reset_session_context(s_token, t_token)
```

### 16.3 FastAPI 入口（含 WebSocket）

```python
# api/server.py
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.api.connection_manager import ConnectionManager
from app.api.monitor import monitor
from app.agent.plan_agent import run_plan_agent
from app.agent.refine_agent import run_refine_agent

app = FastAPI(title="Travel Planning Agent")
manager = ConnectionManager()

@app.on_event("startup")
async def _startup():
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    monitor.set_websocket_manager(manager)

@app.post("/api/trip")
async def create_trip(req: TripRequest):
    thread_id = req.conversation_name or str(uuid.uuid4())
    asyncio.create_task(run_plan_agent(req.dict(), thread_id))
    return {"trip_id": str(uuid.uuid4()), "thread_id": thread_id, "status": "started", "version": 1}

@app.post("/api/trip/{thread_id}/refine")
async def refine_trip(thread_id: str, req: RefineRequest):
    asyncio.create_task(run_refine_agent(req.instruction, thread_id))
    return {"trip_id": str(uuid.uuid4()), "thread_id": thread_id, "status": "started"}

@app.websocket("/ws/{thread_id}")
async def ws_endpoint(websocket: WebSocket, thread_id: str):
    await manager.connect(websocket, thread_id)
    try:
        while True:
            await websocket.receive_text()  # 心跳
    except WebSocketDisconnect:
        manager.disconnect(websocket, thread_id)
```

---

> 本方案 v0.3 已确认 7 项关键决策（见 §0），架构对齐 DeepSearchResearcher。
> 评审通过后按 M1 → M12 推进。M1~M11 ≈ 14.5 人日（含前端），可基于 Mock 完整跑通 + 前端实时展示；真实 API 接入按平台审核进度独立排期。
