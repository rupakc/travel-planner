# Travel Planner

AI-powered travel planning application that uses specialized Claude agents to produce comprehensive trip plans — flights, weather, hotels, activities, places to see, free walking tours, events, visa info, SIM cards, travel tips, emergency card, local transportation, forex, packing list and a day-by-day itinerary. Open source (MIT). Production: one always-free e2-micro VM on GCP (project `voyager-prod-ohzkl`, us-east1): Caddy + the app container, SQLite on the persistent disk; every green merge to `main` deploys (signed images pulled by the VM every minute: app, then the SPA + Caddyfile swapped in without restarting Caddy; only a Caddy runtime change recreates Caddy, after draining SSE streams; only images whose build inputs changed are rebuilt, so a frontend-only merge never restarts the app; merge → live ≈ 4.5–6 min frontend-only, ≈ 5.5–8.5 min with backend changes). The app and the SPA ship independently (separate images, promoted separately; either can go live before the other, or alone), so changes must work in both mixes: frontend changes must tolerate the previous backend (feature-detect new endpoints/fields), and backend changes must keep serving the previous SPA (no removed or renamed endpoints, fields or semantics without a deprecation step: add the new one, ship the SPA that uses it, remove the old one in a later merge). The Cloud Run production was decommissioned on 2026-08-30. Runbook: `docs/Deployment-GCP.md`.

Developer docs live in `docs/` (TitleCase pages, built by mkdocs and synced to the GitHub wiki); `docs_homepage/index.html` is the gh-pages landing page.

## Architecture

### Multi-Agent System

The backend uses a **three-phase orchestrator pattern** (`backend/app/agents/orchestrator.py`):

1. **Phase 0 (instant)** — Static lookup tables yield results for visa, SIM, tips, getting-around and forex, a `confidence` event (Travel Ease grade), and the emergency card, all with `source: 'static'`.
2. **Phase 1 (parallel AI)** — Thirteen specialist agents run **in parallel** (flights, weather, hotels, activities, places-to-see, walking-tours, events, visa, sim, tips, emergency-card, getting-around, forex), 240 s ceiling each. As each completes, its result streams to the frontend. Hotels, activities and places_to_see stream again after URL enrichment. Two deferred agents start mid-phase: packing-list (once activities + weather are in) and pricing-advisor (once flights have ≥ 3 results); both give up after 120 s. For the six static-backed agents, error results are suppressed so the static data remains.
3. **Phase 2** — The itinerary agent synthesises activities + hotels into a day-by-day plan. Starts as soon as both inputs are ready, with a 60-second timeout and template fallback. Once the itinerary is final, a stress-test agent (90 s timeout) adversarially audits the plan (pacing, timings, visa deadlines, weather clashes).

Agent definitions live in `.agents/*.md` (22 files) using YAML frontmatter (`name`, `description`) and a markdown body for the system prompt. They are loaded by `backend/app/agents/loader.py`. `BaseAgent.execute()` makes one model call per attempt through `core/llm.py` (agent model, JSON output, `max_tokens` 16384, no tools), behind a global concurrency semaphore (`AGENT_MAX_CONCURRENCY`, default 6), with up to 4 attempts, exponential backoff on rate limits and a compact-retry when output hits the token cap.

Each specialist agent subclass in `backend/app/agents/` overrides `run(request)` to build a user prompt and parse the JSON result. All execution goes through `BaseAgent` — no per-agent API plumbing. `ToolAgent.enrich()` does background link lookups (DuckDuckGo via `ddgs` in `web_tools.py`; Serper as tier 2).

