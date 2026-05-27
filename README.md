<div align="center">

# ✈️ TravelPlanningAgent

### 基于 LangGraph 多智能体协作的智能旅行规划助手

一句话或一张表单提交诉求，自动完成 **多源数据聚合 + 行程编排 + 自反思 + Markdown / PDF 报告生成**，<br/>
全程 WebSocket 实时推送 **节点 / 工具调用 / 思维链**，支持 **多轮调整** 与 **MOCK 零密钥运行**。

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0+-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Vue](https://img.shields.io/badge/Vue-3.5+-4FC08D?logo=vue.js&logoColor=white)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](./LICENSE)

[English](./README.en.md) · **简体中文**

</div>

<p align="center">
  <img width="80%" alt="welcome screen" src="https://github.com/user-attachments/assets/54f1f38e-d5a9-4abb-8f01-be1c8085ff07" />
  <img width="80%" alt="chat stream with thought process" src="https://github.com/user-attachments/assets/7f6b3418-4a21-4ae4-8001-67f7d28c6ff5" />
</p>

---

## 目录

- [核心特性](#核心特性)
- [整体架构](#整体架构)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [后端架构详解](#后端架构详解)
  - [LangGraph 工作流](#langgraph-工作流)
  - [TripState 状态设计](#tripstate-状态设计)
  - [跨协程实时推送 (ContextVar + Monitor)](#跨协程实时推送-contextvar--monitor)
  - [Checkpointer 与多轮调整](#checkpointer-与多轮调整)
  - [LLM 抽象层](#llm-抽象层)
  - [工具层 (Mock/Real 切换)](#工具层-mockreal-切换)
  - [PDF 渲染 (多引擎)](#pdf-渲染-多引擎)
- [前端架构详解](#前端架构详解)
  - [组件树](#组件树)
  - [Pinia 状态管理](#pinia-状态管理)
  - [WebSocket 客户端](#websocket-客户端)
  - [会话持久化与恢复](#会话持久化与恢复)
- [端到端数据流](#端到端数据流)
- [快速开始](#快速开始)
- [配置项](#配置项)
- [API 参考](#api-参考)
- [WebSocket 事件协议](#websocket-事件协议)
- [冒烟测试](#冒烟测试)
- [演示行为说明](#演示行为说明)
- [License](#license)

---

## 核心特性

| # | 特性 | 说明 |
|---|------|------|
| F-01 | 多源信息聚合 | 并行调用天气 / 机票 / 酒店 / POI 工具 |
| F-02 | 智能行程编排 | 按片区聚类 + 节奏映射；每日含 meals / transport / 单日预估开销 / 预订提醒 |
| F-03 | 主题适配 | 亲子 / 蜜月 / 美食 / 户外 / 文化等主题影响 POI 选择、节奏、餐厅密度、打包项 |
| F-04 | 报告 6 大模块 | Markdown 始终生成（PDF 自动选择 Word COM / pandoc+xelatex / WeasyPrint）；包含每日行程 / 推荐机票酒店 / 预算（按 budget/mid-range/luxury 分档） / **打包清单** / **当地文化与安全** / **出行前准备 Timeline** |
| F-05 | 自反思循环 | `review_plan` 不通过会回到 `plan_itinerary`，最多 2 次 |
| F-06 | 失败降级 | 单个工具失败仅写入 `errors`，不阻塞主流程 |
| F-07 | 多轮调整 | `refine_graph` 按 `dirty_nodes` 最小化重算，`version+1` |
| F-08 | 异步执行 | `asyncio.create_task` 调度，HTTP 立即返回 |
| F-09 | Web 前端 | Vue 3 Kiro 风格：欢迎页 → 聊天流 + 思维链 + 文件抽屉 |
| F-10 | 实时推送 | 节点 / 工具 / 审稿迭代 / 任务结果通过 WebSocket 推送 |
| F-11 | 多用户隔离 | `ContextVar` 在协程级隔离 `session_dir` / `thread_id` |
| F-12 | Mock-to-Real | `MOCK_LLM=false` 切 GPT-4o；`USE_MOCK_TOOLS=false` 走 QWeather / OpenWeatherMap / Amadeus / Amap 真实 Provider，**缺哪个 Key 就该工具单独降级 Mock**，不阻塞其余工具 |

---

## 整体架构

```mermaid
flowchart TB
    subgraph FE["🖥️ Web Frontend · Vue 3 + TS + Vite + Pinia"]
        FUI["WelcomeScreen / ChatStream / ThoughtProcess / FilesSidebar"]
        FStore["stores/chat.ts (Pinia)"]
        FUI --- FStore
    end

    subgraph API["⚡ FastAPI 服务层 · api/server.py"]
        REST["REST · /api/trip · /refine · /files"]
        WSE["WS · /ws/{thread_id} → ConnectionManager"]
        Task["asyncio.create_task"]
        REST --> Task
    end

    subgraph AG["🧠 LangGraph 编排层 · agent/"]
        PG["plan_graph (15 节点)"]
        RG["refine_graph"]
        Saver[("InMemorySaver · 共享")]
        Subs["LLM 子 agent · parse_intent / plan_itinerary / review_plan / parse_refine"]
        PG -.- Saver
        RG -.- Saver
        PG --- Subs
        RG --- Subs
    end

    subgraph TL["🔧 工具层 · TravelTool 包装器 (统一上报 Monitor)"]
        TW[Weather]
        TF[Flight]
        TH[Hotel]
        TP[POI]
    end

    subgraph PV["🔌 Provider 适配器"]
        Mock["Mock"]
        Real["Real"]
    end

    FE <-->|"HTTP (axios) + WebSocket"| API
    Task --> AG
    AG --> TL
    TL --> PV
```

> **横切关注点 (Cross-cutting)**
> - `ContextVar(session_dir, thread_id)` —— 协程级会话隔离
> - `Monitor` 单例 + `run_coroutine_threadsafe` —— 任意深度反向推送 WS
> - `TTLCache (cachetools)` —— 工具结果缓存
> - `Jinja2` + `Word` / `Pandoc` / `WeasyPrint` —— 多引擎 PDF
> - 文件落盘：`output/session_{thread_id}/trip_v{N}.{md,pdf}`

---

## 技术栈

### 后端

| 类别 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | |
| Agent 框架 | **LangGraph 1.0** + LangChain 1.0 | 状态机式工作流；`init_chat_model` 统一入口 |
| Web 框架 | FastAPI 0.115 + Uvicorn | 原生异步 / WebSocket / OpenAPI |
| Checkpointer | **InMemorySaver** | 进程内按 `thread_id` 隔离；可平滑切换到 Sqlite/Postgres |
| 异步调度 | `asyncio.create_task` | 不引入 Celery |
| 数据校验 | Pydantic v2 | 与 TripState 集成 |
| 实时通信 | 原生 WebSocket | 与前端 WebSocket API 直接对接 |
| 会话隔离 | `contextvars.ContextVar` | 协程级 |
| 缓存 | `cachetools.TTLCache` | 进程内，无 Redis 依赖 |
| 模板/PDF | Jinja2 + 多引擎(Word COM/pandoc/WeasyPrint) | 跨平台 Markdown→PDF |
| 日志 | Loguru | 彩色结构化输出 |

### 前端

| 类别 | 选型 | 说明 |
|------|------|------|
| 框架 | Vue 3.5 (Composition API + `<script setup>`) | |
| 语言 | TypeScript 5+ | 严格模式 |
| 构建 | Vite 5 | 代理 `/api` `/ws` → `127.0.0.1:8000` |
| 状态管理 | **Pinia** | `chat` / `history` 两个 store |
| HTTP | axios | REST 调用 |
| WebSocket | 原生 `WebSocket` + 自动重连 + 心跳 | 25s `ping` |
| Markdown | marked + DOMPurify | 渲染 AI 回复（XSS 防护） |
| 样式 | CSS Variables + Scoped CSS | Kiro 深色主题 |

---

## 项目结构

> **分层原则**：依赖方向严格自上而下 —— `core/` 是叶子包（仅依赖 stdlib + 三方），其它包都可以放心引用 `core/*`，
> 反过来 `core/` 永远不引入 `agent/` `api/` `tools/` `services/` `domain/`，从架构层面杜绝循环依赖。

```
TravelPlanningAgent/
├── core/                        🧰 横切运行时基础设施（叶子包）
│   ├── logger.py                  Loguru 配置（singleton ``logger``）
│   ├── context.py                 ContextVar(session_dir, thread_id) —— 协程级会话隔离
│   ├── monitor.py                 ToolMonitor 单例，跨协程定向推送 WS
│   ├── llm.py                     MockLLM / RealLLM (init_chat_model) + build_llm()
│   ├── checkpointer.py            InMemorySaver 单例工厂（plan + refine 共享）
│   └── prompts.py                 YAML 提示词加载 + 安全 {var} 替换
│
├── api/                         🌐 FastAPI HTTP 边界层（极简）
│   ├── server.py                  REST + WS 入口；asyncio.create_task 调度 agent
│   ├── connection_manager.py      WebSocket 连接管理（按 thread_id 路由 · 与 fastapi.WebSocket 强耦合）
│   └── schemas.py                 HTTP 请求/响应 Pydantic 模型
│
├── agent/                       🧠 LangGraph 编排层（纯领域）
│   ├── plan_agent.py              首次规划入口（设置 ContextVar、调度图）
│   ├── refine_agent.py            多轮调整入口
│   ├── plan_graph.py              build_plan_graph() — 15 节点状态机
│   ├── refine_graph.py            build_refine_graph() — 复用 plan 节点 + 派发器
│   ├── nodes.py                   plan-graph 节点（fetch / plan / 3 个 generator / review / render）
│   ├── refine_nodes.py            load_previous_state / parse_refine_intent / dispatcher_router
│   ├── _timed.py                  共享 @timed 装饰器（plan + refine 节点共用）
│   ├── agents.py                  7 个 LLM 子 agent（共用 build_llm() 单例 + 各自 prompt）
│   ├── state.py                   TripState (TypedDict + Annotated reducer)
│   └── prompts/
│       └── prompts.yaml           7 个集中式提示词模板（plan 4 个 + skill 风格 3 个：pack_list / cultural_tips / pre_trip_checklist）
│
├── domain/                      📦 纯领域数据模型 / 路由常量
│   └── refine.py                  RefineIntent + DIRTY_MAP（refine 类型 → 脏节点集合）
│
├── tools/                       🔧 工具层
│   ├── base.py                    TravelTool 包装器（缓存 + monitor + 降级）
│   ├── factory.py                 provider 工厂（按 USE_MOCK_TOOLS 路由）
│   ├── cache.py                   TTLCache（key = tool+provider+sha1(kwargs)）
│   └── providers/                 数据源适配器（Mock + Real 同级共存）
│       ├── base.py                  BaseProvider 抽象
│       ├── real/                    QWeather / OpenWeatherMap / Amadeus(机票+酒店) / Amap
│       └── mocks/                   mock_weather / mock_flight / mock_hotel / mock_poi
│           └── fixtures/poi/        东京 / 北京 / 大阪 离线 POI 数据
│
├── services/                    🛠️ 领域服务
│   ├── pdf_renderer.py            Markdown 渲染 + 多引擎 PDF 转换
│   └── templates/
│       └── trip_report.md         Jinja2 报告模板（与 pdf_renderer 就近放置）
│
├── ui/                          🖥️ Vue 3 前端
│   ├── src/
│   │   ├── App.vue                三栏布局：HistorySidebar / Main / FilesSidebar
│   │   ├── api/{http,trip,ws}.ts  axios + REST + WebSocket 客户端
│   │   ├── stores/chat.ts         Pinia 主 store（messages/threadId/status/files）
│   │   ├── stores/history.ts      历史会话（localStorage 持久化）
│   │   ├── components/            WelcomeScreen / ChatStream / MessageAi /
│   │   │                          ThoughtProcess / ToolCallCard / InputBox /
│   │   │                          TripFormInline / FileCard / 两个侧栏
│   │   └── types/{chat,ws,trip}.ts
│   └── vite.config.ts             /api /ws 代理到后端
│
├── scripts/                     🚀 运维脚本
│   ├── run_backend.sh             启动后端（uvicorn api.server:app）
│   └── run_frontend.sh            启动前端（npm run dev）
│
├── tests/                       ✅ 测试套件（与 pyproject.toml::testpaths 对齐）
│   └── smoke/
│       ├── smoke_test.py          直跑 plan + refine 图（无 HTTP）
│       └── smoke_http.py          ASGI 端到端 + WS 管道测试
│
├── output/session_{thread_id}/  会话产物（trip_v{N}.md / .pdf）
├── DESIGN.md                    完整设计文档（权威参考）
├── requirements.txt
├── pyproject.toml
└── README.md / README.en.md
```

### 依赖方向（一图）

```
            ┌─────────────────────────────────────────────┐
            │  api  (HTTP 边界)                           │
            │   server.py · schemas.py · connection_mgr   │
            └─────────────┬───────────────────────────────┘
                          │ 仅向下依赖
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   ┌─────────┐      ┌──────────┐       ┌──────────┐
   │  agent  │      │ services │       │  tools   │
   │ (graphs │      │ (pdf,    │       │ (Travel  │
   │  +nodes)│      │  jinja)  │       │  Tool +  │
   │         │      │          │       │ provider)│
   └────┬────┘      └────┬─────┘       └────┬─────┘
        │                │                  │
        └────────────────┼──────────────────┘
                         ▼
                ┌────────────────┐
                │  core  (叶子)  │  ← logger / context / monitor /
                │                │     llm / checkpointer / prompts
                └────────────────┘
                         ▲
                ┌────────┴───────┐
                │     domain     │  ← refine.py（纯数据 + 路由表）
                └────────────────┘
```

| 包 | 角色 | 依赖谁 |
|----|------|--------|
| `core/` | 横切基础设施（leaf） | 仅 stdlib + 三方 |
| `domain/` | 领域数据模型（leaf） | 仅 stdlib + Pydantic |
| `tools/` | 数据源工具 + Provider 适配 | `core` |
| `services/` | 领域服务（PDF/模板） | `core` |
| `agent/` | LangGraph 编排 | `core` · `domain` · `tools` · `services` |
| `api/` | FastAPI HTTP 边界 | `core` · `agent` |

---

## 后端架构详解

### LangGraph 工作流

#### Plan 图（`agent/plan_graph.py`）— 首次规划

```mermaid
flowchart TD
    Start([START]) --> VI["validate_input · 校验/补默认/算 date_range"]
    VI --> PI["parse_intent · LLM 抽取约束"]
    PI --> FW[fetch_weather]
    PI --> FF[fetch_flights]
    PI --> FH[fetch_hotels]
    PI --> FP[fetch_pois]
    FW --> CP["cluster_pois · 按 area 聚类 → N 个 day bucket"]
    FF --> CP
    FH --> CP
    FP --> CP
    CP --> PL[plan_itinerary]
    CP --> GPL[generate_packing_list]
    CP --> GCT[generate_cultural_tips]
    CP --> GPT[generate_pre_trip_checklist]
    PL --> EB[estimate_budget]
    GPL --> EB
    GCT --> EB
    GPT --> EB
    EB --> RP{"review_plan · LLM 自反思"}
    RP -->|"不通过 & retry &lt; 2"| PL
    RP -->|"passed"| RD["render_pdf · MD（必有）+ PDF（可选）"]
    RD --> FN["finalize · 推送 task_result"]
    FN --> End([END])

    classDef parallel fill:#e3f2fd,stroke:#1976d2,color:#0d47a1
    classDef llm fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    class FW,FF,FH,FP parallel
    class PI,PL,RP,GPL,GCT,GPT llm
```

**关键实现点**

- `@_timed(node_name)` 装饰器自动发 `node_start` / `node_end` 事件
- 节点返回 `{"_summary": "..."}` 字段会作为 `node_end` 的 `summary` 推到前端
- 4 个 fetcher 都是 `parse_intent` 的下游，LangGraph 自动并行
- `review_router` 条件边实现 review→retry 循环（最多 2 次）
- 异常仅 `monitor.report_error` + 记录到 `errors`，不中断主图

#### Refine 图（`agent/refine_graph.py`）— 多轮调整

```mermaid
flowchart TD
    Start([START]) --> LP["load_previous_state · 从 saver 读 v_n"]
    LP --> PRI["parse_refine_intent · LLM → RefineIntent + dirty_nodes"]
    PRI --> DR{"dispatcher_router · 按 dirty_nodes 路由"}
    DR -.->|"fetch_weather ∈ dirty"| FW[fetch_weather]
    DR -.->|"fetch_flights ∈ dirty"| FF[fetch_flights]
    DR -.->|"fetch_hotels ∈ dirty"| FH[fetch_hotels]
    DR -.->|"fetch_pois ∈ dirty"| FP[fetch_pois]
    DR -.->|"否则跳过 fetch"| PL[plan_itinerary]
    FP --> CP[cluster_pois]
    FW --> PL
    FF --> PL
    FH --> PL
    CP --> PL

    PL --> EB[estimate_budget]
    EB --> RPL[review_plan_lite]
    RPL --> RD["render_pdf · trip_v(n+1)"]
    RD --> FN["finalize · version+1"]
    FN --> End([END])

    classDef parallel fill:#e3f2fd,stroke:#1976d2,color:#0d47a1
    classDef llm fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    class FW,FF,FH,FP,CP parallel
    class PRI,PL,RPL llm
```

`refine_intent.type` → `dirty_nodes` 映射在 `domain/refine.py::DIRTY_MAP`：

| RefineType | dirty_nodes |
|------------|-------------|
| `swap_poi` / `rework_day` / `change_pace` / `freeform` | `{plan_itinerary}` |
| `change_hotel` | `{fetch_hotels, plan_itinerary}` |
| `change_flight` | `{fetch_flights}` |
| `change_theme` | `{fetch_pois, cluster_pois, plan_itinerary, generate_packing_list, generate_cultural_tips}` |
| `change_budget` | `{fetch_hotels, plan_itinerary}` |
| `extend_days` | 全部 fetch + cluster + plan + `generate_packing_list` + `generate_pre_trip_checklist` |

> 所有 refine 类型都强制重算 `estimate_budget` → `review_plan_lite` → `render_pdf` → `finalize`，确保最终产物自洽。

### TripState 状态设计

`TripState` 是一个 `TypedDict`，用 `Annotated[..., reducer]` 声明 LangGraph 合并策略：

```python
class TripState(TypedDict, total=False):
    # 输入：destination / days_num / people_num / travel_theme / ...
    # 解析：parsed_intent / date_range / constraints（含 budget_level / interests）
    # 聚合：weather / flights / hotels / pois / pois_clustered
    # 规划：itinerary（含 meals/transport/daily_cost_cny/booking_notes）
    # 内容：packing_list / cultural_tips / pre_trip_checklist
    # 预算：budget（按 tier 分档）/ daily_costs[] / tips / summary
    # 反思：review_passed / review_feedback / retry_count
    # 多轮：version / refine_request / refine_intent
    history:     Annotated[List[Dict], operator.add]   # 追加
    dirty_nodes: Annotated[set, _set_union]            # 集合合并
    files:       Annotated[List[Dict], operator.add]
    errors:      Annotated[List[Dict], operator.add]
```

并行节点同时写同一个键时通过 reducer 合并，无需手动同步。

### 跨协程实时推送 (ContextVar + Monitor)

后端的"任意深度都能把事件推到正确的前端连接"靠三件事，三个模块都位于 `core/`（横切基础设施）：

1. **`core/context.py`** — `session_dir` / `thread_id` 用 `ContextVar` 存储；
   `run_plan_agent` 入口用 `set_session_context` / `set_thread_context` 写入，
   asyncio 任务及其衍生协程自然继承。
2. **`core/monitor.py::ToolMonitor`** — 进程级单例，
   工具/节点直接 `from core.monitor import monitor` 调用 `report_*`，
   它从 ContextVar 读 `thread_id`，再用
   `asyncio.run_coroutine_threadsafe(manager.send_to_thread(...), manager.loop)`
   把事件投递到 FastAPI 主事件循环。
3. **`api/connection_manager.py::ConnectionManager`** — 维护
   `Dict[thread_id → WebSocket]`，`send_to_thread` 选中目标连接发送。
   它依赖 `fastapi.WebSocket` 类型，因此留在 HTTP 边界包 `api/` 中（不下沉到 `core/`）。

```mermaid
sequenceDiagram
    autonumber
    participant T as Tool / Node
    participant M as Monitor (singleton)
    participant CV as ContextVar
    participant L as FastAPI loop
    participant CM as ConnectionManager
    participant W as WebSocket
    participant FS as Frontend chat store

    T->>M: report_tool("WeatherTool", {...})
    M->>CV: get_thread_id()
    CV-->>M: thread_id
    M->>L: run_coroutine_threadsafe(send_to_thread)
    L->>CM: send_to_thread(payload, thread_id)
    CM->>W: ws.send_json(payload)
    W->>FS: onmessage
    FS->>FS: handleEvent → 修改 messages[].logs
```

**收益**：节点/工具是普通 `async def`，不需要持有 websocket 引用或参数透传，多用户并发安全。

### Checkpointer 与多轮调整

- `core/checkpointer.py` 提供 `get_checkpointer() → InMemorySaver` 单例
- `plan_graph` 与 `refine_graph` **共用同一个 saver**
- 调用时 `config = {"configurable": {"thread_id": thread_id}}`，LangGraph 自动按 thread_id 加载/合并 checkpoint
- `refine_agent.run_refine_agent` 仅传 `{"refine_request": instruction}`，其余字段由 saver 合并恢复
- `load_previous_state` 通过 `saver.aget_tuple(config)` 读取 `version`，新版本号 `+1`

> ⚠️ **限制**：进程重启后 InMemorySaver 状态全部丢失。
> 此时 `output/session_{tid}/` 还在，但 `state` 已没了 —— 用户若直接对老会话发起 refine，
> `load_previous_state` 会立刻抛 `RefineStateMissingError` 并通过 WebSocket 推一条
> `error` 事件（"会话状态已丢失，请重新发起一次完整规划"），不会跑到下游再 KeyError。
> 升级路径：把 `core/checkpointer.py::get_checkpointer()` 切到 `SqliteSaver` / 自定义 PostgresSaver，
> 接口完全兼容，无需改业务代码。

### LLM 抽象层

`core/llm.py` 提供两套实现 + 一个工厂：

| 类 | 触发条件 | 行为 |
|-----|----------|------|
| `MockLLM` | `MOCK_LLM=true`（默认）或缺 `OPENAI_API_KEY` | 按 prompt 关键词返回**结构化合规**的桩 JSON（7 种 prompt 各一种） |
| `RealLLM` | `MOCK_LLM=false` 且有 key | LangChain 1.0 `init_chat_model("gpt-4o", model_provider="openai", ...)` |

`agent/agents.py` 中 7 个子 agent **共用 `build_llm()` 返回的进程级单例**，差异化只在各自的 prompt 模板上 —— 早期版本曾把 `_llm_xxx` 拆成 7 个变量，但 `build_llm()` 内部会 cache 同一个实例，拆变量只会让代码看起来"每个 agent 有自己的模型"，运行时其实仍是同一个对象，反而误导 reader。要切不同模型时，改 `build_llm()` 让它按 agent 名分发即可：

| 子 agent | 调用节点 | 输入 → 输出 |
|---------|---------|------------|
| `parse_intent` | `parse_intent` | `bot_user_input` → `{parsed_intent, constraints}` |
| `plan_itinerary` | `plan_itinerary` | weather/pois_clustered/constraints → `{itinerary, tips}` |
| `generate_packing_list` | `generate_packing_list` | weather/days/theme → 7 类 checklist |
| `generate_cultural_tips` | `generate_cultural_tips` | destination/theme → dos/donts/dining/safety/phrases |
| `generate_pre_trip_checklist` | `generate_pre_trip_checklist` | destination/start_date/days → 5 段反推 timeline |
| `review_plan` | `review_plan` | itinerary/weather/budget → `{passed, issues, suggestions}` |
| `parse_refine_intent` | `parse_refine_intent` | refine_request + 摘要 → `RefineIntent + dirty_nodes` |

`core/prompts.py` 用**手动 `{var}` 替换**而非 `str.format`，避免提示词中 JSON 大括号被误识别。提示词模板放在 `agent/prompts/prompts.yaml`，与消费方就近放置。

### 工具层 (Mock/Real 切换)

```mermaid
flowchart LR
    A["TravelTool.fetch(**kwargs)"] --> B["monitor.report_tool_start(name, kwargs)"]
    B --> C{"cache.get · key=tool+provider+sha1(kwargs)"}
    C -->|"hit"| F["monitor.report_tool_end(name, summary)"]
    C -->|"miss"| D["provider.fetch · Mock | Real"]
    D -->|"ok"| E["cache.set(key, result)"]
    D -->|"fail & has fallback"| D2["provider.fallback.fetch"]
    D2 --> E
    E --> F
    F --> G([result])
```

- `tools/factory.py` 按 `USE_MOCK_TOOLS` + 目的地中/海外 + 各 Key 是否齐全做路由：
  - 国内天气 → QWeather；海外 → OpenWeatherMap
  - 机票 / 酒店 → Amadeus（test env 免费 2000/月）
  - 国内 POI → Amap；海外暂走 Mock
- **单工具降级**：缺某个 Provider 的 Key 时，**只有该工具退回 Mock**（一行 warning），其他工具该走真实就走真实，主流程不受影响
- 真实 Provider 抛错也会走 `BaseProvider.fallback`，自动回退到对应 Mock
- Mock provider 用 `hashlib.sha1(seed).hexdigest()` 做随机种子，**相同输入永远输出相同结果**（截图/测试友好）
- POI fixtures 已内置 **东京 / 北京 / 大阪**，其他城市走 Faker 合成
- 申请各 Key 的入口、免费额度、注意事项详见 [`.env.example`](./.env.example)

### PDF 渲染 (多引擎)

`services/pdf_renderer.py` 实现自动选择最优 PDF 引擎，端口自 DeepSearchResearcher：

| 平台 | 优先级 |
|------|--------|
| Windows | Word COM → pandoc(+xelatex) → WeasyPrint |
| macOS / Linux | pandoc(+xelatex) → WeasyPrint |

特别地：

- macOS 上自动把 `/Library/TeX/texbin`、`/opt/homebrew/bin` 等加入子进程 `PATH`，
  解决 GUI 启动的 Python（uvicorn / IDE）找不到 mactex 的常见问题
- 支持 `PDF_ENGINE=word|pandoc|weasyprint` 强制指定
- **Markdown 始终生成**；所有 PDF 引擎都失败时只产 `.md`，主流程不受影响

---

## 前端架构详解

### 组件树

```mermaid
flowchart TB
    App["App.vue · 三栏布局"]
    App --> HS[HistorySidebar.vue]
    App --> Main["main 区"]
    App --> FS[FilesSidebar.vue]
    Main --> Top["topbar · status dot + thread_id"]
    Main --> WS["WelcomeScreen.vue (无会话)"]
    Main --> CS["ChatStream.vue + InputBox (有会话)"]
    WS --> Chips["4 个示例提示芯片"]
    WS --> Form["InputBox(showForm=true) → TripFormInline"]
    CS --> MU["MessageUser.vue · 用户气泡"]
    CS --> MA[MessageAi.vue]
    MA --> TP["ThoughtProcess.vue · 折叠面板"]
    MA --> MD["marked + DOMPurify · markdown 渲染"]
    MA --> FC["FileCard.vue × N · PDF/MD 下载"]
    TP --> TC["ToolCallCard.vue × N"]
    HS -.- HStore["history store · localStorage"]
    FS -.- ChatFiles["chat.files · 实时同步"]
```

### Pinia 状态管理

#### `stores/chat.ts` — 主 store

```typescript
state:
  messages : Message[]            // 用户/AI 消息（含 logs[] / files[]）
  threadId : string | null
  status   : 'idle'|'running'|'error'|'ok'
  files    : FileItem[]           // 右侧栏数据源

actions:
  startNewTrip(req, displayText)  // POST /api/trip + 建 WS + 推 history + persist()
  sendRefine(instruction)         // POST /api/trip/{tid}/refine + persist()
  selectThread(tid)               // ① 加载 localStorage 瘦身缓存秒显
                                  // ② 重连 WS / 刷新文件
                                  // ③ GET /api/trip/{tid}/messages 与缓存合并回写
  newSession()                    // 关 WS、清空、回欢迎页

私有:
  ensureWs(tid)                   // TripWS 单例（自动重连）
  handleEvent(msg)                // 路由所有 WS 事件 → 修改 messages
  patchLogTitle(kind, name, ...)  // 把同名 running 日志条目改为 done
  persist()                       // 把当前线程的"瘦身版" messages 写入 localStorage
```

事件 → 状态 映射规则（见 `handleEvent`）：

| WS 事件 | 行为 |
|---------|------|
| `session_created` | append 一条 info log "📁 会话目录已创建" |
| `tool_start` | append 一条 running 工具卡片 |
| `tool_end` | 把最近一条同名 running 卡片 patch 成 done + summary |
| `node_start` / `node_end` | 同上，但 kind=node |
| `review_iteration` | append review 卡片（passed → done，否则 error） |
| `partial_thought` | append 一条 info |
| `task_result` | 当前 AI 消息：`content = result; files = files; status = 'done'`；并刷新 `/api/files`、`persist()` |
| `error` | append error 卡片 + 标记当前 AI 消息为 error；`persist()` |

#### `stores/history.ts` — 历史会话

最多保留 50 条，按 `last_active` 倒序，持久化到 `localStorage` 的 `tpa.history.v1` 键。
`startNewTrip` 时 `upsert`，`refine` 不会改变历史顺序（thread_id 已存在）。
`remove(tid)` 同时清理对应的 `tpa.msgs.<tid>` 缓存。

### WebSocket 客户端

`ui/src/api/ws.ts` 中的 `TripWS` 类提供：

- 自动 URL 解析：优先 `VITE_WS_BASE`，否则按页面 host + 协议（dev 模式由 Vite 反代）
- **重连**：`onclose` 后 1.5 秒重连，直到 `close()` 显式关闭
- **心跳**：每 25 秒发送 `"ping"` 字符串（后端会回 `{event:'pong'}`）
- 事件分发：`on(event, fn)` 订阅；`'*'` 监听所有事件
- 单例：`chat store::ensureWs(tid)` 保证同一 thread_id 复用同一连接

### 会话持久化与恢复

> 切换或刷新会话时如何"不丢消息"——后端补一个权威接口，前端用瘦身 LRU 缓存秒显。

#### 设计动机

`InMemorySaver` 进程内保存 LangGraph state，进程重启即丢；
而前端早期只在 `localStorage` 里缓存了 `HistoryItem` 元数据，切换会话或刷新页面会清空 `messages`。
为同时满足"秒开 / 跨刷新 / 不爆配额"三个目标，引入两层互补：

```mermaid
flowchart LR
    subgraph Server["📦 服务端权威源"]
        SD["session_dir<br/>trip_v{N}.{md,pdf}"]
        CK["InMemorySaver<br/>(channel_values)"]
    end
    subgraph Client["🖥️ 前端 localStorage"]
        H["tpa.history.v1<br/>HistoryItem[] (≤50)"]
        M["tpa.msgs.&lt;tid&gt;<br/>SlimMessage[] (LRU≤20)"]
    end
    SD -->|"GET /messages"| Resp["MessagesResponse"]
    CK -->|"aget_tuple"| Resp
    Resp --> Client
    Client -.->|"selectThread 秒显"| UI["chat store"]
    Resp -.->|"merge 覆盖 AI 内容"| UI
```

#### 后端：`GET /api/trip/{tid}/messages`

按版本组装出一份"瘦身"消息流，给前端做切换/刷新时的权威源。

| 数据来源 | 提供什么 | 存活性 |
|---------|---------|--------|
| `output/session_{tid}/trip_v{N}.{md,pdf}` | 各版本 AI 产出文件 | ✅ 跨重启保留 |
| `InMemorySaver.channel_values` | `bot_user_input` (v1 用户输入)、`history[].summary` | ❌ 进程内 |

返回结构：

```jsonc
{
  "thread_id": "trip-xxx",
  "expired": false,                     // true 表示 session_dir 已不存在
  "messages": [
    { "id": "u-...-v1", "role": "user", "content": "...", "version": 1, "timestamp": ... },
    { "id": "a-...-v1", "role": "ai",   "content": "v1 摘要", "version": 1, "files": [...], "timestamp": ... },
    { "id": "a-...-v2", "role": "ai",   "content": "v2 摘要", "version": 2, "files": [...], "timestamp": ... }
  ]
}
```

> ⚠️ 后端不持久化每次 refine 的用户输入文本（state 仅保留最新一条 `refine_request`）。
> 这正是"前端瘦身缓存"补充的部分。

#### 前端：`tpa.msgs.<thread_id>` 瘦身缓存

按线程拆 key、按数量做 LRU、丢弃过程事件，把 localStorage 占用钉死在 ~1 MB 量级。

| 维度 | 选择 | 原因 |
|------|------|------|
| 存储键 | `tpa.msgs.<tid>` 单线程一 key | 改某线程不会引发全量序列化 |
| LRU 上限 | `SLIM_THREAD_LIMIT = 20` | 超出按 `tpa.history.v1.last_active` 顺序裁剪 |
| 持久字段 | `id / role / content / files / version / timestamp / status` | 用户文字 + AI 摘要 + 产物，跨刷新足以重建 UI |
| 丢弃字段 | `logs[]`、`partial_thought`、streaming 占位 | 过程事件刷新后无意义；占主要体积 |
| 触发点 | `task_result`、`error`、`startNewTrip`、`sendRefine` | 都是消息从 streaming → settled 的边界 |

`selectThread(tid)` 走三段式：

1. **秒显**：从 `localStorage` 读瘦身缓存写入 `messages.value`，立即可见。
2. **重连**：`ensureWs(tid)` + `refreshFiles()`。
3. **校准**：`GET /api/trip/{tid}/messages` 拉权威列表，与缓存按 `version` 对齐合并；
   AI 字段以服务端为准，用户消息（含 refine 文本）以缓存为准；
   合并结果写回 `tpa.msgs.<tid>`。
   响应中 `expired=true` 时，把对应历史项标记为已过期，但保留缓存让用户仍能查看。

> 切线程发起的 `loadMessages` 是异步的；返回前若用户又点了别的线程，
> `chat store` 用 `threadId.value !== tid` 守卫直接丢弃过期响应，避免 UI 抖动。

---

## 端到端数据流

### 首次规划

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant FE as Frontend
    participant API as FastAPI
    participant AG as PlanGraph
    participant T as TravelTool
    participant LLM as LLM
    participant W as WebSocket

    U->>FE: 填表与输入诉求, 点击发送
    FE->>API: POST /api/trip
    API-->>FE: 返回 trip_id 与 thread_id, version=1
    FE->>W: 建立 WebSocket 连接 ws/thread_id
    API->>AG: asyncio.create_task 调度 run_plan_agent
    AG->>W: session_created
    AG->>AG: 启动 build_plan_graph 状态机

    loop 每个节点
        AG->>W: node_start
        AG->>T: TravelTool.fetch
        T->>W: tool_start
        T->>T: provider.fetch  Mock 或 Real
        T->>W: tool_end
        AG->>LLM: 调用 Mock 或 GPT-4o
        AG->>W: node_end
    end

    AG->>W: review_iteration  passed
    AG->>AG: render_pdf 生成 trip_v1.md 与 trip_v1.pdf
    AG->>W: task_result 携带 version 与 files
    W-->>FE: 推送事件
    FE->>FE: 更新当前 AI 消息 status=ok
    FE->>API: GET /api/files
```

> 期间，所有 `node_*` / `tool_*` / `review_*` 事件实时进入 `messages[lastAi].logs[]`，`ThoughtProcess` 组件自动显示在折叠面板中。

### 多轮调整

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant FE as Frontend
    participant API as FastAPI
    participant AG as RefineGraph
    participant Sv as InMemorySaver
    participant LLM as LLM
    participant W as WebSocket

    U->>FE: 输入 把第3天换成室内活动
    FE->>API: POST /api/trip/thread_id/refine
    API->>AG: asyncio.create_task 调度 run_refine_agent

    AG->>Sv: aget_tuple 读取上一版 state v_n
    Sv-->>AG: 返回 v_n 完整状态
    AG->>AG: version = v_n + 1

    AG->>LLM: parse_refine_intent
    LLM-->>AG: 返回 RefineIntent 与 dirty_nodes
    AG->>AG: dispatcher_router 选中 plan_itinerary

    AG->>AG: plan_itinerary 然后 estimate_budget 然后 review_plan_lite
    AG->>AG: render_pdf 生成 trip 新版本
    AG->>W: task_result 携带新版本号与 files
    W-->>FE: 推送事件
    FE->>FE: 新 AI 消息就位, FilesSidebar 多出新版 pdf
```

---

## 快速开始

> 默认 MOCK 模式：**零密钥**即可端到端跑通。

### 1. 后端

```bash
pip install -r requirements.txt
PYTHONPATH=. python -m uvicorn api.server:app --reload --port 8000
```

### 2. 前端（新开终端）

```bash
cd ui && npm install && npm run dev
```

打开 **http://localhost:5173** 即可。

| 服务 | URL |
|------|-----|
| 前端 | http://localhost:5173 |
| 后端 | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |
| WebSocket | `ws://localhost:8000/ws/{thread_id}` |

### 3. 不想跑前端？

仓库自带两个**无头冒烟脚本**完整跑通图 + WS 管道：

```bash
# 直跑 plan + refine（生成 trip_v1.md / trip_v2.md）
PYTHONPATH=. python tests/smoke/smoke_test.py

# 端到端 HTTP + Monitor→WS 管道
PYTHONPATH=. python tests/smoke/smoke_http.py
```

---

## 配置项

### 后端 `.env`

```env
# ===== LLM =====
MOCK_LLM=true                              # 默认；改为 false 启用真实模型
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://your-proxy/v1   # 可选代理

# ===== 工具数据源 =====
USE_MOCK_TOOLS=true                        # 改为 false 走 Real Provider 路由

# ===== Real Provider 密钥（USE_MOCK_TOOLS=false 时使用；缺哪个就只那个工具降级 Mock）=====
# 国内天气 — https://console.qweather.com/  控制台 → 项目管理 → API Host
QWEATHER_API_KEY=
QWEATHER_API_HOST=                         # 必填，每人专属（形如 https://abcd1234ef.re.qweatherapi.com）
# 海外天气 — https://openweathermap.org/api  注册后 Key 需 1-2h 激活
OPENWEATHER_API_KEY=
# 机票 + 酒店 — https://developers.amadeus.com/self-service  test env 免费 2000/月
AMADEUS_API_KEY=
AMADEUS_API_SECRET=
# AMADEUS_BASE_URL=https://test.api.amadeus.com   # 默认 test；上生产改 api.amadeus.com
# 国内 POI — https://lbs.amap.com/  应用管理 → 添加 Key（服务平台 = Web 服务）
AMAP_API_KEY=

# ===== 服务 =====
HOST=0.0.0.0
PORT=8000
ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
# 注：若设为 *（默认值，仅本地 demo 方便），后端会自动把 allow_credentials 关掉
# 并打 WARN —— 浏览器规范禁止 "Access-Control-Allow-Origin: *" 与 credentials=true 同时出现。
# 任何要带 cookie / Authorization 的部署都请显式列出 origin。
# PDF_ENGINE=pandoc | weasyprint | word    # 不设则自动选择
```

### 前端 `ui/.env`

仅当前端不走 Vite 代理（独立部署）时才需要：

```env
VITE_API_BASE=http://localhost:8000
VITE_WS_BASE=ws://localhost:8000
```

### 启用真实 PDF（可选）

| 平台 | 命令 |
|------|------|
| macOS | `brew install pandoc && brew install --cask mactex` |
| Debian/Ubuntu | `sudo apt-get install -y pandoc texlive-xetex fonts-noto-cjk` |
| Windows | 安装 MS Office（Word COM 引擎自动可用），或 `pip install pywin32` |
| 任意系统 | `pip install weasyprint markdown`（轻量 fallback） |

不安装任何 PDF 引擎也能跑——只产出 Markdown。

---

## API 参考

### REST

| Method | Path | 说明 |
|--------|------|------|
| `GET`  | `/api/health` | 存活探针 |
| `POST` | `/api/trip` | 启动新规划 → `{trip_id, thread_id, status, version}` |
| `POST` | `/api/trip/{thread_id}/refine` | 提交调整指令 |
| `GET`  | `/api/trip/{thread_id}/versions` | 列出 MD/PDF 各版本 |
| `GET`  | `/api/trip/{thread_id}/messages` | 重建会话消息（用户输入 + 各版本 AI 摘要 + 文件）；`expired=true` 表示 session 目录已不存在 |
| `GET`  | `/api/files?thread_id=X` | 列出该会话目录下所有文件 |
| `GET`  | `/api/download?path=ABS` | 下载文件（路径限定在 `output/` 内） |
| `WS`   | `/ws/{thread_id}` | 服务端→客户端事件流 |

#### `POST /api/trip` 请求体

```jsonc
{
  "conversation_name": "trip_2026_summer",   // 可选，作为 thread_id；缺省自动生成
  "bot_user_input":    "想带 3 岁小孩，避免长途车程",
  "destination":       "大阪",                // 必填
  "departure":         "上海",
  "days_num":          5,                     // 必填 (1~30)
  "people_num":        2,                     // 必填 (1~20)
  "start_date":        "2026-07-15",
  "travel_theme":      "亲子"
}
```

---

## WebSocket 事件协议

客户端连上 `/ws/{thread_id}` 后，**只发送** `"ping"` 字符串作为 25s 心跳；
服务端回包格式统一为 `{ "event": <name>, "data": {...} }`：

| event | 时机 | data |
|-------|------|------|
| `session_created` | agent 入口设置 ContextVar 后 | `{ path }` |
| `node_start` | 每个 LangGraph 节点进入 | `{ node, ts }` |
| `node_end` | 节点结束 | `{ node, duration_ms, summary? }` |
| `tool_start` | TravelTool.fetch 入口 | `{ tool_name, args }` |
| `tool_end` | TravelTool.fetch 完成 | `{ tool_name, summary? }` |
| `review_iteration` | review_plan 每次结果 | `{ iteration, passed, feedback? }` |
| `partial_thought` | 节点中间思考（预留） | `{ text }` |
| `task_result` | finalize 完成 | `{ result, version, files[] }` |
| `error` | 任意层级 try/except | `{ where?, message }` |
| `pong` | 服务端心跳响应 | `{}` |

---

## 冒烟测试

每次后端改动后，两个脚本必须保持绿（与 `pyproject.toml::testpaths = ["tests"]` 对齐）：

```text
tests/smoke/smoke_test.py    plan + refine 各产出 trip_v1.md / trip_v2.md
tests/smoke/smoke_http.py    /api/health + /api/trip + /api/files + /api/.../refine
                             + Monitor→WS 管道（验证 session_created / node_start / node_end /
                                tool_start / tool_end / review_iteration / task_result 至少各一条）
```

---

## 演示行为说明

1. **InMemorySaver** 在进程内按 `thread_id` 隔离 State；
   后端重启后历史会话失效（前端 localStorage 仍记录，但新指令会触发全新规划）。
   切换/刷新会话时不会丢消息——参见 [会话持久化与恢复](#会话持久化与恢复)。
2. **MOCK_LLM** 对 7 类 prompt 都返回结构合规的桩 JSON，离线即可全图跑通。
3. **Mock 工具**输出由输入哈希做种子，**完全确定性**，便于截图与冒烟。
4. **Real Provider 单工具降级**：缺某个 Key 时，仅该工具退回 Mock 并打 warning，其他工具按 `USE_MOCK_TOOLS` 路由继续走真实数据，主流程不受影响（参见 `tools/factory.py` 与 `.env.example`）。
5. **报告 6 大模块**：`plan_itinerary` 与 3 个生成节点（`generate_packing_list` / `generate_cultural_tips` / `generate_pre_trip_checklist`）在 `cluster_pois` 之后并发，再汇入 `estimate_budget`，整图相对原版只多 1 个 LLM 调用的延迟代价。
6. POI fixtures 自带 **东京 / 北京 / 大阪**；其他城市走 Faker 合成池。
7. 单个 fetcher 失败仅写入 `state.errors`，**不阻塞整体行程生成**。
8. PDF 引擎一个都不可用时，只输出 Markdown，前端 `FileCard` 仍可下载。

---

## License

MIT — 仅作 Demo。生产化指南详见 [DESIGN.md §12](./DESIGN.md)。
