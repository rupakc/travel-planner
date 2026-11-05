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
  ├── watch scheduler (background task) ── fare + price watch re-checks (SerpAPI), alert emails (SMTP)
  ├── TTLCache (in memory, 30 min)
  └── SQLite: $DATA_DIR/airports.db (21 tables) ── optional GCS backup every 60 s
            │
            ▼
External: Anthropic API (Haiku 4.5, Sonnet 4.6), SerpAPI, Serper, DuckDuckGo,
          Open-Meteo, walking-tour provider sites, optional SMTP server
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

## Plan from a link

`POST /api/import/extract` (`backend/app/api/routes/link_import.py`) turns a link, pasted text or screenshots into a preview the traveller reviews before anything is planned:

```
url ──► link_fetch.read_link ──► text ─┐
text ──────────────────────────────────┼─► LinkImportAgent (Haiku; vision for images)
images (sniffed, ≤4 × 5 MB) ───────────┘        │  untrusted-data fencing, Pydantic validation
                                                ▼
                     link_import.build_preview: resolve_place per city → stops
                     (day trips merged, ≤3 stops, nights split) → Serper POI lookups
                                                ▼
                     ImportPreview ──► review in the browser ──► POST /api/search
                                                   with must_include + import_source
```

`link_fetch` is the only place the backend fetches a user-supplied URL. It vets every DNS answer and every redirect hop, and connects to the vetted IP with the original Host and SNI (see [API Reference](API-Reference.md#post-apiimportextract)). In the search, `ActivitiesAgent` merges the places into its results (`services/must_include.merge_into_activities`). `ItineraryAgent` lists them as must-schedule in its prompt and runs `ensure_must_include` on its result, and the orchestrator's template fallback runs the same check, so every itinerary reports `link_coverage`.

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
| `fare_watches` | Watched fares: trip, alert settings, baseline / last / lowest prices, per-signal alert state (last alerted price and time, peak since), Google's verdict, status, schedule and lease |
| `fare_watch_history` | Each check's prices (up to 120 rows per watch) |
| `fare_watch_quota` | SerpAPI calls spent by fare watches per UTC day |
| `fare_watch_user_quota` | The same per user, for the per-user daily share |
| `price_watches` | Watched hotel / activity / trip prices: `kind`, the matched `subject` (JSON, kind-specific), `match_key`, title and subtitle, alert settings, baseline / last / lowest prices, alert state (last alerted price and time, peak since), `last_observation` (JSON: status, unit price, source, link, trip breakdown), failure and unavailable streaks, `expires_on`, status, schedule and lease |
| `price_watch_history` | Each look: total price (null when unavailable), trip breakdown and raw observed details as JSON (up to 120 rows per watch) |
| `notifications` | In-app notifications (fare and price alerts, watch ended / on hold), read and emailed times |

The first six are reference data seeded from files committed to the repo; see [Place and Airport Data](Place-and-Airport-Data.md).

### Backups (optional)

`backend/app/db/backup.py` is active only when `BACKUP_BUCKET` is set. At startup it restores every `*.db` under `sqlite-backups/` in the bucket. Every 60 s it uploads a snapshot, using GCS generation checks: if another instance wrote newer data, it merges that data with `INSERT OR IGNORE` first, and it skips uploads during a 150 s startup window. On shutdown it forces one final upload. Snapshots leave out the regenerable place tables and the place-data version, so a restored database reseeds them on start. This was built for Cloud Run's ephemeral disk; locally it is off.

---

## Fare-watch scheduler

`backend/app/services/fare_watch.py`, started in the `lifespan` (`start_scheduler`) only when `SERPAPI_KEY` is set and `FARE_WATCH_ENABLED` is true, and cancelled on shutdown.

- Every `FARE_WATCH_TICK_SECONDS` (300) it sweeps notifications older than 180 days (once per UTC day), ends paused / on-hold watches whose departure day has come, and lists up to 50 due active watches. Each one is **leased** only when its turn comes (`claim_watch(..., due_only=True)`: one `UPDATE` that also checks it is still active, due and unleased; `lease_until` = now + 10 min), so a watch taken meanwhile by "Check now" or another scheduler is skipped, and a slow batch never outlives its leases; a crashed worker's lease simply expires. Creating a watch and "Check now" take the same lease for their inline check.
- Leased watches are checked three at a time (`check_watch`): departure reached → `expired` + one notice; otherwise the check's SerpAPI cost is estimated (cached fares are free) and reserved all-or-nothing from the day's `FARE_WATCH_DAILY_CALL_BUDGET` and from the owner's share of it (`FARE_WATCH_USER_DAILY_SHARE`) (over either → moved to early next UTC day; the pool running out is logged once); the fare comes from `serp_flights.watch_fares` (the fare calendar's outbound-stage price plus Google's insights, and the calendar's ±3 days for flexible watches, reusing a cached search). A failure retries in 1 h, three in a row put the watch on hold (`error` + one notice); SerpAPI's own quota error postpones without a strike. A watch deleted while its fares were fetched ends as `deleted` with nothing recorded. A success appends history, applies `evaluate` (the pure trigger and anti-spam rules, with separate references for the trip's own dates and the nearby dates, re-armed after rebounds; see [Trip Planning Features](Trip-Planning-Features.md#fare-watch-and-price-alerts)), stores at most one notification, emails it when enabled (`alert_email.py`, `smtplib` in a thread, failures only logged), and schedules the next check in `FARE_WATCH_INTERVAL_HOURS` ±10 %.
- The tests never start the loop (`FARE_WATCH_ENABLED=false`); they drive `run_due` and `check_watch` with an injected clock and fetch.
- The same loop then runs the price-watch pass (`price_watch.run_due`, below); a failing pass of either kind is logged and never stops the other.

### Shared alert rules

`backend/app/services/price_rules.py` holds the kind-agnostic own-price rules both kinds of watch use: the reference (baseline, last alerted price, or the peak once re-armed), the step (`FARE_STEP` max($15, 5 %), also used by hotels; `ACTIVITY_STEP` max(1 unit of the listing currency, 5 %); `TRIP_STEP` max($25, 4 %) for whole-trip totals), target re-arming, the baseline-already-good rule, the 24 h cooldown cap and the state a check leaves behind. Fare watches add their Google-"low" and nearby-dates signals on top. `test_price_rules_equivalence.py` checks the extraction against a frozen copy of the original fare rules.

## Price watches

Hotel, activity and whole-trip prices are watched by `backend/app/services/price_watch.py`, with tables in `db/price_watch_db.py` and routes in `api/routes/price_watches.py`. The pipeline is generic; each kind plugs in a **price source**:

- `PriceSource` (protocol): `kind`; `match_key(spec)` (dedupe key from the client's spec, no live calls); `async create(spec, user, api_key)` → `CreatedWatch` (matched `subject`, baseline `PriceObservation`, title, subtitle, `expires_on`, `plan_id`) or `NoLivePrice` (message, up to 3 live `suggestions`, the AI `estimate`); `async check(watch, api_key)` → `PriceObservation`; `estimate_calls(watch)`; `compose(kind, watch, obs, ref)` → the alert's title, body and extra data; optional `step`, `max_create_calls` (the most calls `create` may spend, default 1: hotel 2, activity 2, trip 10) and `existing_watch(user_id, created)` (the same subject found another way: hotel by property, stay, guests and rooms; activity by listing and travellers).
- `PriceObservation`: `price` (the total, in the watch's currency: USD, except an activity watch, which keeps its listing's currency), `unit_price`, `status` (`ok` / `unavailable`), `source`, `link`, `breakdown` (trips), `observed` (raw details), `calls`.
- Hotels everywhere (a hotel watch, and a trip's hotel) are priced for `hotel_prices.rooms_for(guests)` rooms: one room for up to 4 guests, then one per 4 (the UI's `hotelGuests` mirrors it). A trip's hotel baseline is the property look by `property_token` — the look every check makes — never the search list's price, so an unchanged trip never shows a hotel drop.
- A spec's `city` may be the airport code the search form stores ("LIS"), or "City, Country" (cut at the comma): the hotel and activity sources and the trip component builder name it from the local airport data (`database.airport_city`, no web lookup), so subjects, alert copy and Google queries say "Lisbon". A multi-city trip's activities use their own leg's city.
- Sources register with `register_source`; built-in ones are listed in `price_watch.SOURCE_MODULES` (each module exposes `SOURCE`) and registered in the `lifespan`. Tests use a fake `test` source only.

Creating a watch holds the kind's worst case (`max_create_calls`: hotel 2, activity 2, trip 10) from the shared daily budget and the owner's share, all or nothing (refused with `429` when either can't cover it), lets the source match and take the baseline, then gives back what it didn't spend (`fare_watch_db.adjust_calls`; settlement never charges more than the hold, so price spending can't postpone fare checks). A failure whose spend is unknown keeps the whole hold. Calls are counted as made: a lookup answered from the 30-minute cache is free. A failed check's text is stored and logged redacted (`price_watch.redact_error`: the HTTP status without the response body, never the key). The baseline is stored as the first check (never an alert). Each later check (`check_watch`, leased exactly like fare checks, three at a time) reserves its worst case, `estimate_calls`, all or nothing from the **same** budget as fare watches and settles it to `obs.calls` afterwards (in practice only giving calls back) (a failing `create` may report its spend as `exc.calls`); expires on `expires_on`; postpones on a spent budget or SerpAPI quota; retries a failure in 1 h and puts the watch on hold after three (a crash in the source's own code after the live look, e.g. in `compose`, counts as a failure too, so a broken watch is never retried every tick); records an `unavailable` look (sold out, listing gone) without alert or strike, holding the watch only after three in a row; and otherwise applies the shared rules to the total, storing at most one `<kind>_drop` / `<kind>_target` notification (data carries `watch_kind`, `watch_id` and `links.alerts` = `/alerts?kind=<kind>&watch=<id>`) and emailing it when enabled (`alert_email.deliver_price`, its own unsubscribe token). `FARE_WATCH_MAX_ACTIVE_PER_USER` counts fare and price watches together. Estimates are frozen at creation and never alert on their own; a source never presents an estimate as a live price.

The fare scheduler (`fare_watch.run_scheduler`) runs the fare pass on every tick and starts the price pass (`price_watch.run_due`) as its own task, so a slow price pass never delays fare checks; at most one price pass is in flight (a tick that finds one running starts none), and stopping the scheduler cancels and awaits it.

## Cache

One process-wide `cachetools.TTLCache` (`backend/app/core/cache.py`, size `CACHE_MAXSIZE` 500, TTL `CACHE_TTL_SECONDS` 1800) holds full search runs, discover and compare results (complete ones only), the `/health/agents` result, SerpAPI flight results and per-date calendar fares, activity and place link resolutions, Serper places data and walking-tour crawls. It does not survive a restart.

---

## Authentication and access

- `POST /api/auth/login` returns an HS256 JWT valid for 24 h (`backend/app/core/auth.py`). Passwords are bcrypt-hashed. There is no registration endpoint; admins create users.
- Most routes require a valid token (`get_current_user`). Admin routes also require `is_admin`.
- `/api/search`, `/api/search/sync`, `/api/discover` and every single-agent ("light_ai") route accept **anonymous** calls. They use `get_optional_user`: with a valid token for an active user, the Taste Graph is applied and the rate-limit key is the user; otherwise, including for a deactivated user's token, the caller is anonymous and keyed by client IP. The SPA itself requires login for every page except `/share/:token`.

## Rate limiting

`backend/app/core/rate_limit.py` is an in-process sliding-window limiter attached to routers as a FastAPI dependency (`backend/app/main.py`). Defaults per 10 minutes: search 10, chat 30, compare 30, discover 10, import 20, light_ai 60. A chat turn that starts a full trip plan also takes a search token (`try_consume`), answering with a friendly in-stream message when over. Over the limit the API returns `429` with `Retry-After` and a string `detail` that the frontend shows as-is. Being in-process, it only works for a single backend process. See [Configuration](Configuration.md#rate-limits). Fare and price watches share their own daily SerpAPI budget, stored in SQLite (see [Fare-watch scheduler](#fare-watch-scheduler)).

## Middleware

- CORS from `CORS_ORIGINS`.
- `AnalyticsMiddleware` logs every request as JSON, except `/health`, `/docs`, `/openapi.json` and `/redoc`.
- `RequestIdMiddleware` propagates or creates `X-Request-ID`.

UI analytics events are batched by the frontend (`utils/analytics.js`, every 5 s or 10 events) and posted to `POST /api/analytics/events`, which logs them to stdout.
