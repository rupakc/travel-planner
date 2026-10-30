# Architecture

How Travel Planner fits together, from a submitted search to the last section on screen.

---

## Components

```
Browser (React 18 SPA, Vite)
  ├── sseWorker.js  ── POST /api/search  (SSE)
  ├── chatWorker.js ── POST /api/chat    (SSE)
  └── axios         ── everything else  (JSON)
            │
            ▼
FastAPI backend (uvicorn, one process)
  ├── middleware: CORS, request logging, X-Request-ID
  ├── routers: one per domain, rate-limit dependency on AI routes
  ├── TravelOrchestrator ── Phase 0 static tables
  │                       ├── Phase 1: 13 specialist agents in parallel (+2 deferred)
  │                       └── Phase 2: itinerary → stress test
  ├── ChatAgent ── routing, knowledge answers, comprehensive planning
  ├── services: SerpAPI flights, Serper places, link resolvers,
  │             walking-tour crawler, verification, compare
  ├── TTLCache (in memory, 30 min)
  └── SQLite: $DATA_DIR/airports.db (12 tables) ── optional GCS backup every 60 s
            │
            ▼
External: Anthropic API (Haiku 4.5, Sonnet 4.6), SerpAPI, Serper, DuckDuckGo,
          Open-Meteo, walking-tour provider sites
```

In the container setup, nginx serves the built frontend and proxies `/api/` and `/health` to the backend.

---

## The search pipeline

`POST /api/search` (`backend/app/api/routes/search.py`) checks the cache, then streams `TravelOrchestrator.stream_run()` (`backend/app/agents/orchestrator.py`).

### Phase 0: static data (instant)

Lookup tables in `backend/app/agents/static_results.py` produce, in this order: visa, sim, tips, getting_around and forex; then a `confidence` event (the Travel Ease grade); then emergency_card. All carry `source: "static"`, and the UI marks those sections "Enhancing…" until the AI version arrives.

### Phase 1: thirteen agents in parallel

flights, weather, hotels, activities, places_to_see, walking_tours, events, visa, sim, tips, emergency_card, getting_around and forex start together. Each has a 240 s ceiling. A section is yielded as soon as its agent finishes, with `source: "ai"`.

- **Static-backed agents** (visa, sim, tips, getting_around, forex, emergency_card): if the AI result is an error, it is not yielded, so the Phase 0 data stays. The frontend also refuses to replace valid data with an error.
- **URL enrichment**: hotels, activities and places_to_see are yielded first with `verification.pending = true`, then again after their links have been searched and checked.
- **Deferred agents**: `packing_list` starts once activities and weather are both in (template fallback after 120 s or on error). `pricing_advisor` starts once flights have at least 3 results (skipped after 120 s or on error).

### Phase 2: itinerary and stress test

The itinerary agent starts as soon as activities and hotels are both in, not after all of Phase 1. After 60 s, or on an empty or malformed result, a template itinerary built from the available activities is used instead. Once the itinerary is final, the stress-test agent audits it (pacing, timings, visa deadlines, weather clashes) with a 90 s timeout.

The stream always ends with `{"type": "done"}`. While agents run, the server sends `: keepalive` comments.

`POST /api/search/sync` runs the same agents sequentially and returns one JSON object; it is meant for testing.

### Caching

