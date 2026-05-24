# 智能旅行助手 Agent — 技术方案

> 版本: v0.2 (设计稿，含决策更新)
> 编写日期: 2026-05-24
> 适用范围: 基于 LangGraph 的旅行规划 Agent，输出行程 PDF
> 主架构: **异步任务 + SSE 进度推送 + 多轮调整 + Mock-to-Real 数据源切换**

---

## 0. 决策日志 (Decisions Log)

| # | 决策 | 状态 | 说明 |
|---|------|------|------|
| D-01 | 默认 LLM 使用 GPT-4o | ✅ 已确认 | 通过 `LLM_PROVIDER=openai` `LLM_MODEL=gpt-4o`；DeepSeek-V3 / Qwen-Max 作为兜底 |
| D-02 | 机票 / 酒店初期使用 Mock 数据 | ✅ 已确认 | 通过 `USE_MOCK_TOOLS=true` 切换；真实 API 接入方案保留在第 5 章中，可一行配置切换 |
| D-03 | 支持多轮调整 | ✅ 已确认 | 增加 `refine` 子图，按用户指令做最小化重算；State 通过 Redis Checkpointer 持久化 |
| D-04 | 主架构使用异步 | ✅ 已确认 | `POST` 立即返回 `trip_id`，通过 SSE 推送节点级进度；同步模式仅为 debug 选项 |

---

## 1. 项目目标

构建一个智能旅行助手 Agent。用户输入出发地、目的地、出行人数、天数、出行日期、主题等参数，
Agent 自动完成 **天气查询 / 机票查询 / 酒店查询 / 景点攻略 / 行程编排 / 预算估算**，
并最终生成一份可下载的 **旅行方案 PDF**；用户可通过自然语言对生成的方案做**多轮调整**。

### 1.1 核心需求

| 编号 | 需求 | 说明 |
|------|------|------|
| F-01 | 多源信息聚合 | 调用天气、机票、酒店、POI 等外部 API 获取实时数据 |
| F-02 | 智能行程编排 | 根据天数、人数、主题、POI 距离编排日程 |
| F-03 | 主题适配 | 支持亲子 / 蜜月 / 美食 / 户外 / 文化等主题，影响 POI 选择和节奏 |
| F-04 | PDF 输出 | 生成结构化 PDF，含封面、概览、日程、酒店、机票、预算、注意事项 |
| F-05 | 可观测 | 每一步可追踪（LangSmith / 自定义日志），便于调试 |
| F-06 | 失败可恢复 | 单一外部 API 失败时降级，不阻塞整体流程 |
| F-07 | **多轮调整** | 用户可对已生成方案做局部修改（换酒店、改某天、调节奏），仅重算受影响的部分 |
| F-08 | **异步执行** | 一次规划过程 30~120s，必须异步执行 + 进度可见 |

### 1.2 非功能需求

- **响应时延**：典型 case (5 天行程) p95 ≤ 60s；refine 模式 p95 ≤ 20s
- **可扩展**：节点 / 工具松耦合，新增数据源不影响主图
- **缓存**：相同查询参数 30min 内复用结果，降低外部 API 成本
- **可重入**：State 持久化 (Redis Checkpointer)，支持中断后从最近 checkpoint 恢复
- **数据源可切换**：Mock ↔ Real 通过环境变量切换，Tool 接口对图层透明

---

## 2. 输入与输出

### 2.1 输入参数（与图一一致）

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `CONVERSATION_NAME` | string | 否 | 会话标识，用于持久化 / 多轮 | `trip_2026_summer` |
| `BOT_USER_INPUT` | string | 否 | 用户自然语言补充诉求 | "想带 3 岁小孩，避免长途车程" |
| `destination` | string | **是** | 目的地（城市 / 区域） | `大阪` |
| `departure` | string | 否 | 出发地，缺省由用户补充或取常驻地 | `上海` |
| `days_num` | int | **是** | 游玩天数 | `5` |
| `people_num` | int | **是** | 出行人数 | `2` |
| `start_date` | string (YYYY-MM-DD) | 否 | 出发日期，缺省取当前日 +14d | `2026-07-15` |
| `travel_theme` | string | 否 | 主题，影响 POI 选择 | `亲子` / `美食` / `户外` |

### 2.2 输出

```jsonc
{
  "status": "success",
  "trip_id": "trip_xxx",
  "version": 2,                  // 多轮调整版本号
  "summary": "为期 5 天的大阪亲子游...",
  "pdf_url": "https://.../trip_xxx_v2.pdf",
  "pdf_path": "/data/output/trip_xxx_v2.pdf",
  "estimated_cost": { "currency": "CNY", "total": 12800, "per_person": 6400 },
  "plan": { /* 结构化行程，便于前端渲染 */ }
}
```

---

## 3. 整体架构

### 3.1 架构分层