**Models:** every model call goes through `backend/app/core/llm.py` (`generate`, `stream`, `generate_sync`), which picks the provider from `LLM_PROVIDER`. `auto` (the default) picks `gemini` when `GCP_PROJECT` is set, or when no `ANTHROPIC_API_KEY` is configured and Application Default Credentials resolve a project; otherwise `anthropic` — so prod (GCP_PROJECT set) runs Gemini and a local `.env` with only an Anthropic key keeps Claude. The resolved provider is logged at startup and reported by `/health/agents` (`llm_provider`, `llm_provider_reason`).
- `gemini`: Gemini on Vertex AI with Application Default Credentials (no API key; `GCP_PROJECT`, `GCP_LOCATION` default `global`). **Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`, thinking `minimal`, JSON mode) for every specialist agent, packing, pricing advisor, itinerary, stress test, link import, discovery, layover, the chat-itinerary agent and chat routing/extraction; **Gemini 3.8 Flash** (`gemini-3.8-flash`, thinking `low`) only for chat conversational answers (streamed token by token) and narrative.
- `anthropic` (local dev / rollback, needs `ANTHROPIC_API_KEY`): Haiku 4.5 (`claude-haiku-4-5-20251001`) and Sonnet 4.6 (`claude-sonnet-4-6`) in the same two roles.

Every call logs an `llm_usage` line (label, model, input/output/thinking tokens, latency; never content). AI spend is hard-capped by a GCP spend-cap budget: a 403/429 that names billing/budget becomes `LLMError(spend_cap=True)`, later calls fail fast for 5 min, sections get `{"error": "AI limit reached for this month — try again on the 1st.", "error_code": "ai_limit"}`, chat sends that text as a `delta`, and `/discover`, `/compare/destination`, `/import/extract` and `/nearby` answer `503`; `BILLING_DISABLED` gets its own message (`ai_billing`). Gemini calls time out at 120 s (`generate_sync`: 8 s, no retries); a thinking level the model rejects fails startup. `generate_grounded` (Gemini only; Anthropic → `grounding_unavailable`, 503 on its routes) runs one text-output call with Google Search or Maps grounding and returns text + grounding chunks/supports/queries; used only by `/live-check` and Near me v2, whose results Google's terms keep to the requesting user (no storage, cache or scheduled use — watches/alerts stay on SerpAPI). Vertex reads no GIF: link import converts GIF→PNG with Pillow, else `422 gif_unsupported`. `backend/scripts/llm_eval.py` (manual, never CI) runs the six saved searches in `backend/tests/fixtures/llm_eval/` on a provider/model and compares two runs into a Markdown report.

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
- **Persistence**: one SQLite file, `$DATA_DIR/airports.db`, holding all 25 tables (airports, places, place_names, features, feature_names, admin1, meta, nationalities, users, plans, preferences, recent_searches, feedback, taste_signals, notifications, devices, fare_watches, fare_watch_history, fare_watch_quota, fare_watch_user_quota, price_watches, price_watch_history, telemetry_daily, telemetry_daily_totals, telemetry_rollups); raw product-telemetry events are the one exception, `telemetry_events` in a separate `$DATA_DIR/telemetry.db` (WAL, pruned after `TELEMETRY_RETENTION_DAYS` = 90, never backed up; the daily rollup tables above are). Optional GCS backup (`BACKUP_BUCKET`): `BACKUP_MODE=vm` in production (disk authoritative, restore only if the DB is missing and `DATA_DIR/.voyager-data-disk` exists, no merge, user tables uploaded when their hash changes every 5 min + at shutdown, `backup_ok` in `/health`; `db/vm_backup.py`); default `cloudrun` mode is the legacy restore-every-start + 60 s merge (`db/backup.py`)
- **Place data**: OurAirports + GeoNames files committed in `backend/app/db/data/`, versioned seed at startup; `lookup_city_iata` / `resolve_place` resolve typed places to airports locally; country names in any language (`countries.csv` `names`), suburbs yield to namesakes with their own airport (`places.satellite`), and notable islands/parks/mountains resolve via `features.csv.gz`
- **Caching**: in-memory cachetools TTLCache (TTL 30 min, max 500 entries)
- **Rate limits**: in-process sliding window (`core/rate_limit.py`)
- **Telemetry**: `POST /api/telemetry` (anonymous-friendly, own `telemetry` bucket, 204; 404 when `TELEMETRY_ENABLED=false` or `telemetry.db` could not be opened at startup; a global disk guard drops batches, still 204, past `TELEMETRY_MAX_DB_MB` = 1024 (file + WAL) or `TELEMETRY_MAX_EVENTS_PER_DAY` = 200000 per UTC day) validates every event against the closed registry `telemetry/registry.py` (unknown events/props dropped; props are tokens, numbers, booleans or enums, so no free text), appends to `telemetry.db` (`db/telemetry_db.py`); an hourly lifespan task (`telemetry/maintenance.py`) rolls up UTC days and prunes. `GET /api/config` hands clients `public_base_url`, telemetry settings and feature flags; `GET /api/admin/telemetry/summary?days=` feeds the admin Analytics tab (`users_7d` included). Docs: `docs/Telemetry.md` (event table, a registry test requires every event be listed there), `docs/Privacy.md`.
- **UI language**: AI-calling requests accept `locale` (`en es de fr hi zh bn`, default English); `BaseAgent.execute(locale=)` appends a language instruction to the system prompt and the search cache keys per language (`core/cache.request_digest`; English keys unchanged). Static Phase 0 tables stay English.
- **Logging**: stdlib logging, JSON unless `LOG_FORMAT` is set to something other than `json`

### Frontend — React / Vite

- **Framework**: React 18 with React Router 6 (`react-router-dom` 6.28)
- **Build**: Vite 6 (dev server port 5174, proxies `/api` and `/health` → `http://localhost:8001`)
- **Styling**: Tailwind CSS 3.4
- **Maps**: Leaflet + react-leaflet
- **State**: React context for auth/preferences (`AuthContext.jsx`) and search results (`SearchDataContext.jsx`), local state for selections
- **Streaming**: Web Workers for SSE parsing (`sseWorker.js`, `chatWorker.js`)
- **Pages**: `SearchPage` → `ResultsPage`, `ChatPage`, `PreferencesPage`, `AdminPage` (Users, Feedback, Analytics tabs), `LoginPage`, `ChangePasswordPage`, `SharePage` (public)
- **Theme**: light default, dark via Tailwind `darkMode: 'class'` (`html.dark`). Colours come from `frontend/design/tokens.json` → `npm run tokens` → generated `src/theme/tokens.css` (CSS variables, never hand-edited); `src/theme/ThemeContext.jsx` (`system|light|dark`, `localStorage tp_theme`); `public/theme-init.js` sets the class before first paint (external because CSP is `script-src 'self'`). Docs: `docs/Theming.md`.
- **i18n**: i18next + react-i18next, 7 languages (en es de fr hi zh bn); catalogues `src/i18n/locales/<lang>/<ns>.json` (13 namespaces; en bundled, others lazy chunks), plurals `_one/_other`, keys `ns:area.thing`, language in `localStorage tp_lang`, `src/i18n/format.js` (`fmtNumber/fmtCurrency/fmtDate/fmtRelative`); `src/i18n/catalog.test.js` fails on any missing key, bad plural form, or placeholder/tag mismatch. New UI strings go in all 7 languages. Docs: `docs/Internationalization.md`.
- **Telemetry SDK**: `src/telemetry/` (`client.js` queue/batching, `consent.js`, `autocapture.js`, `perf.js`, `routes.js`); never blocks the UI, switches itself off on a 404 from `/api/config`; routes are templates; EU/EEA/UK/CH timezones are opted out until the user answers `ConsentPrompt` (`tp_consent`), Preferences has the switch. Interactive elements carry `data-tid` (the element name in telemetry, never its text). Social sign-in buttons (`components/auth/`) show "coming soon" until `GET /api/auth/providers` exists (Phase 1).
- **Parity**: `docs/Feature-Parity.md` lists each feature per client (web / Android / iOS); update it with any client-visible feature.
- **My Plan**: Drawer widget on both ResultsPage and ChatPage for selecting flights, hotels, activities, places, free walking tours, events, SIM plans, tips, transport options, packing items and itinerary slots. Plans are persisted to the backend.

