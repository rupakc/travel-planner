# ✈️ Travel Planner

> An AI trip planner that runs a team of specialist Claude agents in parallel. Within seconds it streams back flights, hotels, activities, visa rules, local tips, weather and a day-by-day itinerary, and you can edit, budget, export and share the result.

**[Docs site](https://rupakc.github.io/travel-planner/)** · **[Wiki](https://github.com/rupakc/travel-planner/wiki)** · **[Quick start](#quick-start)** · **[Changelog](docs/Changelog.md)**

> **The hosted demo is offline.** Production was decommissioned on 2026-08-30. To try the app, run it locally with `./start.sh` or `docker compose up`. The infrastructure code (Terraform, deploy workflow) is kept for self-hosting; see [Deployment](docs/Deployment.md).

---

## Features

### Plan a trip
- **Three ways to start.** Search a destination you already know. Use **Surprise me**, which suggests 5 destinations with visa status, flight time, a rough cost range and why each one matches you. Or use **Compare**, which puts 2–3 destinations side by side on cost, flight, hotel, weather, visa and Travel Ease.
- **Multi-city trips.** Add up to 3 stops on the way, each with its own number of nights. Flights come per leg, and every section stays in journey order.
- **16 streaming sections:** Flights, Weather, Hotels (across budget tiers), Activities (matched to your interests), Places to See, Free Walking Tours (from GuruWalk, Freetour.com, freewalkingtour.com and SANDEMANs NewEurope), What's On (events during your dates), Visa, SIM Cards, Travel Tips, Emergency Card, Getting Around, Currency & Forex, Itinerary, Trip Health Check and Packing List.
- **Filters** for flights (stops, price, time windows), hotels (beds, price, wifi, distance, private washroom) and activities (interests, price, dates, rating).
- **Layover planner.** Turn a long connection into a timed mini-plan.
- **Trip Remix.** One-click presets: A week later, Half the budget, Make it luxe, Slow it down and Long weekend. Each shows a before/after comparison.

### Know before you go
- Visa requirements for your nationality, residence permits and existing visas.
- An **Emergency Card** with police, ambulance and fire numbers per city, plus your embassy, useful phrases and local laws.
- Day-by-day weather from Open-Meteo, plus SIM/eSIM options, currency advice, safety and culture tips, and local and inter-city transport.
- A **Travel Ease** grade for the destination.
- A weather- and activity-aware **packing list**.

### Budget and fares
- **Best-value package.** A rule-based pick of real listed items that you can add to your plan in one click, with Undo.
- **Budget planner.** Splits your budget into per-person shares and flags or hides over-budget results. It runs entirely in the browser.
- **Fare calendar.** Shows the cheapest live fare for departure dates ±3 days. It needs SerpAPI, a signed-in user and a single-city trip.
- **Price insights** from Google Flights (low / typical / high) and a **pricing advisor** with booking-timing advice.

### Itinerary
- A day-by-day plan with Cards and Timeline views and a route map (Leaflet + OpenStreetMap).
- Drag-and-drop or keyboard "Move to…", swap, remove/restore, Undo and "Free time" rows. Your layout is saved with the plan.
- **Estimated start/end times** based on duration and travel distance.
- Per-slot edits and notes.
- **Trip Health Check.** An adversarial agent audits pacing, timings, visa deadlines and weather clashes. You can re-check after editing.

### Organise and share
- **My Plan drawer** (on Results and Chat). Pick flights (one per leg), a hotel, activities, places, tours, events, SIM, tips, transport, packing items and itinerary slots, and see a cost breakdown.
- Save, rename, load and delete plans.
- Export to a **calendar (.ics)** file or a **print/PDF** page.
- **Share links** open a public, read-only view with personal details removed.
- **Recent searches** (the last 8) that you can re-run in one click.

### Chat
- A conversational travel advisor. Topic questions are answered from the model's own knowledge. The specialist agents step in only when the model can't answer.
- Ask for a full plan and it builds one, with a map and day cards, asking clarifying questions when it needs to. Requests like "make it cheaper" re-run only the affected parts.
- It manages your plan from the conversation ("add this hotel", "show my plan").

### Personalisation
- **Preferences** pre-fill the Search form, and the Search form syncs back to Preferences.
- The **Taste Graph** learns from the plans you save and ranks matching options higher. You can view or reset it on the Preferences page.
- A **discovery slider** goes from famous classics to hidden gems, and a traveller mix (adults, seniors, children, infants) with accessibility needs shapes the results.
- A first-run **onboarding tour** on the Search page.

---

## What's new

See the [Changelog](docs/Changelog.md) for the full history.

- **Comprehensive place data.** Any town in the world (GeoNames, 162k places) resolves to nearby airports (OurAirports, 4,014 airports), and autocomplete suggests places as well as airports.
- **Fare calendar** and Google Flights price insights.
- **Timed itinerary**, with estimated times kept when you pick slots into your plan.
- **Budget planner**, **best-value package** and **side-by-side comparison**.
- **Drag-and-drop itinerary editing**, plus re-checking an edited plan.
- **Source-verification badges** on every result section.
- **Rate limiting** per user or IP on every AI-calling endpoint.
- **Free Walking Tours**, the **onboarding tour**, **calendar/PDF export**, **recent searches** and the **cost breakdown**.
- Housekeeping: MIT [LICENSE](LICENSE), a fixed `docker compose` build, GeoNames/OurAirports credit in the app footer, inactive users' tokens treated as anonymous, and dead code removed.

---

## How it works

```
POST /api/search ──► Phase 0  static lookup tables ─────────────► instant results
                    Phase 1  13 specialist agents in parallel ──► stream as each finishes
                             + packing list, pricing advisor (start when inputs land)
                    Phase 2  itinerary agent ──► stress-test agent ──► done
```

- **Three-phase orchestration** (`backend/app/agents/orchestrator.py`):
  - **Phase 0** sends curated static data for visa, SIM, tips, getting around, forex and the emergency card, plus the Travel Ease grade, straight away.
  - **Phase 1** runs 13 agents concurrently: flights, weather, hotels, activities, places to see, walking tours, events, visa, SIM, tips, emergency card, getting around and forex. Packing list and pricing advisor are deferred and start as soon as their inputs arrive.
  - **Phase 2** builds the itinerary from activities and hotels. It has a 60 s timeout and falls back to a template. The stress test then audits the final plan.
- **Agents are config.** There are 22 agent definitions in `.agents/*.md`: YAML frontmatter plus a system prompt. `BaseAgent` calls the Anthropic Messages API (Claude Haiku 4.5) behind a global concurrency cap (default 6). It backs off on capacity errors and retries with a compact prompt when it hits the token limit. Chat conversation uses Claude Sonnet 4.6.
- **SSE streaming.** `/api/search` and `/api/chat` stream `data: {JSON}` events. The frontend parses them in Web Workers (`sseWorker.js`, `chatWorker.js`) and renders each section as it arrives. A complete search is cached for 30 minutes.
- **Static-first, AI-enhanced.** Static data is shown as "Enhancing…" and the AI result replaces it. If an AI agent fails, the static data stays: the backend suppresses the error and the frontend refuses to overwrite good data with it.
- **Verification badges.** Every result section carries a level: Verified, Partly verified, AI-generated, or Check details for a conflict with reference data. The level comes from existing evidence only (live fares, checked links, crawl and Open-Meteo provenance, the static visa and emergency tables), with no extra network calls (`backend/app/services/verification.py`).
- **Comprehensive place data.** Committed OurAirports and GeoNames snapshots are seeded into SQLite on first start (about 2 s), and reseeded only when the data changes. Typed places resolve to airports locally and deterministically: "Zermatt", "Chicago IL" and "Cologne" all work. See [Place and Airport Data](docs/Place-and-Airport-Data.md).

Details: [Architecture](docs/Architecture.md) · [Agent System](docs/Agent-System.md).

---

## Quick start

### Prerequisites
- **Python 3.12** (3.11+ is supported; CI and Docker use 3.12)
- **Node.js 20+** (CI and Docker use 20; vitest 4 needs `^20 || ^22 || >=24`)
- An **Anthropic API key**

### 1. Configure
Create `backend/.env`. Every setting has a default, but these matter:

```bash
ANTHROPIC_API_KEY=sk-ant-...       # powers every agent
JWT_SECRET_KEY=<long random string> # signs login tokens; must be set
ADMIN_PASSWORD=<choose one>        # seeds the admin user (username: admin); empty = no admin
# Optional
SERPAPI_KEY=...                    # live Google Flights, fare calendar, price insights
SERPER_KEY=...                     # Places to See data and better activity/place links
```

There is no self-registration. Sign in as the admin, then create users on the Admin page. All settings, including `DATA_DIR`, `CORS_ORIGINS`, `AGENT_MAX_CONCURRENCY`, `RATE_LIMIT_*` and `CACHE_*`, are covered in [Configuration](docs/Configuration.md).

### 2. Run

```bash
git clone https://github.com/rupakc/travel-planner.git
cd travel-planner
./start.sh          # backend + frontend; --backend / --frontend for one side
./stop.sh           # stop both (--force to SIGKILL)
```

- Frontend: http://localhost:5174 (Vite proxies `/api` and `/health` to the backend)
- Backend: http://localhost:8001, with interactive API docs at http://localhost:8001/docs
- Logs go to `.logs/backend.log` and `.logs/frontend.log`

To run each side by hand:

```bash
cd backend  && pip install -r requirements.txt && uvicorn app.main:app --port 8001 --reload
cd frontend && npm install && npm run dev
```

### Docker

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or put it in a .env file at the repo root
docker compose up --build
open http://localhost:8080
```

Compose builds the backend from the repo root, serves the frontend through nginx on port 8080, and keeps the SQLite data in the `backend_data` volume. Set `JWT_SECRET_KEY` and `ADMIN_PASSWORD` too, because the compose defaults are for development only.

More detail: [Setup and Installation](docs/Setup-and-Installation.md).

---

## Tests and CI

```bash
# Backend: 3794 tests
cd backend && python3 -m pytest -q
cd backend && python3 -m pytest --cov=app --cov-fail-under=70   # as in CI

# Frontend: 532 tests
cd frontend && npx vitest run
# On Node 20.18 you may need: NODE_OPTIONS=--experimental-require-module npx vitest run

# Lint
ruff check backend/ && ruff format --check backend/
cd frontend && npx eslint src/ --max-warnings 0

# Everything CI checks (lint + security + tests)
make ci
```

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and on PRs to `main`:
- backend and frontend lint;
- a security audit (bandit, pip-audit, npm audit);
- backend tests with at least 70% coverage, and frontend tests;
- Docker image builds with a Trivy scan.

`docs.yml` publishes the docs site from `main`. See [Testing and CI](docs/Testing-and-CI.md).

---

## Project layout

```
.agents/            22 agent definitions (frontmatter + system prompt)
backend/
  app/
    agents/         BaseAgent, orchestrator, chat, specialist agents, static lookup tables
    api/routes/     one router per domain (search, chat, plans, compare, admin, ...)
    core/           config, auth, cache, rate limiting, place-name folding
    db/             SQLite schema, place resolution, seeding, committed place data
    services/       SerpAPI/Serper clients, walking-tour crawler, verification, compare
  scripts/          offline place-data generator
  tests/
frontend/src/
  pages/            Search, Results, Chat, Preferences, Admin, Share, Login
  components/       feature components + ui/
  utils/            pure helpers (budget, schedule, export, compare, ...)
  workers/          SSE parsers (sseWorker, chatWorker)
docs/               documentation sources (published to the docs site)
infrastructure/     Terraform + scripts for GCP (kept for self-hosting)
```

---

## Documentation

The docs live on the **[docs site](https://rupakc.github.io/travel-planner/)** and the **[wiki](https://github.com/rupakc/travel-planner/wiki)**, with sources in `docs/`:

| Page | What's in it |
|---|---|
| [Home](docs/Home.md) | Overview and where to start |
| [Setup and Installation](docs/Setup-and-Installation.md) | Local development and Docker |
| [Configuration](docs/Configuration.md) | Every environment variable |
| [Architecture](docs/Architecture.md) | Phases, streaming, caching, persistence |
| [Agent System](docs/Agent-System.md) | Agent definitions and execution |
| [Trip Planning Features](docs/Trip-Planning-Features.md) | Every user-facing feature |
| [Multi-City Trips](docs/Multi-City-Trips.md) | Up to three stops, per-leg flights and stays |
| [Chat Assistant](docs/Chat-Assistant.md) | Conversational planning and Q&A |
| [Personalization](docs/Personalization.md) | Preferences and the two-way form binding |
| [Sharing and Plans](docs/Sharing-and-Plans.md) | Saved plans, share links, exports |
| [Place and Airport Data](docs/Place-and-Airport-Data.md) | Sources, resolution rules, regeneration |
| [API Reference](docs/API-Reference.md) | All REST and SSE endpoints |
| [Deployment](docs/Deployment.md) | Self-hosting (the hosted demo is offline) |
| [Testing and CI](docs/Testing-and-CI.md) | Test suites, lint and workflows |
| [Contributing](docs/Contributing.md) | Workflow and conventions |
| [Changelog](docs/Changelog.md) | What changed, and when |

---

## Built with

- **AI**: [Anthropic Claude](https://www.anthropic.com) via the `anthropic` Python SDK (Haiku 4.5 for the agents, Sonnet 4.6 for chat)
- **Backend**: Python 3.12, FastAPI, Uvicorn, Pydantic v2 and pydantic-settings, SQLite, cachetools, httpx, BeautifulSoup, ddgs, PyJWT and bcrypt
- **Frontend**: React 18, React Router 6.28, Vite 6, Tailwind CSS 3.4, TanStack Query 5, axios, Leaflet / react-leaflet, lucide-react, Vitest 4
- **Data and services**: Open-Meteo (weather), SerpAPI (Google Flights, optional), Serper.dev (places, optional), OurAirports, GeoNames
- **Tooling**: ruff, ESLint, pre-commit, GitHub Actions, Trivy, Docker, MkDocs Material

---

## Data credits

- Contains data from **GeoNames** ([geonames.org](https://www.geonames.org/)), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The data has been modified (filtered, folded, scored and linked to airports), and GeoNames does not endorse these changes.
- Airport data from **[OurAirports](https://ourairports.com/data/)**, public domain.

The sources, licences and derivation rules are in [`backend/app/db/data/README.md`](backend/app/db/data/README.md).

---

## License

[MIT](LICENSE) © 2026 Rupak Chakraborty
