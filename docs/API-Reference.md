# API Reference

The Travel Planner backend is a FastAPI application. All endpoints are under `/api/`. Interactive documentation (Swagger UI) is available at `/docs` on any running instance.

**Live API:** `https://travel-planner-backend-2hrxgxqboa-ew.a.run.app`
**Local API:** `http://localhost:8001`

**Authentication:** Most endpoints require a JWT Bearer token from the login response:
```
Authorization: Bearer <token>
```

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
| `POST /api/flights` | Flight options (supports stop/price/time filters; multi-city returns ordered `legs`) |
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

## Taste Graph

### `GET /api/taste-profile`

Returns the authenticated user's learned taste profile — signals mined from saved-plan selections (flight style, hotel tier, activity categories, budget band) plus the natural-language summary injected into agent prompts. `DELETE /api/taste-profile` resets it.

## Analytics

### `POST /api/analytics/events`

Ingests batched client-side usage events (up to 50 per call). Returns `204`.

## Reference Data

| Endpoint | Returns |
|---|---|
| `GET /api/airports?q=` | Airport/city typeahead search |
| `GET /api/nationalities?q=` | Nationality typeahead search |

## Health

### `GET /health`

Liveness check. Returns `{"status": "ok"}`. Used by Cloud Run health probes and Cloud Monitoring uptime checks. No auth required.