```
┌──────────────────────────────────────────────────────┐
│                   Client (Web / Bot)                 │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP/JSON + SSE
┌────────────────────────▼─────────────────────────────┐
│               FastAPI Service Layer                  │
│   - 输入校验 / 鉴权 / 任务提交 / SSE 进度推送         │
│   - 同步 debug 端点 + 异步主流程                      │
└────────────────────────┬─────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────┐
│            Async Worker (Celery / RQ)                │
│   - 长任务执行 / 重试 / 限流                          │
└────────────────────────┬─────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────┐
│         LangGraph Agent Orchestration Layer          │
│   - StateGraph (plan / refine 两个图)                 │
│   - RedisCheckpointer (状态持久化 / 多轮)             │
│   - 统一 LLM Provider（GPT-4o + fallback）            │
└──────┬──────────┬──────────┬──────────┬──────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
   ┌───────┐ ┌────────┐ ┌────────┐ ┌─────────┐
   │Weather│ │ Flight │ │ Hotel  │ │  POI    │
   │  Tool │ │  Tool  │ │  Tool  │ │  Tool   │
   └───┬───┘ └───┬────┘ └───┬────┘ └────┬────┘
       │         │          │            │
       ▼         ▼          ▼            ▼
  ┌─────────────────────────────────────────────┐
  │  Provider Adapter Layer (Mock | Real)       │
  │  USE_MOCK_TOOLS=true → MockProvider          │
  │  USE_MOCK_TOOLS=false → RealProvider         │
  └─────────────────────────────────────────────┘
       │         │          │            │
       ▼         ▼          ▼            ▼
   外部 API (和风 / Amadeus / Booking / 高德 ...)

┌──────────────────────────────────────────────────────┐
│   PDF Render Layer (Jinja2 + WeasyPrint)             │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│   Storage: Redis (state/cache) + SQLite (jobs/PDF)   │
└──────────────────────────────────────────────────────┘
```

### 3.2 技术栈

| 类别 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | LangGraph 原生支持 |
| Agent 框架 | LangGraph 0.2+ + LangChain | 状态机模型适合工作流型 Agent |
| LLM | **OpenAI GPT-4o（默认）** / DeepSeek-V3 / Qwen-Max（备选） | 通过 LLM Provider 抽象，可替换；默认走 GPT-4o，质量优先 |
| Web 框架 | FastAPI + Uvicorn | 异步 / SSE / OpenAPI |
| 任务队列 | **Celery + Redis Broker**（主） / FastAPI BackgroundTasks（开发） | 多 worker、重试、限流，生产级 |
| 数据校验 | Pydantic v2 | 与 LangGraph State 天然集成 |
| 持久化 | Redis（State / Cache / Broker）+ SQLite（任务/结果元数据） | 轻量、易部署 |
| Checkpointer | LangGraph `RedisSaver` | 多轮调整必需 |
| PDF 渲染 | Jinja2 + WeasyPrint | HTML/CSS 模板，样式可控；中文友好 |
| 可观测 | LangSmith + Loguru + OpenTelemetry | Trace / 日志 / 指标 |
| 配置 | pydantic-settings + .env | 12-factor |
| 包管理 | uv（首选）/ poetry | 锁定版本 |
| 容器 | Docker + docker-compose | 本地与部署一致 |

### 3.3 LLM Provider 抽象

为了让"默认 GPT-4o + 兜底其他模型"在代码上可控，定义统一抽象：

```python
# app/core/llm.py
class LLMProvider(Protocol):
    async def chat(self, messages, **kwargs) -> str: ...
    async def chat_json(self, messages, schema, **kwargs) -> dict: ...

def build_llm() -> LLMProvider:
    return FallbackLLM(
        primary  = OpenAIProvider(model=settings.LLM_MODEL),         # gpt-4o
        fallback = DeepSeekProvider(model="deepseek-chat") if settings.LLM_FALLBACK_PROVIDER else None,
        retry    = ExponentialBackoff(max_attempts=3),
    )
```

`.env.example` 关键配置：

```env
# ===== LLM =====
LLM_PROVIDER=openai          # openai | deepseek | qwen
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=             # 可选，走代理时填
LLM_FALLBACK_PROVIDER=deepseek
DEEPSEEK_API_KEY=
LLM_TEMPERATURE=0.4
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=3

# ===== 数据源开关 =====
USE_MOCK_TOOLS=true          # 初期 true，上线时 false
```

**触发 fallback 的条件**：HTTP 429 / 5xx / 超时 / `RateLimitError` / `APIConnectionError`。
fallback 触发时记录 `llm_fallback_total{from,to,reason}` 指标。

---

## 4. LangGraph 工作流设计

整体由两张图组成：
- **`plan_graph`** — 首次生成完整方案
- **`refine_graph`** — 多轮调整：基于已存在的 State，按用户指令做最小化重算