A complete, error-free run is stored as its list of SSE events in the TTL cache for 30 minutes, keyed by the md5 of the request JSON (which includes the user's Taste Graph context), and replayed instantly on a repeat. Runs with any error are never cached.

---

## SSE envelope

```
data: {"type": "visa", "data": {...}, "source": "static"}

data: {"type": "agent_status", "agent": "flights", "status": "searching"}

data: {"type": "flights", "data": {..., "verification": {...}}, "source": "ai"}

data: {"type": "itinerary", "data": {...}}

data: {"type": "done"}
```

The full list of event types is in [API Reference](API-Reference.md#post-apisearch). The frontend parses the stream in a Web Worker (`frontend/src/workers/sseWorker.js`) so that large JSON payloads do not block rendering. If the stream ends without `done`, the worker reports an interruption and the page says so.

---

## Source verification

Every non-error section streamed by `/api/search`, and the responses of `/api/{flights,hotels,activities}/filtered`, carry `data.verification`: `{level, label, summary, checks[], items_verified, items_total, pending}`. `backend/app/services/verification.py` computes it from evidence the pipeline already holds: live SerpAPI fares, link checks from enrichment, crawl provenance, Open-Meteo provenance, and comparisons with the static visa and emergency tables. It makes no network or LLM calls. The levels are `verified` ("Verified"), `partial` ("Partly verified"), `unverified` ("AI-generated") and `conflict` ("Check details"). See [Agent System](Agent-System.md#source-verification) for the per-section rules. Chat does not use verification.

---

## Models

| Use | Model |
|---|---|
| Every specialist agent (`BaseAgent`), the chat-itinerary agent, chat routing, parameter extraction and plan actions, `/health/agents` | `claude-haiku-4-5-20251001` |
| Chat conversational answers and planning narrative | `claude-sonnet-4-6` |

`BaseAgent.execute()` makes one `AsyncAnthropic.messages.create` call per attempt with `max_tokens` 16384, behind a global semaphore (`AGENT_MAX_CONCURRENCY`, default 6). See [Agent System](Agent-System.md).

---

## Persistence

There is one SQLite file, `$DATA_DIR/airports.db` (`backend/app/db/database.py`), opened in WAL mode with `synchronous=NORMAL` and a 5 s busy timeout. Despite its name it holds every table:

| Table | Holds |
|---|---|
| `airports` | Airports from OurAirports plus the curated list (IATA, ICAO, name, served city, country, coordinates, region, rank, `scheduled`) |
| `places` | GeoNames places with their linked airports |
| `place_names` | Folded own and alternate names for place lookup |
| `admin1` | First-level divisions (states, provinces) |
| `meta` | Key/value, including `place_data_version` |
| `nationalities` | 202 nationality → country rows for the nationality typeahead |
| `users` | Accounts: bcrypt hash, `is_admin`, `is_first_login`, `is_active` |
| `plans` | Saved plans: search data, selections (JSON), share token |
| `preferences` | Saved preferences per user |
| `recent_searches` | Up to 8 per user |
| `feedback` | Feedback widget submissions |
| `taste_signals` | Taste Graph signals mined from saved plans |

The first six are reference data seeded from files committed to the repo; see [Place and Airport Data](Place-and-Airport-Data.md).

### Backups (optional)

`backend/app/db/backup.py` is active only when `BACKUP_BUCKET` is set. At startup it restores every `*.db` under `sqlite-backups/` in the bucket. Every 60 s it uploads a snapshot, using GCS generation checks: if another instance wrote newer data, it merges that data with `INSERT OR IGNORE` first, and it skips uploads during a 150 s startup window. On shutdown it forces one final upload. Snapshots leave out the regenerable place tables and the place-data version, so a restored database reseeds them on start. This was built for Cloud Run's ephemeral disk; locally it is off.

---

## Cache

One process-wide `cachetools.TTLCache` (`backend/app/core/cache.py`, size `CACHE_MAXSIZE` 500, TTL `CACHE_TTL_SECONDS` 1800) holds full search runs, discover and compare results (complete ones only), the `/health/agents` result, SerpAPI flight results and per-date calendar fares, activity and place link resolutions, Serper places data and walking-tour crawls. It does not survive a restart.

---

## Authentication and access

- `POST /api/auth/login` returns an HS256 JWT valid for 24 h (`backend/app/core/auth.py`). Passwords are bcrypt-hashed. There is no registration endpoint; admins create users.
- Most routes require a valid token (`get_current_user`). Admin routes also require `is_admin`.
- `/api/search`, `/api/search/sync`, `/api/discover` and every single-agent ("light_ai") route accept **anonymous** calls. They use `get_optional_user`: with a valid token for an active user, the Taste Graph is applied and the rate-limit key is the user; otherwise, including for a deactivated user's token, the caller is anonymous and keyed by client IP. The SPA itself requires login for every page except `/share/:token`.

## Rate limiting

`backend/app/core/rate_limit.py` is an in-process sliding-window limiter attached to routers as a FastAPI dependency (`backend/app/main.py`). Defaults per 10 minutes: search 10, chat 30, compare 30, discover 10, light_ai 60. A chat turn that starts a full trip plan also takes a search token (`try_consume`), answering with a friendly in-stream message when over. Over the limit the API returns `429` with `Retry-After` and a string `detail` that the frontend shows as-is. Being in-process, it only works for a single backend process. See [Configuration](Configuration.md#rate-limits).

## Middleware

- CORS from `CORS_ORIGINS`.
- `AnalyticsMiddleware` logs every request as JSON, except `/health`, `/docs`, `/openapi.json` and `/redoc`.
- `RequestIdMiddleware` propagates or creates `X-Request-ID`.

UI analytics events are batched by the frontend (`utils/analytics.js`, every 5 s or 10 events) and posted to `POST /api/analytics/events`, which logs them to stdout.
