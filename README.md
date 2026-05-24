# Travel Planning Agent — Demo (v0.3)

End-to-end demo of the [v0.3 design](./DESIGN.md): **FastAPI + LangGraph + InMemorySaver** backend and **Vue 3 + TypeScript + Vite** Kiro-style chat frontend, fully runnable locally with **zero API keys** thanks to MOCK mode.

> ✈️ Type a destination, days, people count and theme — watch tool calls and graph nodes stream into the thought-process panel in real time, get a Markdown trip report (and optionally PDF), then refine it with natural-language follow-ups.

---

## Quick Start (≤ 1 minute)

```bash
# 1. Backend
cp .env.example .env                        # MOCK mode is the default
pip install -r requirements.txt
PYTHONPATH=. python -m uvicorn api.server:app --reload --port 8000

# 2. Frontend (in a second terminal)
cd ui && npm install && npm run dev
```

Then open **http://localhost:5173** and submit a request.

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend  | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| WebSocket | `ws://localhost:8000/ws/{thread_id}` |

If you can't be bothered to run the frontend, the backend ships with two **headless smoke tests** that exercise the full graph + WS pipeline:

```bash
# pure agent run, MD output
PYTHONPATH=. python scripts/smoke_test.py

# HTTP + Monitor→WS pipeline check
PYTHONPATH=. python scripts/smoke_http.py
```

---

## What's inside

```
TravelPlanningAgent/
├── api/                  FastAPI server, WebSocket manager, Monitor singleton, ContextVar
├── agent/                LangGraph plan_graph + refine_graph, nodes, LLM provider, prompts loader
├── tools/                BaseTravelTool + Mock providers (weather/flight/hotel/POI) + Real-API stubs
├── models/               Pydantic schemas (Trip / Flight / Hotel / POI / RefineIntent + DIRTY_MAP)
├── services/             PDF renderer (Markdown via Jinja2 + best-effort WeasyPrint)
├── prompt/prompts.yaml   Centralised prompt templates
├── templates/            trip_report.md.j2
├── ui/                   Vue 3 + TS + Vite frontend (Kiro-style chat UI)
├── scripts/              smoke tests + run_*.sh helpers
└── DESIGN.md             v0.3 technical design (canonical reference)
```

The runtime data path:

```
HTTP/WS  →  api/server.py           — accepts request, opens WS, schedules asyncio task
            └─ asyncio.create_task ─→ agent/plan_agent.py
                                      └─ ContextVar(session_dir, thread_id)
                                         agent/plan_graph.py  (StateGraph)
                                         ├─ validate_input
                                         ├─ parse_intent       (LLM)
                                         ├─ fetch_weather  ┐
                                         ├─ fetch_flights  │ parallel fan-out
                                         ├─ fetch_hotels   │  (each tool emits
                                         ├─ fetch_pois     ┘   tool_start/end
                                         ├─ cluster_pois          via Monitor)
                                         ├─ plan_itinerary    (LLM)
                                         ├─ estimate_budget
                                         ├─ review_plan       (LLM, can loop)
                                         ├─ render_pdf        (MD + maybe PDF)
                                         └─ finalize          (task_result)
              ↑                              │
              │                              ▼
       WebSocket                api/monitor.py  ──→  asyncio.run_coroutine_threadsafe
              ↑                                            └→ ConnectionManager.send_to_thread
              └────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Backend (.env)

```env
# Demo mode — default. Returns deterministic stub LLM responses.
MOCK_LLM=true

# Switch to real GPT-4o:
MOCK_LLM=false
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://your-proxy/v1     # optional

# Mock data for tools (weather/flight/hotel/POI). Set false to wire real
# providers — adapter stubs live in tools/factory.py per DESIGN.md §5.3.
USE_MOCK_TOOLS=true

# CORS (frontend dev origins by default)
ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### Frontend (ui/.env)

When the frontend is served on its own host (not via the Vite proxy), set:

```env
VITE_API_BASE=http://localhost:8000
VITE_WS_BASE=ws://localhost:8000
```

In dev (`npm run dev`) these are unnecessary because Vite proxies `/api` and `/ws` to `127.0.0.1:8000`.

### Optional: PDF rendering

WeasyPrint requires system libraries (cairo, pango, gdk-pixbuf). The demo runs without it (you'll get a `.md` only). To enable:

```bash
# macOS
brew install pango gdk-pixbuf libffi

# Debian / Ubuntu
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 fonts-noto-cjk

# Then:
pip install weasyprint
```

The renderer auto-detects WeasyPrint and additionally produces `trip_v{N}.pdf` next to the markdown.

---

## API Reference

### REST

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/health` | liveness probe |
| `POST` | `/api/trip` | start a new plan task → returns `{trip_id, thread_id, version}` |
| `POST` | `/api/trip/{thread_id}/refine` | submit a refine instruction for an existing thread |
| `GET`  | `/api/trip/{thread_id}/versions` | list MD/PDF artefacts per version |
| `GET`  | `/api/files?thread_id=X` | list all files in the session output dir |
| `GET`  | `/api/download?path=ABS` | download a file (path-confined to `output/`) |
| `WS`   | `/ws/{thread_id}` | server→client event stream |

### WebSocket events

| event | payload |
|-------|---------|
| `session_created` | `{ path }` |
| `node_start`      | `{ node, ts }` |
| `node_end`        | `{ node, duration_ms, summary? }` |
| `tool_start`      | `{ tool_name, args }` |
| `tool_end`        | `{ tool_name, summary? }` |
| `review_iteration`| `{ iteration, passed, feedback? }` |
| `partial_thought` | `{ text }` |
| `task_result`     | `{ result, version, files[] }` |
| `error`           | `{ where?, message }` |

The client sends only `"ping"` as a string keep-alive every 25s.

---

## Demo behaviour notes

1. **InMemorySaver** holds graph state per `thread_id` for the lifetime of the process.
   Restart the backend → in-flight conversations expire (frontend localStorage shows them as past sessions but new instructions trigger a fresh plan).
2. **MOCK_LLM** returns canned, structurally-correct JSON for `parse_intent`, `parse_refine_intent`, `plan_itinerary`, `review_plan` so the graph runs to completion offline. Switch to GPT-4o by flipping `MOCK_LLM=false` and supplying `OPENAI_API_KEY`.
3. **Mock tools** are deterministic (output seeded by the input hash), so the same query produces the same output every time — useful for screenshots and testing.
4. POI fixtures bundled for **大阪 / 北京 / 东京**; other cities fall back to a Faker-synthesised pool.

---

## Smoke test summary

After backend changes, the two smoke scripts must stay green:

```
scripts/smoke_test.py    plan + refine produce trip_v1.md and trip_v2.md
scripts/smoke_http.py    /api/health + /api/trip + /api/files + /api/trip/.../refine + Monitor→WS pipeline
                         observes: session_created, node_start×12, node_end×12,
                                    tool_start×5, tool_end×5, review_iteration, task_result
```

---

## License

MIT (demo only — see `DESIGN.md` §12 for production hardening guidance).