两张图共享同一个 `TripState` 和同一份 Checkpointer (Redis)，通过 `conversation_name`（即 `thread_id`）关联。

### 4.1 状态定义 (`TripState`)

```python
class TripState(TypedDict, total=False):
    # ===== 输入 =====
    conversation_name: str
    bot_user_input: str
    destination: str
    departure: str | None
    days_num: int
    people_num: int
    start_date: str | None       # ISO 日期
    travel_theme: str | None

    # ===== 解析 / 中间态 =====
    parsed_intent: dict          # 由 LLM 从 bot_user_input 抽取的隐式偏好
    date_range: list[str]        # [start_date, ..., end_date]
    constraints: dict            # 预算、忌口、避免项等

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

    # ===== 反思 / 元信息 =====
    review_passed: bool
    review_feedback: str
    retry_count: int

    # ===== 多轮调整 =====
    version: int                 # 当前版本号，每次 refine +1
    history: list[VersionMeta]   # 历史版本元信息（不存全量，存差异摘要）
    refine_request: str          # 当前轮的用户指令
    refine_intent: RefineIntent  # 解析后的结构化指令
    dirty_nodes: set[str]        # 需要重算的节点集合

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
| `finalize` | 落盘 / 上传 / 推送结果 | 否 | 致命 |

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

- 用 `conversation_name` 作为 LangGraph 的 `thread_id`，从 Redis Checkpointer 加载上一版完整 `TripState`
- 用 LLM 把用户的调整指令解析成结构化的 `RefineIntent`
- 由 `route_refine_dispatcher` 决定哪些节点需要重算（写入 `dirty_nodes`），跳过其他节点
- 重算完成后，统一走 `estimate_budget` → `review_plan`(轻量) → `render_pdf` → `finalize`，并将 `version+1`

#### 4.4.2 RefineIntent 类型

```python
class RefineIntent(BaseModel):
    type: Literal[
        "swap_poi",       # 换某个 POI（最轻量，直接改 itinerary）
        "rework_day",     # 重做某一天（重跑 plan_itinerary 仅针对该天）
        "change_hotel",   # 换酒店（重跑 fetch_hotels + plan_itinerary）
        "change_flight",  # 换航班（重跑 fetch_flights）
        "change_pace",    # 调节奏（重跑 plan_itinerary）
        "change_theme",   # 改主题（重跑 fetch_pois + cluster + plan）
        "change_budget",  # 改预算（重跑 fetch_hotels + plan_itinerary）
        "extend_days",    # 加天数（重跑全部，相当于退回 plan_graph）
        "freeform",       # 自由文本（重跑 plan_itinerary，把指令注入 prompt）
    ]
    targets: list[str] = []   # 受影响的对象：日索引 / POI 名 / 酒店名 等
    payload: dict = {}        # 类型相关数据：new_constraints / new_pace 等
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
           load_previous_state          (从 Redis Checkpointer 取 v_n)
                    │
                    ▼
          parse_refine_intent           (LLM → RefineIntent)
                    │
                    ▼
        route_refine_dispatcher         (写 dirty_nodes，决定下一步)
                    │
        ┌───────────┼───────────────┬───────────┐
        ▼           ▼               ▼           ▼
   fetch_flights fetch_hotels  fetch_pois → cluster   (按需触发，未命中则跳过)
        └───────────┴───────────────┴───────────┘
                    │
                    ▼
            plan_itinerary (partial)    (支持局部重排：只重排 dirty 的天)
                    │
                    ▼
           estimate_budget
                    │
                    ▼
            review_plan (lite)          (单轮，不再回环)
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

- 同一个 `conversation_name` 同时只能有一个 refine 在跑（Redis 分布式锁）
- 历史版本 PDF 保留最近 5 版（`trip_xxx_v1.pdf`, `_v2.pdf`, ...）
- Refine 失败不污染当前已发布版本（事务化：临时 state 提交成功后再切换 current 指针）
- LLM 解析 RefineIntent 失败时回退为 `freeform`，并把原始指令注入 plan prompt

### 4.5 Reducer / 合并策略

并行节点写入不同字段，互不冲突；以下字段使用 reducer：

```python
errors:        Annotated[list[ErrorRecord], operator.add]
history:       Annotated[list[VersionMeta], operator.add]
dirty_nodes:   Annotated[set[str], lambda a, b: a | b]
```

---

## 5. 工具 (Tools) 设计

### 5.1 通用 Tool 接口（含 Mock/Real 切换）

每个外部能力封装为 `BaseTravelTool`，**Provider Adapter 层**根据 `USE_MOCK_TOOLS` 选择 Mock 或 Real 实现，对图层完全透明。