## Project Layout

```
.agents/                22 agent definitions (name + description frontmatter, prompt body):
                        flights, weather, hotels, activities, places, walking_tours, events,
                        visa, sim, tips, emergency_card, getting-around, forex, packing_list,
                        pricing_advisor, itinerary, stress_test, discovery, layover, chat,
                        chat-itinerary, orchestrator (descriptive only)
.github/workflows/      ci.yml (also reusable; PRs/branches: build-only image checks, path-filtered),
                        docs.yml, prod-scan.yml (daily Trivy of both :prod images), deploy.yml (push to
                        main + weekly no-cache refresh, also forced by any run when prod's io.voyager.fresh-at is >8 days old: `ci` ∥ `build-app` / `build-caddy` [skip if `prod`'s
                        io.voyager.{app,caddy}-inputs = deploy/ci/image-inputs-id.sh, else build → GHCR
                        → Trivy] → `promote-app` / `promote-caddy`, each only if ci + its build passed:
                        deploy/ci/promote-image.sh = HEAD check → cosign sign + verify → move `prod`;
                        no VM/GCP access)

deploy/gcp/             VM kit: compose.yaml (app + caddy), Caddyfile, caddy.Dockerfile (SPA + Caddyfile
                        inside; label io.voyager.caddy-runtime from caddy-runtime-id.sh),
                        app.env.example,
                        host/ (first-boot.sh, deploy.sh signed-digest deployer: app + edge releases in
                        /var/lib/voyager/edge (current/prev1/prev2 symlinks, admin-API reload, drain +
                        recreate on runtime change, rollback), governor.py egress governor, window.sh
                        weekly reboot window, systemd units), tests/ (test_deploy.py + fakes)
deploy/ci/              deploy workflow scripts (not shipped to the VM): image-inputs-id.sh (build-inputs
                        hash), build-decision.sh, promote-image.sh, trivy-scan.sh (the one Trivy
                        policy); tests/

backend/
  Dockerfile            build from the repo root (copies backend/ and .agents/)
  requirements.txt      runtime deps; requirements-dev.txt for tests/lint
  scripts/build_place_data.py   offline place-data generator
  scripts/llm_eval.py           offline LLM provider/model eval (run + compare)
  tests/                pytest suite + data/golden_places.csv
  app/
    main.py             FastAPI app, lifespan (restore → seed → tables → admin → backup loop), routers, /health
    agents/             loader, base_agent, orchestrator, chat_agent, chat_itinerary_agent,
                        *_agent.py specialists, static_results.py, web_tools.py
    api/routes/         one router per domain (36): search, chat, compare, discover, flights,
                        hotels, activities, visa, sim, tips, getting_around, forex, itinerary,
                        events, walking_tours, layover, stress_test, plans, preferences,
                        recent_searches, taste, airports, nationalities, auth, admin,
                        feedback, analytics, link_import, fare_watches, price_watches,
                        notifications, devices, nearby, live_check, telemetry, client_config
    telemetry/          registry (closed event schema), maintenance (hourly rollup + prune)
    core/               config, llm (provider seam), auth, cache, rate_limit, logging_config, places (fold_place, hints)
    db/                 database (schema, lookup_city_iata, search_airports), places_db,
                        seed_airports, seed_nationalities, airport_regions, backup,
                        users_db, plans_db, preferences_db, recent_searches_db, feedback_db, taste_db,
                        fare_watch_db, price_watch_db, notifications_db, devices_db, telemetry_db
      data/             committed place data, hints.json, README (sources/licences)
    middleware/         analytics (request logging), request_id
    schemas/            request.py, travel.py
    services/           serp_flights, serper_places, activity/places URL resolvers,
                        walking_tours (crawler), compare, verification, name_match,
                        fare_watch, price_watch, price_rules, hotel_prices, activity_prices,
                        alert_email, push (FCM)
      price_sources/    one price-watch source per kind: hotel, activity, trip
    utils/geo.py        city coordinates

frontend/src/
  App.jsx, main.jsx     routing, auth guards, always-mounted tabs, attribution footer
  pages/                Search, Results, Chat, Preferences, Admin, Login, ChangePassword, Share
  components/           BestValuePackage, BudgetPlanner, CompareTable, CostBreakdown,
                        FareCalendarStrip, FeedbackWidget, ItinerarySection, OnboardingTour,
                        PlanExport, PlanViewModal, RecentSearches, TimelineView, TripMap,
                        VerificationBadge, WalkingToursSection, ConsentPrompt
    admin/              TelemetrySummary (Analytics tab)
    auth/               SocialSignInButtons
    ui/                 AirportSearch, NationalitySearch, NavBar, TagInput, TravelerPanel, AttributionFooter,
                        LanguagePicker, ThemeToggle
  context/              AuthContext, SearchDataContext (+ AlertsContext)
  i18n/                 index (i18next set-up), format, languages, locales/<lang>/<ns>.json
  telemetry/            client, consent, autocapture, perf, routes
  theme/                ThemeContext, themeStorage, tokens.css (generated)
  hooks/                useFirstRunTour
  services/api.js       axios client + streamSearch and API helpers
  utils/                pure helpers (bestValuePackage, budgetPlanner, compare, fareCalendar,
                        itineraryLayout, schedule, planExport, planPrint, planHelpers, remix, …)
  workers/              sseWorker, chatWorker
frontend/design/tokens.json   colour tokens (source of truth); frontend/public/theme-init.js anti-flash

infrastructure/gcp/     bootstrap.sh (idempotent gcloud, --dry-run, --update-host),
                        migrate_old_prod.py (old-prod export → user tables), tests/
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

LLM locally: with `LLM_PROVIDER=auto` (default) a `backend/.env` holding only `ANTHROPIC_API_KEY` keeps using Claude. For Gemini, run `gcloud auth application-default login` and set `GCP_PROJECT` (e.g. `voyager-prod-ohzkl`).

Tests: `cd backend && python3 -m pytest -q` (model clients are stubbed in `conftest.py`; tests never reach Vertex or Anthropic); deploy kit: `python3 -m pytest -q deploy/gcp/tests infrastructure/gcp/tests`, `shellcheck -x deploy/gcp/*.sh deploy/gcp/host/*.sh deploy/gcp/tests/*.sh infrastructure/gcp/*.sh` (CI's ubuntu-latest has shellcheck 0.9; check with `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.9.0 -x …`), deploy tests need Linux (`deploy/gcp/tests/host_checks.sh` in `debian:trixie`); `cd frontend && npm test` (on Node 20.18 prefix `NODE_OPTIONS=--experimental-require-module`). Lint: `ruff check backend/`, `cd frontend && npx eslint src/ --max-warnings 0`. Docs: `mkdocs build --strict`.

## Key Conventions

- **Agent definitions are config, not code.** Edit `.agents/*.md` to change agent behavior (system prompts). The Python agent classes handle prompting, execution and JSON parsing.
- **All agents return JSON.** Every specialist agent outputs a structured JSON object — no prose, no markdown. The `BaseAgent._parse_json()` method has three fallback strategies for extraction.
- **Parallel-first execution.** Independent agents always run concurrently via `asyncio.gather` / `asyncio.create_task`. Only the itinerary (and the stress test after it) depends on prior results.
- **Static-first, AI-enhanced.** Visa, SIM, tips, getting-around, forex and emergency-card have curated static lookup tables that provide instant results. If the AI fails, static data is retained.
- **Two-way preference binding.** Changes on the Search form sync back to Preferences on submit; saved Preferences pre-fill the Search form on load.
- **My Plan selections.** Users can select individual items into a plan drawer, or add the whole rule-based best-value package from the Results page in one click (with Undo). Selections are saved/loaded via the plans API. Moved/removed itinerary activities persist as an overlay in `selections.itinerary_layout` (keyed by original slot, fingerprinted to the itinerary), with edits/notes in `itinerary_edits` / `itinerary_notes`; display, export and share follow it. Itinerary times are derived (`utils/schedule.js`), never stored, except that picked slots keep their scheduled times. Both ResultsPage and ChatPage support the full plan workflow, including the cost breakdown and calendar (.ics) / print-PDF export.
- **Trip comparison.** The Search page's third mode, "Compare", takes 2–3 destinations plus shared trip fields and calls `POST /api/compare/destination` once per destination in parallel (per-column loading/error + Retry); results render in `CompareTable` and "Plan this trip" runs the compared request as a normal full search. Pure helpers live in `frontend/src/utils/compare.js`.
- **Plan from a link.** The Search page's "From a link ✨" mode sends a URL, pasted text or 1–4 screenshots to `POST /api/import/extract` (SSRF-safe fetch in `services/link_fetch.py`, `link_import` agent, place resolution and grouping in `services/link_import.py`, `import` rate bucket, default 20). The reviewed places go into a normal search as `must_include` plus `import_source`: they lead Activities, and `services/must_include.py` makes sure every one is scheduled in the itinerary (`from_link` slots, `link_extras`, `link_coverage`).
- **Fare watch & alerts.** `/api/fare-watches` + `/api/notifications`; a lifespan scheduler (`services/fare_watch.py`, only with `SERPAPI_KEY`) re-checks leased watches within a daily SerpAPI budget, and the pure `evaluate()` holds the trigger + anti-spam rules (one alert per check; separate own-dates / nearby-dates references; repeats need a further max($15, 5 %) drop unless re-armed by a rebound; never on the baseline; 24 h cap); optional SMTP email (`services/alert_email.py`); optional FCM push to the Android app's registered devices (`services/push.py`, fire-and-forget from each watch service's `_notify`, only with `FCM_SERVICE_ACCOUNT_FILE`); UI in `components/alerts/`, `pages/AlertsPage.jsx`, `context/AlertsContext.jsx`.
- **Price watch (hotels, activities, trips).** `/api/price-watches` on the same scheduler, SerpAPI budget and active limit as fare watch; each kind is a `PriceSource` in `services/price_sources/` (`hotel`, `activity`, `trip`, registered via `SOURCE_MODULES`), shared own-price rules in `services/price_rules.py` (steps: fares/hotels max($15, 5 %), activities max(1 unit, 5 %), trips max($25, 4 %)). Honesty: prices are observed or labelled estimates; estimates are frozen and never alert; no live part → `422 no_live_price`; activity prices come from Google results for GetYourGuide/Viator listings, never scraped, in the listing's currency; a trip's flight is the cheapest fare on the dates.
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
| `GET/POST /api/devices`, `DELETE /api/devices/{id}`, `POST /api/devices/unregister` | Android push devices (FCM tokens: masked in lists, only ever in bodies; auth) |
| `POST /api/nearby` | Near me: nearest known place to `lat`/`lng` + activities there (auth, light_ai, cached 1 h per ~5 km cell); `sections: true` → v2: see/eat/shop/stay from one Google-Maps-grounded Gemini call, items only from Maps chunks, `attribution`, `sources`, never cached |
| `POST /api/live-check` | "Search the web now" for one of the caller's watches (`kind` flight/hotel/activity/trip + `watch_id`, 404 if not theirs): prompt built from the stored watch, Google Search grounding, `summary`/`quotes`/`sources`/`searched_for`; never stored or cached (auth, light_ai; 502 `live_check_failed`) |
| `POST /api/telemetry` | Batch (≤ 100) of product-telemetry events from any client; gzip accepted, 64 KB cap; closed registry, always 204 for a well-formed batch; 404 when disabled; own `telemetry` bucket (60 / 10 min), dropped past the global disk guard (still 204), never behind `ALLOW_ANONYMOUS_AI` |
| `GET /api/config` | Public client config: `public_base_url`, `telemetry {enabled, flush_interval_s, max_batch}`, `features`; `Cache-Control: max-age=300` |
| `GET /api/admin/telemetry/summary` | Admin: daily users/sessions/events, top events and screens, `users_7d` (`days` 1–90) |
| `GET /health`, `GET /health/agents` | Health (reports `serpapi_configured`, `push_configured`); deep LLM check on the configured provider (`llm`, `llm_provider`) |

**Rate limits.** Every AI-calling endpoint is rate-limited per signed-in user (or per client IP when anonymous) in an in-process sliding window (`backend/app/core/rate_limit.py`, wired as router dependencies in `main.py`). Defaults per 10 minutes: search 10 (`/search`, `/search/sync`), chat 30, compare 30, discover 10, light_ai 60 (every single-agent route, `/*/filtered`, `/flights/fare-calendar`, `/stress-test`, `/layover`, `/nearby`, `/live-check`). Over the limit → `429` with `Retry-After` and a string `detail` the frontend shows as-is. Chat-triggered full plans also count against the search bucket (`ChatAgent._full_plan_refusal` calls `try_consume` before any full plan — at the top of `_run_comprehensive_planning`, or up front for refinements that rebuild the itinerary; over it, a friendly in-stream message instead of a 429). `/telemetry` has its own `telemetry` bucket (`RATE_LIMIT_TELEMETRY`, 60). `/auth/login` has its own `login` bucket (10 per IP) plus a per-username failure lock (20). `ALLOW_ANONYMOUS_AI=false` (production) makes every AI router require sign-in. Settings: `RATE_LIMIT_*` (see docs/Configuration.md); tests run with `RATE_LIMIT_ENABLED=false`.

**Production runtime.** The image runs `python -m app.entrypoint`: optional Secret Manager secrets (`SECRET_MANAGER_SECRETS`) into the process env only, refuses an empty `JWT_SECRET_KEY`, execs uvicorn (1 worker, `--timeout-graceful-shutdown 5`, proxy headers only from `FORWARDED_ALLOW_IPS`, never `*`). `/search` and `/chat` stream through `core/sse.guarded_stream` (15 s keepalives; every task the stream started is cancelled when the client disconnects). Push can use ADC (`FCM_USE_ADC`). `GET /internal/streams` (`{"active_streams": n}`, 404 when forwarded, not routed by Caddy) lets the VM's deployer drain before recreating Caddy.

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

**Backend**: fastapi, uvicorn, pydantic, pydantic-settings, httpx, google-genai (Gemini on Vertex AI, pinned 2.34.0), anthropic (fallback provider), PyJWT, bcrypt, cachetools, pyyaml, ddgs, beautifulsoup4, google-cloud-storage, google-auth (FCM signing)

**Frontend**: react, react-dom, react-router-dom 6, i18next 26.5.11, react-i18next 17.1.9, leaflet, react-leaflet, axios, lucide-react, @tanstack/react-query (provider only), tailwindcss 3.4, vite 6, vitest (date-fns and clsx are listed but unused)
