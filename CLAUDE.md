# Travel Planner

AI-powered travel planning application that uses specialized Claude agents to produce comprehensive trip plans — flights, hotels, activities, visa info, SIM cards, travel tips, local transportation, and day-by-day itineraries.

## Architecture

### Multi-Agent System

The backend uses a **three-phase orchestrator pattern**:

1. **Phase 0 (instant)** — Static lookup tables yield pre-computed results for visa, SIM, tips, and getting-around. These appear on the UI within ~1 second.
2. **Phase 1 (parallel AI)** — Seven specialist agents run **in parallel** (flights, hotels, activities, visa, sim, tips, getting-around). As each completes, its result streams to the frontend. For agents with static fallbacks, error results are suppressed so the static data remains.
3. **Phase 2 (sequential)** — The itinerary agent synthesises activities + hotels into a day-by-day plan. Starts as soon as both inputs are ready, with a 60-second timeout and template fallback.

Agent definitions live in `.agents/*.md` files using YAML frontmatter (name, description, tools, max_turns) and a markdown body for the system prompt. These are loaded by `backend/app/agents/loader.py` and executed via `claude_agent_sdk.query()` in `BaseAgent.execute()`.

Each specialist agent subclass in `backend/app/agents/` overrides `run(request)` to build a user prompt and parse the JSON result. No raw Anthropic API calls — all execution goes through the SDK.

### SSE Streaming

The search endpoint (`POST /api/search`) returns a `text/event-stream` response. Each SSE event is `data: {JSON}\n\n`. The frontend parses the stream via a **Web Worker** (`sseWorker.js`) to keep SSE parsing off the main thread. Results are rendered section-by-section as they arrive — no waiting for all agents to finish.

The chat endpoint (`POST /api/chat`) streams similarly via `chatWorker.js`. When the chat agent detects a trip-planning request (via regex patterns), it auto-triggers the same specialist agents and streams structured `section_result` events instead of plain text.

### Static Fallback Pattern

Agents backed by static lookup tables (visa, SIM, tips, getting-around) follow a **static-first, AI-enhanced** pattern:
- Phase 0 sends instant static data with `source: 'static'` → frontend shows it as "Enhancing…"
- Phase 1 sends AI-enhanced data with `source: 'ai'` → frontend replaces static data, status becomes "Done"
- If the AI agent **fails** (returns `{"error": ...}`), the error is suppressed and the static data is retained. Both backend and frontend enforce this: backend skips yielding error results for static-backed agents, frontend refuses to overwrite valid data with error responses.

### Backend — Python / FastAPI

- **Framework**: FastAPI with uvicorn
- **Validation**: Pydantic v2 models in `backend/app/schemas/`
- **Config**: pydantic-settings with `.env` support (`backend/app/core/config.py`)
- **Auth**: JWT-based authentication (`backend/app/api/routes/auth.py`)
- **Persistence**: SQLite for plans and user preferences (`plans_db.py`, `preferences_db.py`)
- **Caching**: In-memory via cachetools (TTL 30 min, max 500 entries)
- **Services**: Domain logic in `backend/app/services/` (searchers, rankers, builders)
- **ML**: sentence-transformers + scikit-learn for activity relevance scoring

### Frontend — React / Vite

- **Framework**: React 18 with React Router 7
- **Build**: Vite 6 (dev server port 5174, proxies `/api` → `http://localhost:8001`)
- **Styling**: Tailwind CSS 4
- **State**: React context for auth/preferences (`AuthContext.jsx`), local state for selections
- **Streaming**: Web Workers for SSE parsing (`sseWorker.js`, `chatWorker.js`)
- **Pages**: `SearchPage` → `ResultsPage`, `ChatPage`, `PreferencesPage`
- **My Plan**: Drawer widget on both ResultsPage and ChatPage for selecting flights, hotels, activities, SIM plans, tips, transport options, and itinerary slots. Plans are persisted to the backend.

## Project Layout