```python
# app/tools/base.py
class BaseTravelTool(BaseTool):
    cache_ttl: int = 1800
    provider: BaseProvider           # MockProvider | RealProvider

    async def _arun(self, **kwargs) -> dict:
        cache_key = self._make_key(kwargs)
        if cached := await cache.get(cache_key):
            return cached
        try:
            result = await self.provider.fetch(**kwargs)   # ← 由 Adapter 决定
            await cache.set(cache_key, result, self.cache_ttl)
            return result
        except Exception as e:
            logger.warning(f"{self.name} provider={self.provider.name} failed: {e}")
            if self.provider.fallback:
                return await self.provider.fallback.fetch(**kwargs)
            raise

# app/tools/factory.py
def build_flight_tool() -> FlightTool:
    if settings.USE_MOCK_TOOLS:
        provider = MockFlightProvider()
    else:
        provider = AmadeusProvider(api_key=settings.AMADEUS_KEY, ...)
    return FlightTool(provider=provider)
```

### 5.2 工具清单

| 工具 | Mock 实现 | 真实 API（生产） | 输入 | 输出 |
|------|-----------|------------------|------|------|
| `WeatherTool` | 基于历史季节的伪随机生成 | 和风天气（国内） / OpenWeatherMap（海外） | city, date_range | `{date, temp_high, temp_low, condition, rain_prob}` |
| `FlightTool` | Faker 生成 3~5 个候选 | **Amadeus Flight Offers**（海外） / **携程开放平台 / 去哪儿** （国内）/ **Skyscanner RapidAPI** | from, to, date, pax | top-K `{airline, flight_no, depart_time, arrive_time, duration, price, stops}` |
| `HotelTool` | Faker 生成 5~10 个候选 | **Booking.com Affiliate / RapidAPI** / **Agoda Affiliate API** / **携程酒店 API** | city, checkin, checkout, pax, theme | top-K `{name, area, price, rating, kid_friendly, lng, lat, image_url}` |
| `POITool` | 离线 JSON 知识库（80 个热门城市） | **高德地图 Place Search**（国内） / **TripAdvisor Content API**（海外） / **Google Places API** | city, theme, kid? | `{name, type, lng, lat, rating, duration_minutes, ticket_price, opening_hours}` |
| `RouteTool` | 基于 lng/lat 估算直线距离 + 倍率 | **高德路径规划**（国内） / **Google Directions API**（海外） | poi_a, poi_b, mode | `{distance_km, duration_minutes}` |
| `CurrencyTool` | 固定汇率表 | **exchangerate.host**（免费）/ **Open Exchange Rates** | base, target | rate |

### 5.3 真实 API 接入详细方案（生产切换时启用）

#### 5.3.1 机票 — Amadeus Flight Offers Search（海外首选）

- **文档**：https://developers.amadeus.com/self-service/category/flights
- **认证**：OAuth2 Client Credentials（`AMADEUS_API_KEY` + `AMADEUS_API_SECRET`）
- **关键端点**：`GET /v2/shopping/flight-offers`
- **配额**：免费 Test 环境 2000 次/月；生产付费按调用计费
- **字段映射**：
  | Amadeus 字段 | TripState 字段 |
  |--------------|----------------|
  | `itineraries[].segments[].carrierCode + number` | `flight_no` |
  | `itineraries[].segments[].departure.at` | `depart_time` |
  | `price.total` (EUR) | `price` (转换为 CNY) |
- **限流**：10 QPS（每个 app key），用 token bucket 限流

#### 5.3.2 机票 — 携程开放平台（国内首选）

- **文档**：https://open.ctrip.com/
- **认证**：商家入驻审核（约 5~15 工作日），获取 `appId` + `secretKey`，签名算法 HMAC-SHA256
- **关键端点**：`POST /flight/search`（机票查询）
- **配额**：根据合作等级，初期约 10 万次/天
- **风险**：审核周期长，建议先用 Amadeus 做主，国内航线再走携程

#### 5.3.3 酒店 — Booking.com Affiliate Partner（海外首选）

- **文档**：https://developers.booking.com/connectivity/docs/affiliate-api
- **认证**：注册 Affiliate 账号 + 申请 API 权限
- **关键端点**：`GET /hotels/search`
- **限制**：必须显示 Booking.com 来源；不能缓存价格超过 24h
- **字段映射**：`hotel.review_score → rating`、`composite_price → price`

#### 5.3.4 酒店 — 携程 / Agoda（备选）

- 携程：与机票同入驻流程，酒店 API 单独申请权限
- Agoda Affiliate：https://partners.agoda.com/，申请较快（1~3 天）

#### 5.3.5 POI — 高德地图 Web 服务 API（国内首选）

- **文档**：https://lbs.amap.com/api/webservice/summary
- **认证**：`AMAP_KEY`（个人开发者免费 30 万次/天）
- **关键端点**：
  - `GET /v3/place/text`（关键词搜索）
  - `GET /v3/place/around`（周边搜索）
  - `GET /v3/direction/walking`（步行路径，给 RouteTool 用）

