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
| light_ai | `POST /api/flights`, `/hotels`, `/activities` and their `/filtered` variants, `/flights/fare-calendar`, `/visa`, `/sim`, `/tips`, `/getting-around`, `/forex`, `/itinerary`, `/events`, `/walking-tours`, `/layover`, `/stress-test`, `/fare-watches` (create), `/fare-watches/{id}/check` | 60 |

Each bucket is counted separately, with one exception: a chat turn that starts a full trip plan (including a refinement that rebuilds the itinerary) also takes one token from the caller's **search** bucket, so searches and chat-planned trips share one budget; over it, the already-open chat stream answers with a friendly `delta` saying roughly how many minutes to wait, then `done` (no `429`, no `error`). Over the limit the API answers `429 Too Many Requests` with a `Retry-After` header (seconds) and:

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
| PUT | `/api/auth/email` | user | Set or clear the account email (for fare alert emails) |
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
| GET, POST | `/api/fare-watches` | user | List own fare watches; watch a trip's fare (takes the baseline) |
| POST | `/api/fare-watches/match` | user | The caller's watch for a trip, or `null` (no live lookup) |
| GET, PATCH, DELETE | `/api/fare-watches/{id}` | user | Get, edit (pause/resume, mode, target, ±3 days, email), delete own watch |
| POST | `/api/fare-watches/{id}/check` | user | "Check now": one live check |
| GET | `/api/fare-watches/unsubscribe?token=` | none | One-click "stop emails for this watch" link from alert emails (HTML page) |
| GET | `/api/notifications` | user | Own notifications, newest first (`unread_only`, `limit` 1–100, `offset`) |
| GET | `/api/notifications/unread-count` | user | `{"count": n}` |
| POST | `/api/notifications/read` | user | Mark `ids` (or `all`) read |
| GET | `/health` | none | Liveness and capability flags |
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
  "user": { "username": "admin", "is_admin": true, "requires_password_change": false, "email": null }
}
```

If `requires_password_change` is `true`, the frontend sends the user to `/change-password` first.

### POST /api/auth/change-password

```json
{ "current_password": "old", "new_password": "at-least-8-chars" }
```

Returns `{"access_token": "...", "token_type": "bearer"}` with a fresh token. `400` if the current password is wrong or the new one is shorter than 8 characters.

### GET /api/auth/me

Returns `{ "username", "is_admin", "requires_password_change", "email" }`.

### PUT /api/auth/email

`{"email": "me@example.com"}` sets the account email (trimmed, lower-cased); `""` clears it and turns email off on all the user's fare watches. Returns `{"email": ...}`. `422` for an address that isn't `local@domain.tld`; `409` when another account uses it. Set from the Preferences page.

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

## Fare watches and notifications

A fare watch re-checks one single-destination trip's live Google Flights fare (SerpAPI) about twice a day and creates a notification when it is worth telling the traveller. All prices are the total for the trip's travellers, like the Flights section. Every route needs a signed-in user and only sees that user's watches and notifications (`404` otherwise), except the unsubscribe link. See [Trip Planning Features](Trip-Planning-Features.md#fare-watch-and-price-alerts) for the alert rules.

### POST /api/fare-watches

```json
{
  "origin": "Berlin", "destination": "Lisbon",
  "departure_date": "2026-12-10", "return_date": "2026-12-17", "num_travelers": 2,
  "alert_mode": "any_drop", "target_price": null, "flexible_days": 0, "email_enabled": false
}
```

Or `{"plan_id": 12, ...options}` to watch a saved plan's trip. Codes are resolved like a search (typed cities work). `alert_mode` is `any_drop` (default) or `below_target` (needs `target_price`); `flexible_days` is `0` or `3` (also watch departures ±3 days, same trip length); `email_enabled` needs an account email and SMTP (`422` otherwise).

Today's price is taken straight away as the **baseline** (never an alert) when the daily SerpAPI budget allows; otherwise the scheduler takes it. Returns the watch (below) with `already_watching: false`, or the existing watch for the same trip with `already_watching: true`. Errors: `503` without SerpAPI; `422` for multi-city (`"Fare watch works for single-destination trips for now"`), an unknown city, a departure today or earlier, or a return before departure; `409` at `FARE_WATCH_MAX_ACTIVE_PER_USER` active watches. Rate-limited (light_ai).

A watch:

```json
{
  "id": 1, "plan_id": null, "origin_code": "BER", "destination_code": "LIS,CAT",
  "origin_label": "Berlin", "destination_label": "Lisbon",
  "departure_date": "2026-12-10", "return_date": "2026-12-17", "num_travelers": 1, "cabin": "economy",
  "flexible_days": 0, "alert_mode": "any_drop", "target_price": null, "email_enabled": true,
  "status": "active",
  "baseline_price": 220.0, "last_price": 150.0, "lowest_price": 150.0, "lowest_price_date": "2026-12-10",
  "last_notified_price": 150.0, "last_notified_at": "2026-11-04T08:50:51+00:00",
  "google_price_level": "low", "google_typical_low": 140, "google_typical_high": 210,
  "check_count": 3, "failure_count": 0, "last_error": null,
  "last_checked_at": "...", "next_check_at": "...", "created_at": "...", "updated_at": "...",
  "history": [{"checked_at": "...", "price": 150.0, "cheapest_price": null,
               "cheapest_departure_date": null, "cheapest_return_date": null, "price_level": "low"}],
  "booking_url": "https://www.google.com/flights#flt=BER.LIS.2026-12-10*LIS.BER.2026-12-17;c:USD;e:1;sd:1;t:f"
}
```

`status` is `active`, `paused`, `expired` (departure day reached) or `error` (three failed checks in a row). `history` holds up to 120 checks, oldest first.

### GET /api/fare-watches, GET /api/fare-watches/{id}

The caller's watches (ordered by departure date) or one watch, each with its history.

### POST /api/fare-watches/match

Body: the trip fields of `POST /api/fare-watches`. Returns `{"watch": {...}}` or `{"watch": null}`; makes no live lookup. The "Watch fare" buttons use it to show "Watching · $412".

### PATCH /api/fare-watches/{id}

Any of `status` (`"paused"` or `"active"`), `alert_mode`, `target_price`, `flexible_days`, `email_enabled`. Resuming an `error` watch clears the failures and checks it on the next scheduler tick (the "Retry" action). `409` to resume an expired watch or past the active limit; `422` for `below_target` without a target or email without an address/SMTP. Scheduler fields can't be set.

### DELETE /api/fare-watches/{id}

Deletes the watch and its history. Returns `{"deleted": true}`.

### POST /api/fare-watches/{id}/check

"Check now": one live check (also on a paused watch), with the same alert rules as scheduled checks. Returns the watch plus `check_status` (`checked`, `failed`, `errored`, `postponed`, `skipped`) and `notification` (the alert this check created, or `null`). `429` with `Retry-After` (seconds to the next UTC day) when today's fare-watch budget is spent; `409` while the watch is being checked or after it expired; `503` without SerpAPI. Rate-limited (light_ai).

### GET /api/fare-watches/unsubscribe?token=

The signed link at the bottom of alert emails (also sent as `List-Unsubscribe`). Turns email off for that one watch, without login, and returns a small HTML page; in-app alerts continue. `400` for an invalid token.

### GET /api/notifications

`?unread_only=false&limit=20&offset=0` → `{"items": [...], "total": n, "unread": n}`, newest first. An item:

```json
{
  "id": 3, "kind": "fare_drop",
  "title": "Berlin → Lisbon dropped to $150 (−$70)",
  "body": "For 10–17 Dec · total for 1 traveller. The lowest we've seen since you started watching.",
  "data": {"watch_id": 1, "price": 150.0, "previous_price": 220.0, "delta": -70.0, "is_lowest": true,
           "departure_date": "2026-12-10", "return_date": "2026-12-17", "num_travelers": 1,
           "links": {"alerts": "/alerts?watch=1", "replan": "/alerts?watch=1&replan=1", "book": "https://www.google.com/flights#..."}},
  "created_at": "...", "read_at": null, "emailed_at": "..."
}
```

`kind` is `fare_drop`, `fare_target`, `fare_low_level`, `fare_cheaper_date` (data adds `selected_price`, `saving`, `cheapest_departure_date`, `cheapest_return_date`), `watch_expired` or `watch_error` (data `action: "retry"`).

### GET /api/notifications/unread-count

`{"count": 2}`. The header bell polls it every 60 s while the tab is visible.

### POST /api/notifications/read

`{"ids": [3, 4]}` or `{"all": true}` → `{"updated": n, "unread": n}`. Only the caller's notifications change. `422` without either.

---

## Reference data

### GET /api/airports/search?q=&limit=

Airport and place typeahead (`limit` 1–50, default 10). Matches airport codes, cities, names and countries, plus GeoNames places and curated hints by folded name prefix ("kyoto" → ITM, KIX; "milan" → MXP, LIN, BGY). Rows: `iata_code, name, city, country, country_code`. Ordering and rules: [Place and Airport Data](Place-and-Airport-Data.md#autocomplete).

### GET /api/nationalities/search?q=&limit=

Nationality typeahead over 202 seeded rows.

---

## Health

### GET /health

`{"status": "ok", "service": "travel-planner-backend", "serpapi_configured": true|false, "fare_watch_available": true|false, "email_alerts_available": true|false}`. No auth. The frontend reads it once per page load: `serpapi_configured` offers the fare calendar, `fare_watch_available` (SerpAPI set and `FARE_WATCH_ENABLED`) offers "Watch fare", `email_alerts_available` (`SMTP_HOST` set) offers "Also email me". Docker Compose uses this endpoint as the backend healthcheck.

### GET /health/agents

A deep check: one tiny Haiku call, cached for 5 minutes. Reports `llm` status, `serpapi_configured` and `backup_configured`.
