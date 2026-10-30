# Travel Planner

AI-powered travel planning application that uses specialized Claude agents to produce comprehensive trip plans — flights, weather, hotels, activities, places to see, free walking tours, events, visa info, SIM cards, travel tips, emergency card, local transportation, forex, packing list and a day-by-day itinerary. Open source (MIT). Production on GCP was decommissioned on 2026-08-30; the app runs locally only.

Developer docs live in `docs/` (TitleCase pages, built by mkdocs and synced to the GitHub wiki); `docs_homepage/index.html` is the gh-pages landing page.

## Architecture

### Multi-Agent System

The backend uses a **three-phase orchestrator pattern** (`backend/app/agents/orchestrator.py`):

1. **Phase 0 (instant)** — Static lookup tables yield results for visa, SIM, tips, getting-around and forex, a `confidence` event (Travel Ease grade), and the emergency card, all with `source: 'static'`.
2. **Phase 1 (parallel AI)** — Thirteen specialist agents run **in parallel** (flights, weather, hotels, activities, places-to-see, walking-tours, events, visa, sim, tips, emergency-card, getting-around, forex), 240 s ceiling each. As each completes, its result streams to the frontend. Hotels, activities and places_to_see stream again after URL enrichment. Two deferred agents start mid-phase: packing-list (once activities + weather are in) and pricing-advisor (once flights have ≥ 3 results); both give up after 120 s. For the six static-backed agents, error results are suppressed so the static data remains.
3. **Phase 2** — The itinerary agent synthesises activities + hotels into a day-by-day plan. Starts as soon as both inputs are ready, with a 60-second timeout and template fallback. Once the itinerary is final, a stress-test agent (90 s timeout) adversarially audits the plan (pacing, timings, visa deadlines, weather clashes).

Agent definitions live in `.agents/*.md` (22 files) using YAML frontmatter (`name`, `description`) and a markdown body for the system prompt. They are loaded by `backend/app/agents/loader.py`. `BaseAgent.execute()` makes one Anthropic Messages call per attempt via `AsyncAnthropic` (`claude-haiku-4-5-20251001`, `max_tokens` 16384, no tools), behind a global concurrency semaphore (`AGENT_MAX_CONCURRENCY`, default 6), with up to 4 attempts, exponential backoff on rate limits and a compact-retry when output hits the token cap.

Each specialist agent subclass in `backend/app/agents/` overrides `run(request)` to build a user prompt and parse the JSON result. All execution goes through `BaseAgent` — no per-agent API plumbing. `ToolAgent.enrich()` does background link lookups (DuckDuckGo via `ddgs` in `web_tools.py`; Serper as tier 2).

**Models:** Haiku 4.5 for every specialist agent, the chat-itinerary agent and chat routing/extraction; Sonnet 4.6 (`claude-sonnet-4-6`) only for chat conversational answers and narrative.

### SSE Streaming

The search endpoint (`POST /api/search`) returns a `text/event-stream` response. Each SSE event is `data: {JSON}\n\n` (plus `agent_status` events, keepalive comments, and a final `done`). Complete error-free runs are cached 30 min. The frontend parses the stream via a **Web Worker** (`sseWorker.js`) to keep SSE parsing off the main thread. Results are rendered section-by-section as they arrive.

The chat endpoint (`POST /api/chat`) streams similarly via `chatWorker.js`. Chat is **knowledge-first**: topic questions are answered from the model's own knowledge; specialists run only if the model fails to answer. A planning request streams `planning_start → trip_map → itinerary_generating → comprehensive_itinerary → planning_done` (chat-itinerary agent). `section_result` events appear only in the specialist fallback and refinement paths.

Every non-error section streamed by `/api/search` (and `/flights|hotels|activities/filtered`) carries `data.verification` (`level`: verified / partial / unverified / conflict, plus `label`, `summary`, `checks`, `pending`), computed by `backend/app/services/verification.py` from existing evidence only (pure: no network or LLM calls, never an `error` key). The frontend renders it as a chip + popover in the section header (`VerificationBadge.jsx`); chat does not use it.

### Static Fallback Pattern