#### 5.3.6 POI — TripAdvisor Content API（海外首选）

- **文档**：https://www.tripadvisor.com/developers
- **认证**：申请 Content API key（需审核，免费 5000 次/月起）
- **限制**：必须显示 TripAdvisor 评分和链接

#### 5.3.7 天气 — 和风天气（国内首选）

- **文档**：https://dev.qweather.com/
- **认证**：`QWEATHER_KEY`（开发者免费 1000 次/天）
- **关键端点**：
  - `GET /v7/weather/7d`（7 天预报）
  - `GET /v7/weather/15d`（15 天，付费）

#### 5.3.8 天气 — OpenWeatherMap（海外首选）

- **文档**：https://openweathermap.org/api
- **认证**：`OWM_KEY`（免费版 1000 次/天）
- **关键端点**：`GET /data/3.0/onecall`（含未来 8 天）

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

- [ ] 真实 API key 已配置到 Secret Manager
- [ ] 各 Provider 的字段映射单测通过（输入/输出 schema 与 Mock 等价）
- [ ] 限流配置（per-tool、per-provider）已设置
- [ ] 缓存 TTL 满足平台 ToS（Booking 价格 ≤ 24h 等）
- [ ] 错误率告警阈值：单 provider 5xx > 5% 时自动降级到 fallback provider
- [ ] 在 staging 环境跑过完整 e2e（5 天行程）

### 5.4 Mock 数据生成器

```
app/tools/mocks/
├── mock_weather.py         # 基于 destination + 月份的伪随机
├── mock_flight.py          # Faker 生成航班，价格基于 km 估算
├── mock_hotel.py           # Faker 生成酒店，价格按主题区分
├── mock_poi.py             # 维护离线 JSON：80 个城市 × 50 个 POI
└── fixtures/
    └── poi/
        ├── osaka.json
        ├── beijing.json
        ├── tokyo.json
        └── ...
```

Mock 数据原则：
- **结构与真实 API 完全一致**（Pydantic Model 共用），切换时图层零改动
- 数据**随机但稳定**：相同输入参数返回相同输出（基于 hash 种子），便于 e2e 测试
- 在 PDF 中带"演示数据"水印，避免误导

### 5.5 缓存策略

- Key: `tool_name + provider + sha1(canonical(kwargs))`
- TTL：天气 6h，机票/酒店 30min，POI 24h
- 存储：Redis Hash

---

## 6. Prompt 设计

### 6.1 `parse_intent`（结构化抽取）

```text
你是旅行偏好抽取器。从用户输入中抽取结构化字段，缺失字段输出 null。
输出 JSON：
{
  "budget_per_person": number | null,   // CNY
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

### 6.3 `parse_refine_intent`（多轮调整指令解析）

```text
你是旅行助手的指令解析器。用户已经有一份 {days_num} 天的行程，现在希望调整。

【当前行程摘要】{current_itinerary_summary}
【用户调整指令】{refine_request}

请输出 JSON：
{
  "type": "swap_poi" | "rework_day" | "change_hotel" | "change_flight"
        | "change_pace" | "change_theme" | "change_budget"
        | "extend_days" | "freeform",
  "targets": [string],     // 例如 ["day_3"] 或 ["环球影城"] 或 ["心斋桥酒店"]
  "payload": {             // 类型相关
    "new_pace": "relaxed",
    "new_budget": 8000,
    "new_theme": "美食",
    "extra_days": 2,
    "free_text": "..."
  }
}

判断规则：
- 用户提到具体某天 → rework_day
- 用户要求换酒店/换住宿 → change_hotel
- 用户提到航班/机票 → change_flight
- 用户提到节奏/紧/松/累 → change_pace
- 仅替换某景点 → swap_poi
- 改变主题 → change_theme
- 涉及预算 → change_budget
- 增加/减少天数 → extend_days
- 兜底 → freeform
```

### 6.4 `review_plan`（自反思）

```text
作为审稿编辑，检查以下行程是否存在问题：
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
2. 概览页：路线缩略图 + 关键数字（天数 / 预算 / 推荐酒店）
3. 行程页（每天一节）：天气 + 时段表 + POI 卡片 + 餐饮推荐 + 当日交通 tips
4. 机票页：去/回程候选
5. 酒店页：候选 + 推荐
6. 预算页：饼图 + 明细表
7. 实用信息页：注意事项、应急联系、签证/入境提示
8. 封底：生成时间 + **版本号**（多轮调整可追溯）+ 免责声明

### 7.2 实现

```python
html = jinja_env.get_template("trip_report.html.j2").render(plan=plan)
HTML(string=html, base_url=ASSETS_DIR).write_pdf(
    output_path,
    stylesheets=[CSS(filename=CSS_FILE)]
)
```