```
.agents/              # Agent definition files (frontmatter + system prompt)
  orchestrator.md     # Coordinator — runs all agents
  flights.md          # Flight search specialist
  activities.md       # Activities discovery + relevance scoring
  hotels.md           # Hotel search across budget tiers
  visa.md             # Visa/immigration requirements
  sim.md              # SIM card and eSIM recommendations
  tips.md             # Safety, culture, and practical tips
  getting-around.md   # Local transportation and inter-city travel
  itinerary.md        # Day-by-day itinerary builder
  chat.md             # Conversational chat agent

backend/
  app/
    main.py           # FastAPI app, CORS, router registration
    api/routes/       # One router per domain (POST /api/<domain>)
      auth.py         # Login, registration, JWT tokens
      search.py       # SSE streaming search endpoint
      chat.py         # SSE streaming chat endpoint
      getting_around.py # Transportation options endpoint
      plans.py        # CRUD for saved travel plans
      preferences.py  # User preference management
    agents/           # Python agent classes
      loader.py       # Reads .agents/*.md → AgentDefinition
      base_agent.py   # BaseAgent — executes via claude_agent_sdk
      orchestrator.py # TravelOrchestrator — Phase 0/1/2 streaming
      chat_agent.py   # ChatAgent — conversational + auto-planning
      static_results.py # Lookup tables for instant visa/sim/tips/transport
      *_agent.py      # Specialist agent subclasses
    schemas/          # Pydantic request/response models
      request.py      # TravelSearchRequest
      travel.py       # Domain response models (incl. TransportOption, GettingAroundResponse)
    services/         # Business logic (searchers, rankers, builders)
    core/             # Config, cache, retry utilities
    tools/            # Search and data tools
  tests/              # Unit and integration tests
  requirements.txt    # Python dependencies
  pyproject.toml

frontend/
  src/
    main.jsx          # React entry point
    App.jsx           # Root component with routing
    pages/
      SearchPage.jsx  # Trip input form with preference pre-fill
      ResultsPage.jsx # Streaming results with 8 sections + My Plan drawer
      ChatPage.jsx    # Chat interface with structured planning + My Plan drawer
      PreferencesPage.jsx # User preference management
    components/
      ui/             # Shared UI components (AirportSearch, NationalitySearch, TagInput)
      PlanViewModal.jsx # Modal for viewing/editing saved plans
    context/
      AuthContext.jsx  # Auth state + two-way preference sync
    workers/
      sseWorker.js    # SSE parser for search streaming
      chatWorker.js   # SSE parser for chat streaming
    services/api.js   # Axios API client + streamSearch helper
    data/airports.js  # Static airport data
  index.html
  package.json
  vite.config.js
```

## Running Locally

```bash
# Both servers (from project root)
./start.sh            # Starts backend + frontend
./stop.sh             # Stops both

# Backend only (from backend/)
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload

# Frontend only (from frontend/)
npm install
npm run dev
```

The frontend dev server runs on port **5174** and proxies `/api` requests to the backend on port **8001**.

## Key Conventions

- **Agent definitions are config, not code.** Edit `.agents/*.md` to change agent behavior (system prompts, tools, turn limits). The Python agent classes handle execution and JSON parsing.
- **All agents return JSON.** Every specialist agent outputs a structured JSON object — no prose, no markdown. The `BaseAgent._parse_json()` method has three fallback strategies for extraction.
- **Parallel-first execution.** Independent agents always run concurrently via `asyncio.gather` / `asyncio.create_task`. Only the itinerary agent depends on prior results.
- **Static-first, AI-enhanced.** Visa, SIM, tips, and getting-around agents have curated static lookup tables that provide instant results. AI agents enhance these; if the AI fails, static data is retained (errors are suppressed for static-backed agents).
- **Two-way preference binding.** Changes on the Search form sync back to Preferences on submit; saved Preferences pre-fill the Search form on load.
- **My Plan selections.** Users can select individual items (flights, hotels, activities, SIM plans, tips, transport options, itinerary slots) into a plan drawer. Selections are saved/loaded via the plans API. Both ResultsPage and ChatPage support the full plan workflow.
- **Budget tiers are explicit.** Hotels must cover luxury, premium, mid-range, and budget options. Activities are scored 0.0–1.0 by interest relevance.

## API

All endpoints are under `/api`:

| Endpoint | Description |
|---|---|
| `POST /api/search` | SSE streaming search — runs all agents |
| `POST /api/search/sync` | Non-streaming search (testing) |
| `POST /api/chat` | SSE streaming chat with auto-planning |
| `POST /api/flights` | Search flights for a route |
| `POST /api/activities` | Discover activities at destination |
| `POST /api/hotels` | Find hotels across budget tiers |
| `POST /api/visa` | Check visa requirements |
| `POST /api/sim` | Recommend SIM/eSIM plans |
| `POST /api/tips` | Safety and culture tips |
| `POST /api/getting-around` | Local transportation options |
| `POST /api/itinerary` | Build day-by-day itinerary |
| `POST /api/auth/login` | JWT login |
| `GET /api/auth/me` | Current user info |
| `GET/PUT /api/preferences` | User preferences |
| `GET/POST /api/plans` | Saved travel plans |
| `GET/PUT/DELETE /api/plans/{id}` | Single plan CRUD |
| `GET /health` | Health check |

### TravelSearchRequest

```json
{
  "origin": "NYC",
  "destination": "Tokyo",
  "departure_date": "2026-04-01",
  "return_date": "2026-04-08",
  "interests": ["food", "history", "adventure"],
  "nationality": "American",
  "residence_permits": [],
  "existing_visas": [],
  "budget_usd": 3000,
  "num_travelers": 2
}
```

## Dependencies

**Backend**: fastapi, uvicorn, pydantic, pydantic-settings, httpx, claude-agent-sdk, beautifulsoup4, feedparser, duckduckgo-search, sentence-transformers, scikit-learn, cachetools

**Frontend**: react, react-dom, react-router, @tanstack/react-query, axios, tailwindcss, lucide-react, date-fns, clsx, vite
