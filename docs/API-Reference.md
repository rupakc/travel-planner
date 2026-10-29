# API Reference

The Travel Planner backend is a FastAPI application. All endpoints are under `/api/`. Interactive documentation (Swagger UI) is available at `/docs` on any running instance.

**Live API:** `https://travel-planner-backend-2hrxgxqboa-ew.a.run.app`
**Local API:** `http://localhost:8001`

**Authentication:** Most endpoints require a JWT Bearer token from the login response:
```
Authorization: Bearer <token>
```

**Rate limits:** endpoints that call the AI agents are limited per caller — the signed-in user, or the client IP for anonymous requests — over a rolling 10-minute window. Every accepted request counts, including cached responses and requests later rejected as invalid (`422`) or unauthenticated (`401`); only requests answered with `429` do not.

| Bucket | Endpoints | Default limit |
|---|---|---|
| search | `POST /api/search`, `POST /api/search/sync` | 10 |
| chat | `POST /api/chat` | 30 |
| compare | `POST /api/compare/destination` | 30 |
| discover | `POST /api/discover` | 10 |
| light_ai | `POST /api/flights`, `/hotels`, `/activities` (and their `/filtered` variants), `/flights/fare-calendar`, `/visa`, `/sim`, `/tips`, `/getting-around`, `/forex`, `/itinerary`, `/events`, `/walking-tours`, `/layover`, `/stress-test` | 60 |

Each bucket is counted separately. Over the limit the API answers `429 Too Many Requests` with a `Retry-After` header (seconds) and:

```json
{"detail": "Too many requests — please wait 42 seconds and try again."}
```