Six agents are backed by static lookup tables in `static_results.py` (visa, SIM, tips, getting-around, forex, emergency card) and follow a **static-first, AI-enhanced** pattern:
- Phase 0 sends instant static data with `source: 'static'` → frontend shows it as "Enhancing…"
- Phase 1 sends AI-enhanced data with `source: 'ai'` → frontend replaces static data, status becomes "Done"
- If the AI agent **fails** (returns `{"error": ...}`), the error is suppressed and the static data is retained. Both backend and frontend enforce this.

### Backend — Python / FastAPI

- **Framework**: FastAPI with uvicorn (Python 3.12)
- **Validation**: Pydantic v2 models in `backend/app/schemas/` (`request.py`: `TravelSearchRequest` resolves origin/destination to airport codes)
- **Config**: pydantic-settings with `.env` support (`backend/app/core/config.py`); every setting has a default
- **Auth**: JWT (HS256, PyJWT, 24 h) + bcrypt. **No self-registration** — admins create users (`api/routes/admin.py`). `/search`, `/discover` and single-agent routes accept anonymous calls via `get_optional_user` (inactive users count as anonymous)
- **Persistence**: one SQLite file, `$DATA_DIR/airports.db`, holding all 14 tables (airports, places, place_names, features, feature_names, admin1, meta, nationalities, users, plans, preferences, recent_searches, feedback, taste_signals). Optional GCS backup (`BACKUP_BUCKET`) every 60 s + on shutdown
- **Place data**: OurAirports + GeoNames files committed in `backend/app/db/data/`, versioned seed at startup; `lookup_city_iata` / `resolve_place` resolve typed places to airports locally; country names in any language (`countries.csv` `names`), suburbs yield to namesakes with their own airport (`places.satellite`), and notable islands/parks/mountains resolve via `features.csv.gz`
- **Caching**: in-memory cachetools TTLCache (TTL 30 min, max 500 entries)
- **Rate limits**: in-process sliding window (`core/rate_limit.py`)
- **Logging**: stdlib logging, JSON unless `LOG_FORMAT` is set to something other than `json`

### Frontend — React / Vite

- **Framework**: React 18 with React Router 6 (`react-router-dom` 6.28)
- **Build**: Vite 6 (dev server port 5174, proxies `/api` and `/health` → `http://localhost:8001`)
- **Styling**: Tailwind CSS 3.4
- **Maps**: Leaflet + react-leaflet
- **State**: React context for auth/preferences (`AuthContext.jsx`) and search results (`SearchDataContext.jsx`), local state for selections
- **Streaming**: Web Workers for SSE parsing (`sseWorker.js`, `chatWorker.js`)
- **Pages**: `SearchPage` → `ResultsPage`, `ChatPage`, `PreferencesPage`, `AdminPage`, `LoginPage`, `ChangePasswordPage`, `SharePage` (public)
- **My Plan**: Drawer widget on both ResultsPage and ChatPage for selecting flights, hotels, activities, places, free walking tours, events, SIM plans, tips, transport options, packing items and itinerary slots. Plans are persisted to the backend.

## Project Layout

