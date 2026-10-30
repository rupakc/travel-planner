# API Reference

The backend is a FastAPI app (`backend/app/main.py`). Every endpoint is under `/api` except `/health` and `/health/agents`. A running instance serves Swagger UI at `/docs`, ReDoc at `/redoc` and the schema at `/openapi.json`; locally that is http://localhost:8001/docs.

**Authentication.** Send the token from `POST /api/auth/login` as `Authorization: Bearer <token>`. Tokens are HS256 JWTs valid for 24 hours. In the tables below:

- **user**: a valid token for an active user is required (`401` otherwise).
- **admin**: the user must also be an admin (`403` otherwise).
- **optional**: anonymous calls are allowed. With a valid token for an active user, the Taste Graph is applied and rate limits count per user; otherwise (including a deactivated user's token) the caller is anonymous and counted per IP.
- **none**: no token needed.

---

## Rate limits

Endpoints that call the AI agents are rate-limited per caller (the signed-in user, or the client IP for anonymous requests) over a sliding 10-minute window (`backend/app/core/rate_limit.py`). Every accepted request counts, including cached responses and requests later rejected as invalid (`422`) or unauthenticated (`401`); only requests answered with `429` do not.

| Bucket | Endpoints | Default limit |
|---|---|---|
| search | `POST /api/search`, `POST /api/search/sync` | 10 |
| chat | `POST /api/chat` | 30 |
| compare | `POST /api/compare/destination` | 30 |
| discover | `POST /api/discover` | 10 |
| light_ai | `POST /api/flights`, `/hotels`, `/activities` and their `/filtered` variants, `/flights/fare-calendar`, `/visa`, `/sim`, `/tips`, `/getting-around`, `/forex`, `/itinerary`, `/events`, `/walking-tours`, `/layover`, `/stress-test` | 60 |

Each bucket is counted separately. Over the limit the API answers `429 Too Many Requests` with a `Retry-After` header (seconds) and:

```json
{"detail": "Too many requests — please wait 42 seconds and try again."}
```

Limits are configurable (see [Configuration](Configuration.md#rate-limits)). The counter is in-process, so each backend process counts on its own.

---

## Endpoint index

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | none | Username and password → JWT |
| POST | `/api/auth/change-password` | user | Change own password; returns a new token |
| GET | `/api/auth/me` | user | Current user |
| POST | `/api/admin/users` | admin | Create a user with a temporary password |
| GET | `/api/admin/users` | admin | List users (no password hashes) |
| DELETE | `/api/admin/users/{username}` | admin | Deactivate a user (not yourself) |
| POST | `/api/admin/users/{username}/reactivate` | admin | Reactivate a user |
| POST | `/api/admin/users/{username}/reset-password` | admin | Set a new password |
| POST | `/api/feedback` | user | Submit feedback |
| GET | `/api/admin/feedback` | admin | List feedback (filters `page`, `category`, `min_rating`) |
| POST | `/api/analytics/events` | user | Batch of up to 50 UI events, logged as JSON; `204` |
| POST | `/api/search` | optional | SSE streaming search (all agents) |
| POST | `/api/search/sync` | optional | Same run, one JSON response (testing) |
| POST | `/api/discover` | optional | 5 destination suggestions |
| POST | `/api/compare/destination` | user | One-destination summary for Compare mode |
| POST | `/api/chat` | user | SSE chat with plan commands and planning |
| GET, POST | `/api/plans` | user | List own plans; save a plan |
| GET, PUT, DELETE | `/api/plans/{id}` | user | Get, rename/update, delete own plan |
| POST | `/api/plans/{id}/share` | user | Create (or return) the public share token |
| DELETE | `/api/plans/{id}/share` | user | Revoke the share token (no UI uses it) |
| GET | `/api/share/{token}` | none | Public, sanitised shared plan |
| GET, PUT | `/api/preferences` | user | Get or update preferences |
| GET, POST | `/api/recent-searches` | user | Last 8 searches; record one |
| DELETE | `/api/recent-searches/{id}` | user | Remove one (`204`, or `404`) |
| GET, DELETE | `/api/taste-profile` | user | Learned taste profile; reset it |
| GET | `/api/airports/search?q=&limit=` | none | Airport and place typeahead |
| GET | `/api/nationalities/search?q=&limit=` | none | Nationality typeahead |
| POST | `/api/flights`, `/api/flights/filtered` | optional | Flights agent; with filters |
| POST | `/api/flights/fare-calendar` | user | Cheapest live fare for departure ±3 days |
| POST | `/api/hotels`, `/api/hotels/filtered` | optional | Hotels agent; with filters |
| POST | `/api/activities`, `/api/activities/filtered` | optional | Activities agent; with filters |
| POST | `/api/visa`, `/api/sim`, `/api/tips`, `/api/getting-around`, `/api/forex` | optional | Single specialist agents |
| POST | `/api/itinerary` | optional | Itinerary agent |
| POST | `/api/events` | optional | Events agent (no frontend caller) |
| POST | `/api/walking-tours` | optional | Crawled free walking tours |
| POST | `/api/layover` | optional | Layover mini-plan |
| POST | `/api/stress-test` | optional | Audit an itinerary |
| GET | `/health` | none | Liveness and `serpapi_configured` |
| GET | `/health/agents` | none | Deep check with one tiny Haiku call (cached 5 min) |

The single-agent routes accept anonymous calls; only the rate limit protects them.

---

## Auth

### POST /api/auth/login

```json
{ "username": "admin", "password": "your-password" }
```

Response (`401` for wrong credentials or an inactive account):

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": { "username": "admin", "is_admin": true, "requires_password_change": false }
}
```

If `requires_password_change` is `true`, the frontend sends the user to `/change-password` first.

### POST /api/auth/change-password

```json
{ "current_password": "old", "new_password": "at-least-8-chars" }
```

Returns `{"access_token": "...", "token_type": "bearer"}` with a fresh token. `400` if the current password is wrong or the new one is shorter than 8 characters.

### GET /api/auth/me

Returns `{ "username", "is_admin", "requires_password_change" }`.

There is no registration endpoint. Admins create users:

### POST /api/admin/users

```json
{ "username": "newuser", "password": "TemporaryPassword123", "email": null, "is_admin": false }
```

`201` with the user (no password hash). The new user must change the password on first login. `409` for a duplicate username or email, `400` for a password under 8 characters. `POST /api/admin/users/{username}/reset-password` takes `{"new_password": "..."}`.

---

## Search

### POST /api/search

The main endpoint. It streams results as Server-Sent Events. **Auth:** optional. Responses for a complete, error-free run are cached for 30 minutes and replayed instantly.

**Request body** (`TravelSearchRequest`, `backend/app/schemas/request.py`):

```json
{
  "origin": "London",
  "destination": "Tokyo",
  "departure_date": "2026-06-01",
  "return_date": "2026-06-14",
  "nationality": "British",
  "interests": ["food", "history", "nature"],
  "budget_usd": 4000,
  "num_travelers": 2,
  "adults": 2, "children": 0, "seniors": 0, "infants": 0,
  "accessibility_needs": [],
  "residence_permits": [],
  "existing_visas": [],
  "destinations": null,
  "destination_nights": null,
  "pace": "balanced",
  "serendipity": 0.5
}
```

`destinations` and `destination_nights` describe a multi-city trip (see [Multi-City Trips](Multi-City-Trips.md)). `taste_context` is set by the server from the user's Taste Graph; a client value is ignored. `origin` and `destination` may be city names, typeahead labels or airport codes; the validator resolves them to airport codes for live flight search (see [Place and Airport Data](Place-and-Airport-Data.md)).

**Response:** `Content-Type: text/event-stream`. Each event is `data: {JSON}\n\n`, and `: keepalive` comments are sent while agents run.

| Event | Phase | `source` | Notes |
|---|---|---|---|
| `visa`, `sim`, `tips`, `getting_around`, `forex` | 0, then 1 | `static`, then `ai` | Static-backed; an AI error is not sent, so the static data stays |
| `confidence` | 0 | `static` | Travel Ease grade: total out of 100 and green/amber/red, from visa ease, safety, English friendliness, cost vs budget and tourist infrastructure |
| `emergency_card` | 0, then 1 | `static`, then `ai` | Static-backed |
| `agent_status` | — | — | `{agent, status: "searching" \| "done"}` for the 15 agents at start, and for `stress_test` |
| `flights`, `weather`, `hotels`, `activities`, `places_to_see`, `walking_tours`, `events` | 1 | `ai` | `hotels`, `activities` and `places_to_see` are sent twice: before and after link enrichment |
| `packing_list` | deferred | `ai` (`static` for the template fallback) | Starts when activities and weather are in |
| `pricing_advisor` | deferred | `ai` | Starts when flights have at least 3 results; skipped on error or after 120 s |
| `itinerary` | 2 | none | Starts when activities and hotels are in; template fallback after 60 s |
| `stress_test` | after the itinerary | `ai` | 90 s timeout; on error an error section is sent |
| `done` | — | — | Always last |

Every non-error section carries `data.verification` (see [Agent System](Agent-System.md#source-verification)). An agent that fails sends `{"error": "..."}` as its data (except the static-backed ones), so the UI can show "not available" instead of waiting.

### POST /api/search/sync

Same request and agents, run sequentially; returns a single JSON object. For testing only.

### POST /api/discover

*Surprise me.* **Auth:** optional. Returns 5 destination suggestions.

```json
{
  "origin": "JFK",
  "nationality": "American",
  "departure_date": "2026-08-01",
  "return_date": "2026-08-08",
  "budget_usd": 3000,
  "interests": ["food", "history"],
  "adults": 1, "children": 0, "seniors": 0, "infants": 0
}
```

`return_date` and `budget_usd` are optional. Response:

```json
{
  "destinations": [
    {
      "city": "Lisbon",
      "country": "Portugal",
      "estimated_cost_usd_low": 1400,
      "estimated_cost_usd_high": 2200,
      "visa_type": "visa-free",
      "visa_verified": true,
      "weather_emoji": "☀️",
      "weather_description": "Warm and sunny, 22–26°C in August",
      "flight_duration_hours": 7.5,
      "flight_duration_label": "~7h 30m from New York",
      "match_reasons": ["Exceptional food scene", "Rich Age of Discovery history"],
      "highlights": ["Alfama district", "Sintra", "Belém Tower"]
    }
  ]
}
```

`visa_verified: true` means the visa type came from the static visa table; otherwise it is the model's guess and the UI shows a warning badge. Errors: `422` invalid request, `504` after 30 s, `500` agent failure. Results are cached for 30 minutes.

### POST /api/compare/destination

Lightweight summary of one destination, used by the Search page's Compare mode (one call per destination, in parallel). Runs flights, hotels (no URL enrichment), weather and visa concurrently with per-piece timeouts (flights and hotels 45 s, weather and visa 30 s). The visa piece uses the static visa table when it has an entry.

**Auth:** user. **Bucket:** compare.

**Request body:** a `TravelSearchRequest` for a single destination. `destinations` must be null or have at most one entry; multi-city requests return `422` ("Compare works with single destinations").

**Response (200)** — example for 2 adults, 7 nights, `budget_usd: 3000`:
```json
{
  "destination": "Lisbon, Portugal",
  "label": "Lisbon",
  "flight": {"price_usd": 620, "stops": 0, "duration_minutes": 895, "airline": "TAP Air Portugal", "source": "google_flights"},
  "hotel": {"typical_nightly_usd": 110, "cheapest_good_nightly_usd": 70, "count": 5},
  "weather": {"avg_high_c": 24.4, "avg_low_c": 15.7, "poor_days": 1, "total_days": 7, "source": "open-meteo"},
  "visa": {"visa_type": "visa-free", "max_stay_days": 90, "fee_usd": 0, "processing_time": "Not required", "verified": true},
  "ease": {"total": 80, "grade": "green", "safety": 18, "english": 15, "infrastructure": 17, "visa_ease": 10},
  "daily_cost_usd": 100,
  "estimate": {
    "total_usd": 1320,
    "flight_usd": 620,
    "stay_usd": 385,
    "daily_usd": 700,
    "included_in_daily": true,
    "nights": 7,
    "partial": false,
    "budget_status": "under"
  },
  "missing": []
}
```
Any piece that failed or timed out is `null` and its name is listed in `missing`; `ease`/`daily_cost_usd` are `null` for destinations outside the static tables. `flight.source` of `estimate` marks a non-live fare; `visa.verified` is true only for static-table data. `ease.grade` is `green` (≥ 71), `amber` (41–70) or `red` (≤ 40).

**Estimate (per traveller):** `flight_usd` is the cheapest fare (`flight.price_usd`, round trip, per person). `daily_usd` = `daily_cost_usd` × days (days = nights, min 1; nights default to 7 without a `return_date`). `daily_cost_usd` is an all-in daily budget that already includes lodging, so when it is known `total_usd = flight_usd + daily_usd` and `stay_usd` is shown for reference only (`included_in_daily: true`) — above, 620 + 700 = 1320. When the daily figure is unknown, `total_usd = flight_usd + stay_usd` and `included_in_daily` is `false`. `stay_usd` = typical nightly × nights × rooms ÷ travellers, with rooms = ⌈(adults + seniors) ÷ 2⌉ (falling back to ⌈num_travelers ÷ 2⌉) — above, 110 × 7 × 1 ÷ 2 = 385. `partial` is `true` when the flight or the daily figure is unknown; the total then sums only the known parts. `budget_status` compares `total_usd × num_travelers` with `budget_usd` (the party's budget): `over`, `under` (only for a complete estimate), or `null` with no budget or when a partial total is still within it.

**Errors:** `422` for multi-city or invalid requests; `502` when every piece failed.

**Caching:** only complete results (empty `missing`) are cached in the shared TTL cache, keyed on the full request; partial results and `502`s are never cached.

---

## Chat

### POST /api/chat

**Auth:** user. Streams SSE.

```json
{
  "messages": [{ "role": "user", "content": "Plan a 5-day trip to Bangkok for two people" }],
  "selections": {},
  "search_results": {},
  "session_context": {}
}
```

Event types: `delta` (text), `done`, `error`, `suggestions`, `session_context_update`, `plan_action`, `planning_start`, `trip_map`, `itinerary_generating`, `comprehensive_itinerary`, `planning_done`, `agent_status` and `section_result`. A planning request streams `planning_start → trip_map → itinerary_generating → comprehensive_itinerary → planning_done`; `section_result` appears only in the specialist fallback and refinement paths. An exception still ends the stream with a fallback `delta`, `error` and `done`. See [Chat Assistant](Chat-Assistant.md).

---

## Plans and sharing

### GET /api/plans, POST /api/plans

List the caller's plans, or save one. Saving records Taste Graph signals.

```json
{
  "name": "The Rainy Tokyo Adventure",
  "search_data": { "origin": "London", "destination": "Tokyo", "departure_date": "2026-04-01" },
  "selections": {
    "flight": {},
    "hotel": {},
    "activities": [],
    "itinerary_slots": [],
    "itinerary": {},
    "itinerary_layout": {},
    "itinerary_edits": {},
    "itinerary_notes": {}
  }
}
```

### GET, PUT, DELETE /api/plans/{id}

Get, update (name and/or selections) or delete one of the caller's plans; `404` for another user's plan.

### POST /api/plans/{id}/share and GET /api/share/{token}

`POST` returns `{"share_token": "..."}` (the existing token if there is one). `GET /api/share/{token}` needs no auth and returns the plan's name, timestamps, selections and only these search fields: origin, destination, destinations, dates, interests, traveller counts and pace. `DELETE /api/plans/{id}/share` revokes the token. See [Sharing and Plans](Sharing-and-Plans.md).

---

## Preferences, recent searches, taste profile

### GET, PUT /api/preferences

The caller's preferences: `budget_category`, `nationality`, `current_residence`, `residence_permits`, `existing_visas`, `interests`, `num_travelers`, `adults`, `children`, `seniors`, `infants`, `accessibility_needs`. They pre-fill the Search form, and the Search form writes back to them.

### GET, POST /api/recent-searches; DELETE /api/recent-searches/{id}

`GET` returns the caller's last 8 searches, newest first, each `{ "id", "search", "last_used_at" }`, where `search` is the Search form as submitted (route with multi-city `stops` and optional `nights`, dates, nationality, permits, visas, interests, budget, traveller mix, accessibility needs, serendipity). `POST` records one: an identical search (interests in any order) is moved back to the top instead of duplicated, and only the newest 8 are kept. `DELETE` returns `204`, or `404` if the entry does not exist or belongs to someone else.

### GET, DELETE /api/taste-profile

`GET` returns the learned signals (flight style, hotel tier, activity categories, budget band) and the summary injected into agent prompts. `DELETE` resets them.

---

## Feedback and analytics

### POST /api/feedback

```json
{ "page": "results", "rating": 4, "category": "praise", "message": "Great activity suggestions!" }
```

`rating` is 1–5; `category` is `bug`, `feature_request`, `general` or `praise`; `message` (optional) is at most 500 characters; `metadata` is an optional object. Returns `201`. Admins read feedback with `GET /api/admin/feedback?page=&category=&min_rating=`.

### POST /api/analytics/events

Up to 50 batched UI events per call, written to the log as JSON. Returns `204`.

---

## Single-agent and helper endpoints

Each takes the `TravelSearchRequest` body of `/api/search` unless noted. **Auth:** optional (except the fare calendar). Bucket: light_ai.

| Endpoint | Returns |
|---|---|
| `POST /api/flights` | Flight options; multi-city returns ordered `legs`. Live single-city results may carry `price_insights` |
| `POST /api/flights/filtered` | Flights with `max_stops`, `max_price_usd`, `departure_time_earliest/latest`, `arrival_time_earliest/latest`; enriched and verification-labelled |
| `POST /api/hotels` | Hotels across budget tiers |
| `POST /api/hotels/filtered` | Hotels with `num_beds`, `max_price_per_night_usd`, `wifi_quality`, `max_distance_from_center_km`, `private_washroom` |
| `POST /api/activities` | Interest-ranked activities |
| `POST /api/activities/filtered` | Activities with `filter_interests`, `max_price_usd`, `available_from/to`, `min_rating` |
| `POST /api/visa`, `/api/sim`, `/api/tips`, `/api/getting-around`, `/api/forex` | The corresponding specialist result |
| `POST /api/itinerary` | Day-by-day itinerary |
| `POST /api/events` | What's On during the trip |
| `POST /api/walking-tours` | Crawled free walking tours (see below) |
| `POST /api/layover` | Layover plan. Own body: `city`, `duration_hours` (> 0, ≤ 48), `nationality`, optional `airport`, `arrival_time` (`HH:MM`) and `interests` |
| `POST /api/stress-test` | Audit of an itinerary. Body: the search request plus `itinerary` (required) and optional `flights`, `visa` and `weather` |

### Flight `price_insights`

When flights come from Google Flights (SerpAPI) on a single-city trip, the result may include Google's own price verdict, taken from the outbound search response (no extra calls). Fields are kept only when well-formed; the object is omitted when there is no usable `price_level` or `lowest_price`. Model-generated flight results never carry it (stripped like `live_fare`), and it does not change the section's verification label.

```json
"price_insights": {
  "lowest_price": 512,
  "price_level": "low",
  "typical_price_range": [600, 820],
  "price_history": [[1727740800, 650], [1727827200, 512]]
}
```

`price_level` is `low`, `typical` or `high`.

### POST /api/flights/fare-calendar

Auth required (`401` without a valid token); `light_ai` rate-limit bucket. Body: the same `TravelSearchRequest` as `/api/search`.

For each departure date from 3 days before to 3 days after the requested one, it makes one Google Flights outbound search (SerpAPI) with the return date shifted by the same amount, so the trip length stays the same, and takes the cheapest `price` (for a round trip that is already the round-trip total). There are no return-leg calls, so this is at most 7 calls, run 4 at a time. Overlapping requests for the same dates (a second tab, a double-mounted component) share the lookups already in flight, so each date costs one call. Dates before tomorrow are skipped. An unfiltered main flight search stores its own cheapest outbound-stage price as the calendar entry for its dates. The requested date shows the lower of that price and the cheapest flight card of the cached main search, so it matches the cards (the main round-trip search always return-prices the lowest-priced outbound, wherever Google lists it, plus the earliest and latest departures); Google's `price_insights.lowest_price` is used only when neither is available. Each date's price is cached for 30 minutes (`serp-cal:{origin}:{dest}:{dep}:{ret}:{travelers}`). A date that fails for any reason (HTTP error, timeout, unreadable response) or has no flights comes back as `null`; the calendar as a whole never fails, and failures are not cached.

```json
{
  "dates": [
    {"departure_date": "2026-10-31", "return_date": "2026-11-07", "cheapest_usd": 610.0, "is_selected": false},
    {"departure_date": "2026-11-03", "return_date": "2026-11-10", "cheapest_usd": 565.0, "is_selected": true},
    {"departure_date": "2026-11-04", "return_date": "2026-11-11", "cheapest_usd": null, "is_selected": false}
  ],
  "currency": "USD",
  "source": "google_flights"
}
```

Errors (string `detail`):

| Status | When |
|---|---|
| `401` | Not signed in |
| `422` | Multi-city request (`"Fare calendar is only available for single-destination trips."`) or invalid body |
| `429` | Rate limit (see above) |
| `503` | `{"detail": "Fare calendar needs live flight data, which isn't configured."}` — `SERPAPI_KEY` is not set |

### POST /api/walking-tours

Free and pay-what-you-wish walking tours at the destination (every stop on multi-city trips). Tours are crawled from the providers' public city pages; the LLM only chooses and explains them by id, so every `url` is a real provider tour page. Same request body as `/api/search`.

```json
{
  "origin": "NYC",
  "destination": "Lisbon, Portugal",
  "departure_date": "2026-04-01",
  "return_date": "2026-04-08",
  "interests": ["history", "food"],
  "num_travelers": 2
}
```

Response:

```json
{
  "results": [
    {
      "id": "t3",
      "name": "Lisbon Old Town Free Walking Tour",
      "provider": "GuruWalk",
      "provider_key": "guruwalk",
      "url": "https://www.guruwalk.com/walks/...",
      "image_url": "https://...",
      "description": "Alfama, the cathedral and the viewpoints, with a local guide.",
      "rating": 4.9,
      "review_count": 1280,
      "duration": "2h 30m",
      "price_note": "Free (tip your guide)",
      "city": "Lisbon",
      "reason": "Covers the old-town history you asked for.",
      "top_pick": true
    }
  ],
  "sources": [
    {
      "provider": "GuruWalk",
      "provider_key": "guruwalk",
      "city": "Lisbon",
      "url": "https://www.guruwalk.com/lisbon",
      "count": 6,
      "status": "ok"
    }
  ]
}
```

`sources` has one entry per provider and city; `status` is `ok`, `none` (page found, no free tours) or `error`. Each city is topped up to at least `min(4, available)` tours. The endpoint returns `{"error": ...}` only when every provider fails.

---

## Reference data

### GET /api/airports/search?q=&limit=

Airport and place typeahead (`limit` 1–50, default 10). Matches airport codes, cities, names and countries, plus GeoNames places and curated hints by folded name prefix ("kyoto" → ITM, KIX; "milan" → MXP, LIN, BGY). Rows: `iata_code, name, city, country, country_code`. Ordering and rules: [Place and Airport Data](Place-and-Airport-Data.md#autocomplete).

### GET /api/nationalities/search?q=&limit=

Nationality typeahead over 202 seeded rows.

---

## Health

### GET /health

`{"status": "ok", "service": "travel-planner-backend", "serpapi_configured": true|false}`. No auth. The Results page reads `serpapi_configured` once per page load to decide whether to offer the fare calendar; Docker Compose uses this endpoint as the backend healthcheck.

### GET /health/agents

A deep check: one tiny Haiku call, cached for 5 minutes. Reports `llm` status, `serpapi_configured` and `backup_configured`.