Limits are configurable (see [Configuration](Configuration.md#rate-limit-variables)). The counter is in-process, so each backend instance counts on its own.

---

## Auth endpoints

### `POST /api/auth/login`

Authenticate and receive a JWT access token.

**Auth required:** No

**Request body:**
```json
{
  "username": "admin",
  "password": "your-password"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "requires_password_change": false,
  "user": { "id": 1, "username": "admin", "role": "admin" }
}
```

If `requires_password_change` is `true`, the frontend redirects to `/change-password` before allowing further navigation.

---

### `POST /api/auth/change-password`

**Auth required:** Yes

```json
{ "current_password": "old", "new_password": "new" }
```

**Response:** `200 OK` — `{"message": "Password changed successfully"}`

---

### `GET /api/auth/me`

Returns the currently authenticated user's profile.

**Auth required:** Yes

---

## Search (primary trip planning)

### `POST /api/search` — SSE streaming

The core endpoint. Submits a trip search and streams results in real time via Server-Sent Events.

**Auth required:** Yes

**Request body:**
```json
{
  "origin": "London",
  "destination": "Tokyo",
  "departure_date": "2026-06-01",
  "return_date": "2026-06-14",
  "nationality": "British",
  "interests": ["food", "history", "nature"],
  "budget_usd": 4000,
  "num_travelers": 1,
  "residence_permits": [],
  "existing_visas": []
}
```

**Response:** `Content-Type: text/event-stream`

Each event:
```
data: {"type": "<event_type>", "data": <object>, "source": "static"|"ai"}\n\n
```

The final event:
```
data: {"type": "done"}\n\n
```

**Event types and phases:**

| Event type | Phase | Source | Description |
|---|---|---|---|
| `confidence` | 0 | static | Travel confidence score (safety / visa / budget / infrastructure) |
| `visa` | 0 then 1 | static → ai | Visa requirements |
| `sim` | 0 then 1 | static → ai | SIM card options |
| `tips` | 0 then 1 | static → ai | Travel tips |
| `getting_around` | 0 then 1 | static → ai | Local transport |
| `emergency_card` | 0 then 1 | static → ai | Emergency numbers, embassy, phrases, local laws |
| `flights` | 1 | ai | Flights guidance |
| `weather` | 1 | ai | Forecast for travel dates |
| `hotels` | 1 | ai | Hotels by neighbourhood and budget tier |
| `activities` | 1 | ai | Activities, relevance-sorted |
| `places_to_see` | 1 | ai | Must-visit landmarks |
| `walking_tours` | 1 | ai | Free walking tours crawled from provider city pages |
| `events` | 1 | ai | What's On: festivals, concerts, exhibitions |
| `forex` | 1 | ai | Currency and payment tips |
| `pricing_advisor` | 1 (deferred) | ai | Flight price trend and booking recommendation |
| `packing_list` | 1 (deferred) | ai | Personalised packing checklist |
| `itinerary` | 2 | ai | Day-by-day schedule |

**Static-backed events** (visa, sim, tips, getting_around, emergency_card): Phase 0 sends static data immediately. Phase 1 replaces it with AI-enriched data. If Phase 1 fails, the static data is retained — no error is shown for these sections.

**Deferred events**: `pricing_advisor` triggers when ≥ 3 flight prices are available; `packing_list` triggers when activities are ready and weather is done.

On agent failure, the event is still emitted with `"error": true` in the data so the frontend can show "not available" rather than hang.

---

### `POST /api/search/sync`

Same as `/api/search` but waits for all agents and returns a single JSON response. For testing only — too slow for production use.

---

## Destination Discovery

### `POST /api/discover`

The "Surprise Me" endpoint. Given a traveller profile, returns 5 curated destination suggestions without needing a specific destination input.

**Auth required:** Yes

**Request body:**
```json
{
  "origin": "JFK",
  "nationality": "American",
  "departure_date": "2026-08-01",
  "return_date": "2026-08-08",
  "budget_usd": 3000,
  "interests": ["food", "history"],
  "adults": 1,
  "children": 0,
  "seniors": 0,
  "infants": 0
}
```

`return_date` is optional (for one-way or open-ended trips).

**Response:**
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
      "weather_description": "Warm and sunny, 22–26°C in August — typical for the season",
      "flight_duration_hours": 7.5,
      "flight_duration_label": "~7h 30m from New York",
      "match_reasons": ["Exceptional food scene", "Rich Age of Discovery history"],
      "highlights": ["Alfama district", "Sintra", "Belém Tower"]
    }
  ]
}
```

`visa_verified: true` means the visa type was confirmed from the authoritative `_VISA_TABLE` lookup. `visa_verified: false` means the AI's guess was not verifiable — the frontend shows an amber "Verify" badge.

**Errors:**
- `422` — missing required fields
- `504` — agent timed out (> 30 seconds); retry
- `500` — agent failed; retry

Results are cached in memory for 30 minutes per unique request.

---

### `POST /api/compare/destination`

Lightweight summary of one destination, used by the Search page's Compare mode (one call per destination, in parallel). Runs flights, hotels (no URL enrichment), weather and visa concurrently with per-piece timeouts.

**Auth required:** Yes

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

## Chat

### `POST /api/chat` — SSE streaming

Conversational trip planning. The agent maintains session context and can trigger the full search pipeline when the message is trip-planning related.

**Auth required:** Yes

**Request body:**
```json
{
  "messages": [
    { "role": "user", "content": "Plan a 5-day trip to Bangkok for two people" }
  ],
  "selections": {},
  "search_results": {},
  "session_context": {}
}
```

**Response:** `Content-Type: text/event-stream`

Events include plain text chunks, structured planning sections (same types as `/api/search`), and a final `done` event.

---

## Plans

### `GET /api/plans`

List all saved plans for the current user.

**Auth required:** Yes

---

### `POST /api/plans`

Save a new plan.

**Auth required:** Yes

**Request body:**
```json
{
  "name": "The Rainy Tokyo Adventure",
  "search_data": { "destination": "Tokyo", "departure_date": "2026-04-01", ... },
  "selections": {
    "flight": { ... },
    "hotel": { ... },
    "activities": [ ... ],
    "packing_list": { ... }
  }
}
```

---

### `GET /api/plans/{id}` / `PUT /api/plans/{id}` / `DELETE /api/plans/{id}`

Retrieve, update, or delete a specific plan. Must be the plan's owner.

---

## Preferences

### `GET /api/preferences` / `PUT /api/preferences`

Get or update the current user's saved preferences (nationality, interests, budget, residence permits, existing visas). These pre-fill the search form on next visit.

**Auth required:** Yes

---

## Recent searches

### `GET /api/recent-searches`

The current user's last 8 submitted searches, most recent first. Each entry is `{ "id", "search", "last_used_at" }`, where `search` is the Search form as submitted (origin, destination, dates, multi-city `stops` with optional `nights`, nationality, permits, visas, interests, budget, traveler mix, accessibility needs, serendipity).

### `POST /api/recent-searches`

Records a search; the Search page calls it on every submit. An identical search (interests in any order) is merged and moved back to the top instead of duplicated, and only the newest 8 entries are kept. Returns the saved entry.

### `DELETE /api/recent-searches/{id}`

Removes one of the caller's entries. `204 No Content`, or `404` if the entry doesn't exist or belongs to another user.

**Auth required:** Yes (all three)

---

## Feedback

### `POST /api/feedback`

Submit a feedback rating from the floating widget.

**Auth required:** Yes

**Request body:**
```json
{
  "page": "results",
  "rating": 4,
  "category": "content",
  "message": "Great activity suggestions!"
}
```

---

### `GET /api/admin/feedback`

View all submitted feedback. Admin only.

**Auth required:** Yes (admin)

---

## Admin

### `GET /api/admin/users`

List all user accounts (without password hashes).

**Auth required:** Yes (admin)

---

### `POST /api/admin/users`

Create a new user. The user is flagged as requiring a password change on first login.

**Auth required:** Yes (admin)

```json
{ "username": "newuser", "password": "TemporaryPassword123", "role": "user" }
```

**Roles:** `"user"`, `"admin"`

---

### `PATCH /api/admin/users/{user_id}` / `DELETE /api/admin/users/{user_id}`

Deactivate/reactivate or delete a user account. Admin only.

---

## Section Endpoints

Each results section is also exposed as a standalone endpoint (same request body as `/api/search`, plus per-domain filters):

| Endpoint | Returns |
|---|---|
| `POST /api/flights` | Flight options (supports stop/price/time filters; multi-city returns ordered `legs`). With live fares (SerpAPI) a single-city result may also carry `price_insights` |
| `POST /api/flights/fare-calendar` | Cheapest live fare for departure dates ±3 days (see below) |
| `POST /api/hotels` | Hotels across four budget tiers (bed/price/wifi/distance filters) |
| `POST /api/activities` | Interest-ranked activities (category/price/date/rating filters) |
| `POST /api/visa` | Entry requirements for the traveler's nationality |
| `POST /api/sim` | SIM/eSIM plans |
| `POST /api/tips` | Safety, culture & practical tips |
| `POST /api/getting-around` | Local + inter-city transportation options |
| `POST /api/forex` | Currency & money guidance |
| `POST /api/itinerary` | Day-by-day itinerary |
| `POST /api/events` | What's On — festivals, concerts, exhibitions during the trip |
| `POST /api/layover` | Layover excursion plan for long connections |
| `POST /api/stress-test` | Adversarial itinerary health check (pacing, timing, visa deadlines, weather, budget) |
| `POST /api/walking-tours` | Free walking tours crawled from GuruWalk, FreeTour.com, FreeWalkingTour.com and SANDEMANs NewEurope |

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

### Airport codes for live flights

Live flight search (`/api/flights`, the search stream and the fare calendar) needs airport codes. The request validator sets them from `origin` / `destination` with `lookup_city_iata` (`backend/app/db/database.py`), local DB only, never a web lookup. Up to 3 scheduled airports are sent comma-joined, best first; the booking link uses the first. In order:

1. **An ALL-CAPS three-letter code** is used as typed ("LHR", "NYC", "GOA"; the autocomplete submits picked airports this way). Any other casing tries places first and falls back to the code: "Hue" → `HUI,DAD`, "Goa" → `GOI,GOX`, "lhr" → `LHR`. Country names and aliases beat codes in any casing: "USA", "UAE", "uk" → the country's gateway airports.
2. **A UI label whose code prefix is a scheduled airport** ("LGW — London, United Kingdom") uses that code alone; an unknown prefix stays part of the text.
3. **A curated island or destination** (`ISLAND_AIRPORTS` / `DESTINATION_AIRPORTS` in `core/places.py`): "Sicily" → `CTA,PMO,TPS`, "Bali" → `DPS`, "Machu Picchu" → `CUZ`, "Kyoto" → `KIX,ITM`, unless a stated country names another country.
4. **The curated tier**: airports from the curated list (`db/seed_airports.py`) whose served city is the typed city, in curated order ("London" → `LHR,LGW,STN`). The city is also tried accent-folded (`fold_place`: "Zürich", "Kraków"), with its St / St. / Saint spellings and through `CITY_ALIASES` ("Washington", "Saigon", "Bombay"). A last comma segment that names a country, ISO code or alias ("UK", "England", "Holland"; one shared map, `COUNTRY_ALIASES`) keeps that country; a region code or name (US states, Canadian provinces, Australian and Brazilian states) keeps that region, in any country that code can mean ("Perth, WA": Washington or Western Australia; "Toronto, CA": Canada, "San Jose, CA": California).
5. **Place resolution** (`resolve_place`, `db/places_db.py`) over every GeoNames place with ≥ 1,000 people, which links each place to its nearby scheduled airports (see `backend/app/db/data/README.md`). Candidates are the places whose own name (or ASCII spelling) is the typed city, plus places with that alternate name at a score penalty (0.0135; "Cologne" → Köln, "Bruges", "Mecca"); places with population 0 never count. A stated segment filters them: a country, a region code, or any first-level division name in any country ("Munich, Bavaria", "London, Ontario" → `YXU`, "Sydney, Nova Scotia" → `YQY`, "Zermatt, Valais"). The winner must have 3× the score of the next candidate (score = population × notability), else the text is ambiguous: "Portland" → `PDX`, "Birmingham" → `BHX…`, but "Springfield" and "San Jose" → nothing. A country typed alone resolves to its top place ("Japan" → Tokyo); a division typed alone to its dominant place ("Bavaria" → Munich).
   - With a curated answer, the place's other airports in the same country follow it ("New York" → `JFK,LGA,EWR`, "Washington" → `IAD,DCA,BWI`); a bigger own-name namesake abroad makes the name ambiguous ("Valencia": Spain or the larger Valencia, Venezuela → nothing; "Valencia, Spain" → `VLC`).
   - Without one, the place's airports, never padded with foreign ones: an airport abroad only when it is the place's own (named after it or within 25 km: "Basel" → `BSL`, in France) or when the place has no domestic airport ("Lviv" → `RZE`). "Victoria" → `YYJ`, "Detroit" → `DTW`, "Geneva" → `GVA`. Among namesakes, one with an airport within 100 km beats one that only has a distant fallback ("Bol" → Bol, Croatia, `BWK`). Examples: "Portland, ME" → `PWM`, "Columbus, GA" → `CSG`, "Zermatt", "Ubud" → `DPS`, "Paris, Texas" → `TYR,DAL` (never CDG).
6. **Last**, any airport whose display city is the typed city.

Airports without scheduled service are never returned. Text that names no place, contradicts its stated country ("Berlin, Japan") or is ambiguous resolves to nothing, and flights fall back to AI estimates. Measured on the golden set (`backend/tests/data/golden_places.csv`, 435 rows): `lookup_city_iata` p50 0.54 ms, p95 0.76 ms per call, so the handlers keep calling it synchronously.

### `POST /api/flights/fare-calendar`

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

### `POST /api/walking-tours`

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

## Taste Graph

### `GET /api/taste-profile`

Returns the authenticated user's learned taste profile — signals mined from saved-plan selections (flight style, hotel tier, activity categories, budget band) plus the natural-language summary injected into agent prompts. `DELETE /api/taste-profile` resets it.

## Analytics

### `POST /api/analytics/events`

Ingests batched client-side usage events (up to 50 per call). Returns `204`.

## Reference Data

| Endpoint | Returns |
|---|---|
| `GET /api/airports/search?q=&limit=` | Airport typeahead: codes, airport cities and names, plus GeoNames places by folded name prefix and curated islands / destinations through their airports ("kyoto" → KIX, ITM; "zurich" → ZRH). Order: exact code, code prefix, exact city / place name, prefix, other; within a class the more notable place first ("lon": London's airports before Long Beach). Unscheduled airports only for their exact code. Rows: `iata_code, name, city, country, country_code`. |
| `GET /api/nationalities?q=` | Nationality typeahead search |

## Health

### `GET /health`

Liveness check. Returns `{"status": "ok", "service": "travel-planner-backend", "serpapi_configured": true|false}`; the Results page reads `serpapi_configured` once per page load to decide whether to offer the fare calendar. Used by Cloud Run health probes and Cloud Monitoring uptime checks. No auth required.