```
.agents/                22 agent definitions (name + description frontmatter, prompt body):
                        flights, weather, hotels, activities, places, walking_tours, events,
                        visa, sim, tips, emergency_card, getting-around, forex, packing_list,
                        pricing_advisor, itinerary, stress_test, discovery, layover, chat,
                        chat-itinerary, orchestrator (descriptive only)
.github/workflows/      ci.yml, docs.yml, deploy.yml (manual-only, decommissioned)

backend/
  Dockerfile            build from the repo root (copies backend/ and .agents/)
  requirements.txt      runtime deps; requirements-dev.txt for tests/lint
  scripts/build_place_data.py   offline place-data generator
  tests/                pytest suite + data/golden_places.csv
  app/
    main.py             FastAPI app, lifespan (restore → seed → tables → admin → backup loop), routers, /health
    agents/             loader, base_agent, orchestrator, chat_agent, chat_itinerary_agent,
                        *_agent.py specialists, static_results.py, web_tools.py
    api/routes/         one router per domain (27): search, chat, compare, discover, flights,
                        hotels, activities, visa, sim, tips, getting_around, forex, itinerary,
                        events, walking_tours, layover, stress_test, plans, preferences,
                        recent_searches, taste, airports, nationalities, auth, admin,
                        feedback, analytics
    core/               config, auth, cache, rate_limit, logging_config, places (fold_place, hints)
    db/                 database (schema, lookup_city_iata, search_airports), places_db,
                        seed_airports, seed_nationalities, airport_regions, backup,
                        users_db, plans_db, preferences_db, recent_searches_db, feedback_db, taste_db
      data/             committed place data, hints.json, README (sources/licences)
    middleware/         analytics (request logging), request_id
    schemas/            request.py, travel.py
    services/           serp_flights, serper_places, activity/places URL resolvers,
                        walking_tours (crawler), compare, verification, name_match
    utils/geo.py        city coordinates

frontend/src/
  App.jsx, main.jsx     routing, auth guards, always-mounted tabs, attribution footer
  pages/                Search, Results, Chat, Preferences, Admin, Login, ChangePassword, Share
  components/           BestValuePackage, BudgetPlanner, CompareTable, CostBreakdown,
                        FareCalendarStrip, FeedbackWidget, ItinerarySection, OnboardingTour,
                        PlanExport, PlanViewModal, RecentSearches, TimelineView, TripMap,
                        VerificationBadge, WalkingToursSection
    ui/                 AirportSearch, NationalitySearch, NavBar, TagInput, TravelerPanel, AttributionFooter
  context/              AuthContext, SearchDataContext
  hooks/                useFirstRunTour
  services/api.js       axios client + streamSearch and API helpers
  utils/                pure helpers (bestValuePackage, budgetPlanner, compare, fareCalendar,
                        itineraryLayout, schedule, planExport, planPrint, planHelpers, remix, …)
  workers/              sseWorker, chatWorker

infrastructure/         bootstrap scripts + Terraform for GCP (retained, unused)
docs/                   mkdocs sources (canonical TitleCase pages; lowercase files are stubs)
docs_homepage/          gh-pages landing page
```

## Running Locally

```bash
# Both servers (from project root)
./start.sh            # Starts backend (8001) + frontend (5174)
./stop.sh             # Stops both

# Backend only (from backend/)
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload

# Frontend only (from frontend/)
npm install
npm run dev

# Containers (from project root): frontend on 8080, backend on 8001
docker compose up --build
```

Tests: `cd backend && python3 -m pytest -q`; `cd frontend && npm test` (on Node 20.18 prefix `NODE_OPTIONS=--experimental-require-module`). Lint: `ruff check backend/`, `cd frontend && npx eslint src/ --max-warnings 0`. Docs: `mkdocs build --strict`.

## Key Conventions

- **Agent definitions are config, not code.** Edit `.agents/*.md` to change agent behavior (system prompts). The Python agent classes handle prompting, execution and JSON parsing.
- **All agents return JSON.** Every specialist agent outputs a structured JSON object — no prose, no markdown. The `BaseAgent._parse_json()` method has three fallback strategies for extraction.
- **Parallel-first execution.** Independent agents always run concurrently via `asyncio.gather` / `asyncio.create_task`. Only the itinerary (and the stress test after it) depends on prior results.
- **Static-first, AI-enhanced.** Visa, SIM, tips, getting-around, forex and emergency-card have curated static lookup tables that provide instant results. If the AI fails, static data is retained.
- **Two-way preference binding.** Changes on the Search form sync back to Preferences on submit; saved Preferences pre-fill the Search form on load.
- **My Plan selections.** Users can select individual items into a plan drawer, or add the whole rule-based best-value package from the Results page in one click (with Undo). Selections are saved/loaded via the plans API. Moved/removed itinerary activities persist as an overlay in `selections.itinerary_layout` (keyed by original slot, fingerprinted to the itinerary), with edits/notes in `itinerary_edits` / `itinerary_notes`; display, export and share follow it. Itinerary times are derived (`utils/schedule.js`), never stored, except that picked slots keep their scheduled times. Both ResultsPage and ChatPage support the full plan workflow, including the cost breakdown and calendar (.ics) / print-PDF export.
- **Trip comparison.** The Search page's third mode, "Compare", takes 2–3 destinations plus shared trip fields and calls `POST /api/compare/destination` once per destination in parallel (per-column loading/error + Retry); results render in `CompareTable` and "Plan this trip" runs the compared request as a normal full search. Pure helpers live in `frontend/src/utils/compare.js`.
- **Budget planner is client-side.** The Results page budget planner (`utils/budgetPlanner.js`) splits the budget into per-person shares and checks already-loaded results; only "Find cheaper hotels" calls the API (the existing hotel filter).
- **Budget tiers are explicit.** Hotels must cover luxury, premium, mid-range, and budget options. Activities get a model-assigned relevance score 0.0–1.0 (no embedding model).
- **Place data is generated.** Don't hand-edit `backend/app/db/data/*.csv*`; regenerate with `backend/scripts/build_place_data.py`. `hints.json` is hand-curated. GeoNames data is CC BY 4.0 — keep the attribution ("Contains data from GeoNames (geonames.org), CC BY 4.0").

