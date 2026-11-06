# Architecture

How Travel Planner fits together, from a submitted search to the last section on screen.

---

## Components

```
Browser (React 18 SPA, Vite)
  ├── sseWorker.js  ── POST /api/search  (SSE)
  ├── chatWorker.js ── POST /api/chat    (SSE)
  └── axios         ── everything else  (JSON)
Android app (separate repo) ── the same JSON / SSE API with a Bearer token,
                               plus /api/devices (push) and /api/nearby (Near me)
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
  ├── watch scheduler (background task) ── fare + price watch re-checks (SerpAPI), alert emails (SMTP),
  │                                         alert pushes to registered phones (FCM, optional)
  ├── TTLCache (in memory, 30 min)
  └── SQLite: $DATA_DIR/airports.db (22 tables) ── optional GCS backup every 60 s
            │
            ▼
External: Gemini on Vertex AI (3.5 Flash-Lite, 3.8 Flash; or Anthropic as a fallback),
          SerpAPI, Serper, DuckDuckGo,
          Open-Meteo, walking-tour provider sites, optional SMTP server,
          optional Firebase Cloud Messaging (FCM HTTP v1)
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
text ──────────────────────────────────┼─► LinkImportAgent (agent model; vision for images)
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

Both `/api/search` and `/api/chat` go through `core/sse.guarded_stream`:

- **Keepalives.** It sends a `: keepalive` comment after 15 s of silence (`SSE_KEEPALIVE_SECONDS`). Proxies and phone networks keep the connection, and a vanished client is noticed at the next write.
- **Cancel on disconnect.** When the client goes away before `done`, it cancels every task the stream started, nested ones included, so abandoned agents stop spending tokens and release the LLM semaphore.
  - Tasks are attributed through a context variable that a small task factory reads, so agent code knows nothing about it.
  - Alert pushes start in a fresh context, so they survive.

---

## Source verification

Every non-error section streamed by `/api/search`, and the responses of `/api/{flights,hotels,activities}/filtered`, carry `data.verification`: `{level, label, summary, checks[], items_verified, items_total, pending}`. `backend/app/services/verification.py` computes it from evidence the pipeline already holds: live SerpAPI fares, link checks from enrichment, crawl provenance, Open-Meteo provenance, and comparisons with the static visa and emergency tables. It makes no network or LLM calls. The levels are `verified` ("Verified"), `partial` ("Partly verified"), `unverified` ("AI-generated") and `conflict` ("Check details"). See [Agent System](Agent-System.md#source-verification) for the per-section rules. Chat does not use verification.

---

## Models

Every model call goes through one module, `backend/app/core/llm.py` (`generate`, `stream`, and `generate_sync` for the IATA lookup fallback). `LLM_PROVIDER` picks the provider; callers only name a **role**. The default, `auto`, resolves to `gemini` when `GCP_PROJECT` is set (production), to `anthropic` when only `ANTHROPIC_API_KEY` is set (a typical local `.env`), and otherwise to `gemini` if Application Default Credentials resolve a project, else `anthropic`. The choice is logged once at startup and reported by `/health/agents`.

| Role | Used by | `gemini` (production) | `anthropic` (local dev / rollback) |
|---|---|---|---|
| `agent` | Every specialist agent (`BaseAgent`), packing list, pricing advisor, itinerary, stress test, link import, discovery, layover, the chat-itinerary agent, chat routing, parameter extraction, plan actions and suggestion chips, `/health/agents` | `gemini-3.5-flash-lite` (`GEMINI_MODEL_AGENT`), thinking `minimal` | `claude-haiku-4-5-20251001` |
| `chat` | Chat conversational answers (streamed token by token) and the planning narrative | `gemini-3.8-flash` (`GEMINI_MODEL_CHAT`), thinking `low` | `claude-sonnet-4-6` |

**Gemini on Vertex AI** uses the `google-genai` SDK with `vertexai=True` and Application Default Credentials (the VM's service account in production, `gcloud auth application-default login` locally); there is no API key. The project and location come from `GCP_PROJECT` (empty: the ADC / `GOOGLE_CLOUD_PROJECT` project) and `GCP_LOCATION` (default `global`). Agent prompts (`.agents/*.md`) are sent unchanged as the system instruction; JSON callers also set `response_mime_type: application/json`. Because Gemini counts thinking tokens against `max_output_tokens`, each call adds headroom for the thinking level on top of the caller's budget (512 for `minimal`, 2048 for `low`); only generated tokens are billed. The SDK retries 429/5xx up to 3 times, like the Anthropic client's `max_retries`, and every request has a 120 s timeout (the SDK default is none); network errors from either transport (httpx, or aiohttp when installed) count as capacity errors. The one blocking call, the IATA lookup fallback (`generate_sync`, run during request validation), has an 8 s timeout and no retries. A chat stream the client abandons is closed at once, and its usage is still logged with `aborted=True`. The shared clients are closed on shutdown. At startup `llm.log_provider()` rejects a thinking level the configured Gemini model refuses (`minimal` on Gemini 3.7 or 3.8 Flash, or an unknown level) with a clear error. Vertex reads PNG, JPEG and WebP screenshots but not GIF: on Gemini, `/api/import/extract` converts a GIF to PNG when Pillow is installed and otherwise refuses it (`422 gif_unsupported`). Safety filters are left at the Vertex default, which is off for Gemini 3.5 Flash and later; a blocked reply would arrive as empty text and be retried as unparseable.

`BaseAgent.execute()` makes one `llm.generate` call per attempt with `max_tokens` 16384, behind a global semaphore (`AGENT_MAX_CONCURRENCY`, default 6). See [Agent System](Agent-System.md).

**Usage accounting.** Every call logs one `llm_usage` line: `label` (the agent or chat step), `provider`, `model`, `input_tokens`, `output_tokens`, `thinking_tokens`, `cached_tokens`, `latency_ms`, `truncated`. Prompts and replies are never logged. `llm.record_usage()` collects the same records for a block of code (the eval harness uses it to price a whole search).

**Spend cap.** Production AI spend is hard-capped by a Cloud Billing spend-cap budget on Vertex AI: when it trips, new calls are refused until the 1st of the next month. Google documents no specific API error for this (only that usage is "paused"), so a `403` or `429` whose error *message* (not the help links or metadata in its details) names billing, a budget, a spend cap/limit, a usage limit or the credit balance is treated as the cap, as is an Anthropic `400` about the credit balance or reached usage limits; a plain `429 RESOURCE_EXHAUSTED` stays an ordinary retryable quota error. A `403`/`400` with reason `BILLING_DISABLED` (or "requires billing to be enabled") is not the cap: it gets its own message, "AI features are unavailable right now: billing is disabled for the AI service. Please try again later." (`error_code: "ai_billing"`). Either way `llm` raises a user-facing `LLMError` (`user_code`), logs the HTTP status, status name and ErrorInfo reasons, and refuses further calls for 5 minutes without contacting the provider. Users see "AI limit reached for this month — try again on the 1st.": as a section's `{"error": ..., "error_code": "ai_limit"}` in searches (static-backed sections keep their static data; the Results page shows the text once as a banner), as a chat `delta`, and as `503` from `/api/discover`, `/api/compare/destination`, `/api/import/extract` and `/api/nearby`. `/health/agents` reports `llm: "spend-cap"` (or `"billing-disabled"`).

**Evaluation.** `backend/scripts/llm_eval.py` is a manual tool (never run in CI) that sends the six saved searches in `backend/tests/fixtures/llm_eval/requests.json` (single city, multi-city, family, budget, accessibility, long trip) through the real search pipeline on a chosen provider and model, stores the final sections, per-call usage, latency and estimated cost, and in `compare` mode writes a Markdown report per section (validity, item counts, fields the baseline always had, verification levels, cost per search).

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
| `devices` | Push devices: `id`, `username`, FCM `token` (unique: one owner at a time), `platform` (`android`), `locale`, created and last-seen times; at most 20 per user |

The first six are reference data seeded from files committed to the repo; see [Place and Airport Data](Place-and-Airport-Data.md).

### Backups (optional)

Backups are active only when `BACKUP_BUCKET` is set, in one of two modes (`BACKUP_MODE`):

- **`vm` (production, `backend/app/db/vm_backup.py`).** The persistent disk is the source of truth.
  - **Restore only if missing.** At start the DB is downloaded from `sqlite-backups/airports.db` only when `airports.db` doesn't exist. Stray `-wal`/`-shm` files are deleted first, and the download is checked with `quick_check` and renamed into place atomically.
  - **Mount guard.** That happens only when `DATA_DIR` holds the provisioning marker `.voyager-data-disk`. A missing marker, or a missing DB that GCS can't supply, stops the start rather than run on the wrong directory or empty.
  - **No merge, ever.** A merge would bring back deleted watches, devices, plans and taste resets.
  - **Change-only uploads.** Every 5 min the non-place tables are exported from one read snapshot into a tmpfs. The export is uploaded only when its SHA-256 differs from the last upload, kept in the object's metadata so a restart doesn't re-upload. One more cycle runs at a clean shutdown.
  - **Visible.** `/health` reports `backup_ok`, which the uptime check content-matches.
- **`cloudrun` (legacy, `backend/app/db/backup.py`, the default).** Built for an ephemeral disk. It restores every `*.db` at startup, uploads a snapshot every 60 s with GCS generation checks and an `INSERT OR IGNORE` merge of newer remote data (skipped during a 150 s startup window), and forces one final upload on shutdown.

In both modes the regenerable place tables and the place-data version are left out, so a restored database reseeds them on start. Locally backups are off.

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

## Mobile client and push

The Android app (its own repository) is a second client of the same API: it signs in with the same JWT, streams `/api/search` and `/api/chat`, and reads `/api/notifications`. Two additions exist for it:

- **Push.** The app registers its FCM token with `POST /api/devices` (`devices` table; a token belongs to one user at a time) and forgets it on sign-out with `POST /api/devices/unregister`; tokens travel only in request bodies and are logged masked. When `FCM_SERVICE_ACCOUNT_FILE` is set, or `FCM_USE_ADC=true` (production: the VM's service account, with no key file), `services/push.py` sends every new fare- or price-watch notification to the owner's devices. The hook is the `_notify` helper of each watch service, right after the notification row is stored: `push.notify` (guarded by its own `try`) starts a background task, so alert creation keeps its latency and outcome, and with push off it does nothing; shutdown gives pending pushes 5 s, then cancels them (`push.drain`). The task looks up the user (inactive users are skipped), signs a JWT with the service-account key (google-auth's RS256 signer) and exchanges it for an OAuth access token, or in ADC mode refreshes the metadata-server token in an executor (one exchange at a time, cached until a minute before it expires, dropped on an FCM `401`), and sends one data-only FCM HTTP v1 message per device concurrently over httpx (no `notification` block, so the app builds and dedupes the notification itself): string data `title`, `body`, `kind`, `notification_id`, `link` (the web deep link, `data.links.alerts`), `watch_id` and, for price watches, `watch_kind`. Expired / on-hold notices go at normal Android priority, alerts at high. Only FCM's own verdict that a token is dead deletes it (error code `UNREGISTERED`, or `INVALID_ARGUMENT` with a violation on `message.token`); a bare `404` (a wrong Firebase project) and every other failure is logged and dropped, keeping the token (the alert stays in-app and in email). The app polls `/api/notifications` as a safety net either way.
- **Near me.** `POST /api/nearby` finds the nearest known place to a coordinate (`places_db.nearest_place`: a lat/lng bounding box on the `places` table's `idx_places_lat_lng` index, wrapping the antimeridian, then great-circle distances, up to 75 km; a ward or suburb yields to a place at least 10× bigger within 15 km), then runs the existing activities agent for "Place, Region, Country" (the GeoNames admin1 name tells Portland, Maine from Portland, Oregon; left out when it repeats the name) with the body's interests (else the saved preferences') and the caller's Taste Graph. Results are cached for an hour in their own `TTLCache`, per 0.05° cell, place, interests and taste.

## Cache

One process-wide `cachetools.TTLCache` (`backend/app/core/cache.py`, size `CACHE_MAXSIZE` 500, TTL `CACHE_TTL_SECONDS` 1800) holds full search runs, discover and compare results (complete ones only), the `/health/agents` result, SerpAPI flight results and per-date calendar fares, activity and place link resolutions, Serper places data and walking-tour crawls. It does not survive a restart. Inside `fresh_reads()` (a watch's "Check now") `get_cache()` returns a view in which older entries are misses, so the look is live, and what it fetches is written back for everyone. Near me results have their own one-hour cache (`api/routes/nearby.py`).

---

## Authentication and access

- `POST /api/auth/login` returns an HS256 JWT valid for 24 h (`backend/app/core/auth.py`). Passwords are bcrypt-hashed. There is no registration endpoint; admins create users.
- Most routes require a valid token (`get_current_user`). Admin routes also require `is_admin`.
- `/api/search`, `/api/search/sync`, `/api/discover` and every single-agent ("light_ai") route accept **anonymous** calls, unless `ALLOW_ANONYMOUS_AI=false` (production): then every AI router answers `401` to anonymous callers (`require_ai_access`). They use `get_optional_user`: with a valid token for an active user, the Taste Graph is applied and the rate-limit key is the user; otherwise, including for a deactivated user's token, the caller is anonymous and keyed by client IP. The SPA itself requires login for every page except `/share/:token`.

## Rate limiting

`backend/app/core/rate_limit.py` is an in-process sliding-window limiter attached to routers as a FastAPI dependency (`backend/app/main.py`). Defaults per 10 minutes: search 10, chat 30, compare 30, discover 10, import 20, light_ai 60, and login 10 per client IP. Failed logins lock a username for the failing IP only (10), with a far higher ceiling per username across all IPs (200), both checked before bcrypt, so attackers elsewhere can't lock a user out. Behind Caddy the client IP comes from `X-Forwarded-For`, trusted only from the compose network (`FORWARDED_ALLOW_IPS`), so it can't be spoofed. A chat turn that starts a full trip plan also takes a search token (`try_consume`), answering with a friendly in-stream message when over. Over the limit the API returns `429` with `Retry-After` and a string `detail` that the frontend shows as-is. Being in-process, it only works for a single backend process. See [Configuration](Configuration.md#rate-limits). Fare and price watches share their own daily SerpAPI budget, stored in SQLite (see [Fare-watch scheduler](#fare-watch-scheduler)).

## Middleware

- CORS from `CORS_ORIGINS`.
- `AnalyticsMiddleware` logs every request as JSON, except `/health`, `/docs`, `/openapi.json` and `/redoc`.
- `RequestIdMiddleware` propagates or creates `X-Request-ID`.

UI analytics events are batched by the frontend (`utils/analytics.js`, every 5 s or 10 events) and posted to `POST /api/analytics/events`, which logs them to stdout.