- 模板：`templates/trip_report.html.j2`
- 样式：`templates/trip_report.css`（A4 / 中文字体 Noto Sans CJK / 打印优化）
- 字体：Docker 中预装 `fonts-noto-cjk` 解决中文显示
- Mock 模式下渲染水印 "DEMO DATA — 演示数据，请勿用于真实出行"

---

## 8. 项目结构

```
TravelPlanningAgent/
├── DESIGN.md
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── Dockerfile
│
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── api/
│   │   ├── routes_trip.py       # 异步主流程 + refine + SSE
│   │   ├── routes_debug.py      # 同步 debug 端点
│   │   └── schemas.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── llm.py               # LLM Provider 抽象
│   │   └── locks.py             # 分布式锁（refine 互斥）
│   ├── agent/
│   │   ├── state.py
│   │   ├── plan_graph.py        # build_plan_graph()
│   │   ├── refine_graph.py      # build_refine_graph()
│   │   ├── nodes/
│   │   │   ├── validate.py
│   │   │   ├── parse_intent.py
│   │   │   ├── parse_refine_intent.py
│   │   │   ├── route_refine_dispatcher.py
│   │   │   ├── load_previous_state.py
│   │   │   ├── fetch_weather.py
│   │   │   ├── fetch_flights.py
│   │   │   ├── fetch_hotels.py
│   │   │   ├── fetch_pois.py
│   │   │   ├── cluster_pois.py
│   │   │   ├── plan_itinerary.py
│   │   │   ├── estimate_budget.py
│   │   │   ├── review_plan.py
│   │   │   ├── render_pdf.py
│   │   │   └── finalize.py
│   │   ├── prompts/
│   │   │   ├── parse_intent.j2
│   │   │   ├── parse_refine_intent.j2
│   │   │   ├── plan_itinerary.j2
│   │   │   └── review_plan.j2
│   │   └── checkpointer.py      # RedisSaver 工厂
│   ├── tools/
│   │   ├── base.py
│   │   ├── factory.py           # build_xxx_tool() + provider 路由
│   │   ├── cache.py
│   │   ├── weather.py
│   │   ├── flight.py
│   │   ├── hotel.py
│   │   ├── poi.py
│   │   ├── route.py
│   │   ├── currency.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── amadeus.py
│   │   │   ├── booking.py
│   │   │   ├── ctrip.py
│   │   │   ├── amap.py
│   │   │   ├── tripadvisor.py
│   │   │   ├── qweather.py
│   │   │   └── openweather.py
│   │   └── mocks/
│   │       ├── mock_weather.py
│   │       ├── mock_flight.py
│   │       ├── mock_hotel.py
│   │       ├── mock_poi.py
│   │       └── fixtures/
│   ├── workers/
│   │   ├── celery_app.py
│   │   ├── tasks_plan.py        # @celery.task plan_trip
│   │   └── tasks_refine.py      # @celery.task refine_trip
│   ├── services/
│   │   ├── pdf_renderer.py
│   │   ├── storage.py           # 本地 / OSS
│   │   ├── progress_publisher.py # SSE 通过 Redis Pub/Sub 推送
│   │   └── trip_repo.py         # SQLite 任务/版本元数据
│   └── models/
│       ├── trip.py
│       ├── poi.py
│       ├── flight.py
│       ├── hotel.py
│       ├── weather.py
│       └── refine.py            # RefineIntent
│
├── templates/
│   ├── trip_report.html.j2
│   ├── trip_report.css
│   └── assets/
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

## 9. 关键接口

### 9.1 异步主流程（推荐入口）

```http
# 1. 创建任务
POST /api/v1/trips
Content-Type: application/json

{
  "conversation_name": "trip_2026_summer",
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
  "conversation_name": "trip_2026_summer",
  "status": "pending",
  "version": 1
}
```

```http
# 2. 查询状态（轮询备用）
GET /api/v1/trips/{trip_id}
→ {
  "trip_id": "trp_abc123",
  "status": "running",            // pending | running | success | failed
  "version": 1,
  "progress": [
    { "node": "fetch_weather", "status": "done", "duration_ms": 820 },
    { "node": "fetch_flights",  "status": "running" }
  ]
}
```

```http
# 3. SSE 进度推送（推荐）
GET /api/v1/trips/{trip_id}/stream
→ event-stream

event: node_start
data: {"node":"fetch_weather","ts":1716...}

event: node_end
data: {"node":"fetch_weather","duration_ms":820,"summary":"5 天天气获取完成"}

event: complete
data: {"version":1,"pdf_url":"https://.../trp_abc123_v1.pdf"}
```

```http
# 4. 下载 PDF
GET /api/v1/trips/{trip_id}/pdf?version=1
→ application/pdf
```

### 9.2 多轮调整 Refine

```http
POST /api/v1/trips/{trip_id}/refine
Content-Type: application/json