## API

All endpoints are under `/api` (Swagger UI at `/docs`). Full list: `docs/API-Reference.md`.

| Endpoint | Description |
|---|---|
| `POST /api/search` | SSE streaming search — runs all agents (optional auth) |
| `POST /api/search/sync` | Non-streaming search (testing) |
| `POST /api/discover` | "Surprise me" — 5 destination suggestions |
| `POST /api/compare/destination` | One-destination summary (cost, flight, hotel, weather, visa, ease) for Compare mode |
| `POST /api/chat` | SSE streaming chat with plan commands and planning |
| `POST /api/flights`, `/hotels`, `/activities` (+ `/filtered`) | Single agents, with filters |
| `POST /api/flights/fare-calendar` | Cheapest live fare for departure ±3 days (same trip length); auth, single-city, needs `SERPAPI_KEY` (503 otherwise) |
| `POST /api/visa`, `/sim`, `/tips`, `/getting-around`, `/forex`, `/itinerary`, `/events`, `/walking-tours` | Single specialist agents |
| `POST /api/layover`, `POST /api/stress-test` | Layover mini-plan; itinerary audit (Re-check) |
| `POST /api/auth/login`, `POST /api/auth/change-password`, `GET /api/auth/me` | Auth (no registration) |
| `/api/admin/users*`, `GET /api/admin/feedback` | Admin: create/deactivate/reactivate/reset users; feedback |
| `POST /api/feedback`, `POST /api/analytics/events` | Feedback widget; batched UI events |
| `GET/PUT /api/preferences`, `GET/DELETE /api/taste-profile` | Preferences; Taste Graph |
| `GET/POST /api/recent-searches`, `DELETE /api/recent-searches/{id}` | Last 8 searches per user |
| `GET/POST /api/plans`, `GET/PUT/DELETE /api/plans/{id}` | Saved plans |
| `POST/DELETE /api/plans/{id}/share`, `GET /api/share/{token}` | Share links (public read) |
| `GET /api/airports/search`, `GET /api/nationalities/search` | Typeaheads |
| `GET /health`, `GET /health/agents` | Health (reports `serpapi_configured`); deep LLM check |

**Rate limits.** Every AI-calling endpoint is rate-limited per signed-in user (or per client IP when anonymous) in an in-process sliding window (`backend/app/core/rate_limit.py`, wired as router dependencies in `main.py`). Defaults per 10 minutes: search 10 (`/search`, `/search/sync`), chat 30, compare 30, discover 10, light_ai 60 (every single-agent route, `/*/filtered`, `/flights/fare-calendar`, `/stress-test`, `/layover`). Over the limit → `429` with `Retry-After` and a string `detail` the frontend shows as-is. Chat-triggered full plans also count against the search bucket (`ChatAgent._full_plan_refusal` calls `try_consume` before any full plan — at the top of `_run_comprehensive_planning`, or up front for refinements that rebuild the itinerary; over it, a friendly in-stream message instead of a 429). Settings: `RATE_LIMIT_*` (see docs/Configuration.md); tests run with `RATE_LIMIT_ENABLED=false`.

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

Optional: `adults`/`children`/`seniors`/`infants`, `accessibility_needs`, `destinations` + `destination_nights` (multi-city), `pace`, `serendipity`. `taste_context` is set server-side.

## Dependencies

**Backend**: fastapi, uvicorn, pydantic, pydantic-settings, httpx, anthropic, PyJWT, bcrypt, cachetools, pyyaml, ddgs, beautifulsoup4, google-cloud-storage (also listed but not imported: claude-agent-sdk, python-dotenv)

**Frontend**: react, react-dom, react-router-dom 6, leaflet, react-leaflet, axios, lucide-react, @tanstack/react-query (provider only), tailwindcss 3.4, vite 6, vitest (date-fns and clsx are listed but unused)