{
  "instruction": "把第3天改成室内活动，酒店换成离心斋桥近的"
}

→ 202 Accepted
{
  "trip_id": "trp_abc123",
  "status": "pending",
  "version": 2,                   // 新版本号
  "based_on_version": 1,
  "stream_url": "/api/v1/trips/trp_abc123/stream?version=2"
}
```

- 同一 `trip_id` 同时只允许一个 refine 在跑（Redis 分布式锁，TTL 5min）
- 历史版本可通过 `?version=N` 拉取
- `GET /api/v1/trips/{trip_id}/versions` 列出所有版本

### 9.3 Debug / 同步端点（仅开发）

```http
POST /api/v1/debug/trips:plan-sync   # 同步执行整个 graph，便于本地调试
```

### 9.4 SSE 事件清单

| 事件 | payload |
|------|---------|
| `task_accepted` | `{trip_id, version}` |
| `node_start` | `{node, ts}` |
| `node_end` | `{node, duration_ms, summary}` |
| `node_error` | `{node, error, will_retry}` |
| `review_iteration` | `{iteration, passed, feedback}` |
| `complete` | `{version, pdf_url, plan}` |
| `failed` | `{error, partial_result?}` |

---

## 10. 错误与降级

| 场景 | 策略 |
|------|------|
| 必填字段缺失 | 返回 422，不进入图 |
| 单一 fetch 工具失败 | 节点内 try/except，state.errors 累加，使用降级值，PDF 中以"信息暂缺"提示 |
| LLM 限流 / 超时 | 指数退避重试 3 次；仍失败则触发 fallback Provider；review_plan 失败时直接通过原计划 |
| review_plan 不通过 | 最多回环 2 次，超出后保留最后一版并附"待优化建议" |
| Refine 解析失败 | 回退为 `freeform`，原始指令注入 plan prompt |
| Refine 中途失败 | 不污染当前版本；返回 failed 并保留 v_n 不变 |
| PDF 渲染失败 | 回退为 Markdown，HTTP 返回降级响应 |
| Worker 进程崩溃 | Celery 自动重试（最多 2 次）；任务级幂等通过 `trip_id + version` 保证 |

---

## 11. 可观测

- **Trace**：LangSmith（每次 graph run = 1 trace；每个 node = 1 span；refine 与 plan 区分 metadata）
- **Metrics**（Prometheus）：
  - `trip_plan_total{status,mode=plan|refine}`、`trip_plan_duration_seconds`
  - `tool_call_total{tool,provider,status}`、`tool_call_duration_seconds`
  - `llm_tokens_total{model,kind=prompt|completion}`、`llm_fallback_total{from,to,reason}`
  - `refine_intent_total{type}`
- **Log**：Loguru，结构化 JSON，`trip_id + version` 作为 trace key

---

## 12. 安全与合规

- API Key 仅放 `.env` / Secret Manager，禁止入库
- 用户输入做长度限制 + Prompt Injection 防护（在 LLM 调用前对 user 段做 XML 包裹）
- 输出 PDF 含免责声明：行程仅供参考、价格非实时、自行核实签证/政策
- Mock 模式下 PDF 显著水印
- 第三方数据使用遵守对应平台 ToS（特别是 Booking 价格缓存 ≤ 24h）

---

## 13. 里程碑

| 阶段 | 交付物 | 估时 |
|------|--------|------|
| M1 — 骨架 | FastAPI + LangGraph plan 图 + State + Mock Tool 跑通 + 异步任务框架 | 1d |
| M2 — Mock 工具 | 4 个 Mock Provider + 字段 schema 与真实 API 对齐 | 1.5d |
| M3 — 编排 | parse_intent / cluster_pois / plan_itinerary / review_plan | 2d |
| M4 — PDF | Jinja 模板 + WeasyPrint + 中文字体 + 水印 | 1d |
| M5 — Refine | refine 子图 + RefineIntent 解析 + dispatcher + API | 2d |
| M6 — 异步 / SSE | Celery + Redis broker + 进度发布 + SSE 端点 | 1d |
| M7 — 观测 | LangSmith + 日志 + 指标 + 告警 | 0.5d |
| M8 — 加固 | 错误降级、Prompt 注入防护、压测、Redis 锁验证 | 1d |
| M9 — 真实 API（按需） | 接入 Amadeus / 高德 / 和风 / Booking | 3~5d（含审核等待） |

合计骨架 + 多轮 + Mock 验收 ≈ **10 人日**；真实 API 接入按平台审核进度另算。

---

## 14. 已决策事项与剩余风险

### 14.1 已决策（见决策日志 §0）

1. ✅ **LLM 默认 GPT-4o**
2. ✅ **机票 / 酒店初期 Mock，真实 API 方案见 §5.3**
3. ✅ **支持多轮调整**（refine 子图）
4. ✅ **主架构异步**（Celery + SSE）

### 14.2 剩余风险与待跟踪

- **真实 API 审核周期**：携程 / Booking / TripAdvisor 审核 1~3 周，需要提前并行启动
- **国际化目的地**：货币、时区、签证信息需要单独的知识库或 Tool（M9 之后再做）
- **PDF 国际化字体**：日韩 / 阿拉伯等目标地名需要对应字体集
- **多轮调整的边界**：当 refine 跨度过大（如 5→10 天），可能比直接重做更慢；阈值化处理：超过一定 dirty 比例直接走 plan_graph
- **成本监控**：GPT-4o 单次完整规划 ≈ 30K~50K tokens，需要预算告警

---

## 15. 附：最小可运行示例（伪代码）

```python
# app/agent/plan_graph.py
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.redis import RedisSaver
from app.agent.state import TripState
from app.agent.nodes import (
    validate_input, parse_intent,
    fetch_weather, fetch_flights, fetch_hotels, fetch_pois,
    cluster_pois, plan_itinerary, estimate_budget,
    review_plan, render_pdf, finalize,
)

def build_plan_graph(checkpointer: RedisSaver):
    g = StateGraph(TripState)
    for n in [validate_input, parse_intent, fetch_weather, fetch_flights,
              fetch_hotels, fetch_pois, cluster_pois, plan_itinerary,
              estimate_budget, review_plan, render_pdf, finalize]:
        g.add_node(n.__name__, n)

    g.add_edge(START, "validate_input")
    g.add_edge("validate_input", "parse_intent")

    # fan-out
    for n in ["fetch_weather", "fetch_flights", "fetch_hotels", "fetch_pois"]:
        g.add_edge("parse_intent", n)
        g.add_edge(n, "cluster_pois")           # join

    g.add_edge("cluster_pois", "plan_itinerary")
    g.add_edge("plan_itinerary", "estimate_budget")
    g.add_edge("estimate_budget", "review_plan")

    g.add_conditional_edges(
        "review_plan",
        lambda s: "plan_itinerary" if (not s["review_passed"] and s["retry_count"] < 2) else "render_pdf",
    )
    g.add_edge("render_pdf", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)


# app/agent/refine_graph.py
def build_refine_graph(checkpointer: RedisSaver):
    g = StateGraph(TripState)
    g.add_node("load_previous_state", load_previous_state)
    g.add_node("parse_refine_intent", parse_refine_intent)
    g.add_node("route_refine_dispatcher", route_refine_dispatcher)
    g.add_node("fetch_flights", fetch_flights)
    g.add_node("fetch_hotels",  fetch_hotels)
    g.add_node("fetch_pois",    fetch_pois)
    g.add_node("cluster_pois",  cluster_pois)
    g.add_node("plan_itinerary",   plan_itinerary)
    g.add_node("estimate_budget",  estimate_budget)
    g.add_node("review_plan_lite", review_plan_lite)
    g.add_node("render_pdf",   render_pdf)
    g.add_node("finalize",     finalize)

    g.add_edge(START, "load_previous_state")
    g.add_edge("load_previous_state", "parse_refine_intent")
    g.add_edge("parse_refine_intent", "route_refine_dispatcher")

    # 条件分发：基于 dirty_nodes 决定走哪条路径
    g.add_conditional_edges(
        "route_refine_dispatcher",
        dispatch_by_dirty_nodes,
        {
            "flights":  "fetch_flights",
            "hotels":   "fetch_hotels",
            "pois":     "fetch_pois",
            "plan":     "plan_itinerary",
            "skip":     "estimate_budget",
        },
    )

    g.add_edge("fetch_flights", "plan_itinerary")
    g.add_edge("fetch_hotels",  "plan_itinerary")
    g.add_edge("fetch_pois",    "cluster_pois")
    g.add_edge("cluster_pois",  "plan_itinerary")
    g.add_edge("plan_itinerary","estimate_budget")
    g.add_edge("estimate_budget","review_plan_lite")
    g.add_edge("review_plan_lite","render_pdf")
    g.add_edge("render_pdf","finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)
```

```python
# 调用方式（异步任务里）
config = {"configurable": {"thread_id": conversation_name}}
result = await plan_graph.ainvoke(initial_state, config=config)

# 多轮调整时，同一个 thread_id 即可加载历史 state
result_v2 = await refine_graph.ainvoke(
    {"refine_request": "把第3天改成室内活动"},
    config=config,
)
```

---

> 本方案 v0.2 已确认 4 项关键决策（见 §0 决策日志）。
> 评审通过后，按里程碑 M1 → M9 推进。M1~M8 ≈ 10 人日，可基于 Mock 完整跑通；真实 API 接入按平台审核进度独立排期。
