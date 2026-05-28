# API Reference

Interactive Swagger UI is available at `http://localhost:8001/docs` when the backend is running.

## Authentication

All endpoints except `POST /api/auth/login` and `GET /health` require a JWT bearer token:

```
Authorization: Bearer <token>
```

Obtain a token via `POST /api/auth/login`. Tokens are signed with `JWT_SECRET_KEY` and expire after 24 hours by default.

---

## Auth Endpoints

### `POST /api/auth/login`

No authentication required.

**Request**
```json
{ "username": "string", "password": "string" }
```

**Response 200**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "requires_password_change": false,
  "user": {
    "username": "alice",
    "is_admin": false,
    "requires_password_change": false
  }
}
```

`requires_password_change: true` is returned for the `admin` account on first login. The frontend redirects to a password-change screen when this flag is set.

**Errors**: `401` invalid credentials.

---

### `POST /api/auth/change-password`

Auth required.

**Request**
```json
{ "current_password": "OldPassword123!", "new_password": "NewPassword456!" }
```

**Response 200**
```json
{ "message": "Password changed successfully" }
```

**Errors**: `401` wrong current password, `422` validation failure.

---

### `GET /api/auth/me`

Auth required. Returns the current user's profile.

**Response 200**
```json
{
  "username": "alice",
  "is_admin": false,
  "requires_password_change": false
}
```

---

## Search Endpoint

### `POST /api/search`

Auth required. Returns a `text/event-stream` SSE response. Each event is:

```
data: {"section": "<name>", "data": {...}, "status": "done"|"loading", "source": "static"|"ai"}\n\n
```

**Request — `TravelSearchRequest`**
```json
{
  "origin": "MUC",
  "destination": "Tokyo, Japan",
  "departure_date": "2026-08-01",
  "return_date": "2026-08-14",
  "nationality": "German",
  "interests": ["food", "history", "photography"],
  "budget_usd": 4000,
  "num_travelers": 2,
  "residence_permits": [],
  "existing_visas": []
}
```

`destination` must include the country name. `origin` is an IATA airport code. `residence_permits` and `existing_visas` are optional arrays of country/visa strings used by the visa agent to determine visa requirements.

**SSE Event Sequence**

Events arrive out of order as agents complete. The frontend renders each section as it arrives.

| Section | Phase | Source | Notes |
|---|---|---|---|
| `confidence` | 0 / static | static | Instant search quality indicator |
| `visa` | 0 → 1 | static → ai | Static-backed (see below) |
| `sim` | 0 → 1 | static → ai | Static-backed |
| `tips` | 0 → 1 | static → ai | Static-backed |
| `getting_around` | 0 → 1 | static → ai | Static-backed |
| `emergency_card` | 0 → 1 | static → ai | Static-backed |
| `flights` | 1 | ai | Parallel agent |
| `weather` | 1 | ai | Parallel agent |
| `hotels` | 1 | ai | Parallel agent |
| `activities` | 1 | ai | Parallel agent |
| `places_to_see` | 1 | ai | Parallel agent (Serper + Claude synthesis) |
| `forex` | 1 | ai | Parallel agent |
| `pricing_advisor` | 1 / deferred | ai | Deferred — starts after core agents complete |
| `packing_list` | 1 / deferred | ai | Deferred — starts after core agents complete |
| `itinerary` | 2 | ai | Sequential — requires activities + hotels |

**Static-backed events**

Sections marked "static → ai" fire twice:

1. Phase 0 — `source: "static"`, `status: "loading"`. Data comes from curated lookup tables and appears within ~1 second.
2. Phase 1 — `source: "ai"`, `status: "done"`. AI-enhanced data replaces the static version.

If the Phase 1 AI call fails, the error is suppressed. The static data remains on screen and is never overwritten with an error response. Both the backend (orchestrator) and frontend enforce this rule independently.

**Deferred events**

`pricing_advisor` and `packing_list` are lower-priority agents that start after the seven core parallel agents have completed. This avoids contention on the Anthropic API during the main burst.

**Example SSE stream (abbreviated)**

```
data: {"section": "confidence", "data": {"score": 0.92, "label": "High"}, "status": "done", "source": "static"}

data: {"section": "visa", "data": {"requirement": "Visa on arrival", "duration_days": 90, ...}, "status": "loading", "source": "static"}

data: {"section": "flights", "data": {"outbound": [...], "return": [...]}, "status": "done", "source": "ai"}

data: {"section": "visa", "data": {"requirement": "Visa on arrival", "duration_days": 90, ...}, "status": "done", "source": "ai"}

data: {"section": "itinerary", "data": {"days": [...]}, "status": "done", "source": "ai"}
```

**Errors**: `401` not authenticated, `422` validation failure, `500` orchestrator error.

---

## Destination Discovery

### `POST /api/discover`

Auth required. **Synchronous** (not SSE). Suggests destinations based on traveller profile. Results are cached in memory for 30 minutes (keyed on the full request body).

**Request — `DiscoveryRequest`**
```json
{
  "origin": "LHR",
  "nationality": "British",
  "departure_date": "2026-09-01",
  "return_date": "2026-09-10",
  "budget_usd": 2500,
  "interests": ["beaches", "culture", "food"],
  "adults": 2,
  "children": 0,
  "seniors": 0,
  "infants": 0
}
```

`return_date` is optional. `adults`, `children`, `seniors`, `infants` are counts of travellers by type.

**Response 200**
```json
{
  "destinations": [
    {
      "city": "Lisbon",
      "country": "Portugal",
      "estimated_cost_usd_low": 1400,
      "estimated_cost_usd_high": 2100,
      "visa_type": "Visa-free (Schengen)",
      "visa_verified": true,
      "weather_emoji": "☀️",
      "weather_description": "Warm and sunny, avg 26°C",
      "flight_duration_hours": 2.5,
      "flight_duration_label": "2h 30m",
      "match_reasons": ["Great food scene", "Rich history"],
      "highlights": ["Alfama district", "Pastéis de Belém", "Sintra day trip"]
    }
  ]
}
```

**Errors**: `422` validation failure, `504` agent timed out, `500` agent failure.

---

## Chat Endpoint

### `POST /api/chat`

Auth required. Returns a `text/event-stream` SSE response.

When the chat agent detects a trip-planning request (via regex patterns in the user message), it auto-triggers the full specialist agent pipeline and emits `section_result` events instead of plain text. Otherwise it streams conversational text chunks.

**Request**
```json
{
  "messages": [
    {"role": "user", "content": "Plan a 10-day trip from NYC to Kyoto in October"}
  ],
  "selections": {},
  "search_results": {},
  "session_context": {}
}
```

`selections`, `search_results`, and `session_context` are optional objects used to pass the user's current plan state and prior search results to the chat agent for context-aware responses.

**SSE event types**

| Event type | Payload |
|---|---|
| `text_chunk` | `{"delta": "some text"}` — streaming prose response |
| `section_result` | `{"section": "<name>", "data": {...}, "status": "done", "source": "ai"}` — same shape as `/api/search` events |
| `done` | `{}` — stream complete |

**Errors**: `401`, `422`, `500`.

---

## Plans

### `GET /api/plans`

Auth required. Returns all saved plans for the authenticated user.

**Response 200**
```json
[
  {
    "id": "plan_abc123",
    "name": "Tokyo August 2026",
    "created_at": "2026-05-01T10:00:00Z",
    "updated_at": "2026-05-20T14:30:00Z",
    "request": { "origin": "MUC", "destination": "Tokyo, Japan", "..." : "..." },
    "selections": { "..." : "..." }
  }
]
```

---

### `POST /api/plans`

Auth required. Creates a new saved plan.

**Request**
```json
{
  "name": "Tokyo August 2026",
  "request": {
    "origin": "MUC",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-08-01",
    "return_date": "2026-08-14"
  },
  "selections": {
    "flight": { "outbound": {...}, "return": {...} },
    "hotel": { "name": "Park Hyatt Tokyo", "tier": "luxury", "price_per_night": 450 },
    "activities": [
      { "name": "Tsukiji Outer Market Tour", "relevance_score": 0.95 }
    ],
    "places_to_see": [
      { "name": "Senso-ji Temple", "description": "Iconic Buddhist temple in Asakusa" }
    ],
    "sim": { "provider": "IIJmio", "plan": "15GB eSIM", "price_usd": 18 },
    "tips": ["Carry cash — many places don't accept cards"],
    "getting_around": [
      { "mode": "IC Card (Suica/Pasmo)", "description": "Tap-to-pay on all trains and buses" }
    ],
    "itinerary_slots": [
      { "day": 1, "date": "2026-08-01", "activities": [...] }
    ],
    "packing_list": {
      "categories": { "clothing": ["T-shirts x5", "Light jacket"], "electronics": ["Universal adapter"] },
      "checked_items": ["passport"],
      "custom_items": ["Portable fan"],
      "luggage_note": "Carry-on only recommended for 2 weeks",
      "total_items": 24,
      "checked_count": 1
    }
  }
}
```

**Response 201** — the created plan object (same shape as `GET /api/plans` items).

---

### `GET /api/plans/{id}`

Auth required. Returns a single plan by ID.

**Errors**: `404` plan not found or belongs to another user.

---

### `PUT /api/plans/{id}`

Auth required. Full replacement of a plan. Request body: same shape as `POST /api/plans`. Returns the updated plan.

---

### `DELETE /api/plans/{id}`

Auth required. Deletes the plan. Returns `204 No Content`.

---

## Preferences

### `GET /api/preferences`

Auth required. Returns saved preferences for the authenticated user.

**Response 200**
```json
{
  "nationality": "German",
  "residence_permits": [],
  "existing_visas": [],
  "interests": ["food", "history"],
  "budget_usd": 4000,
  "num_travelers": 2
}
```

---

### `PUT /api/preferences`

Auth required. Replaces all preferences. Request body: same shape as the response above.

**Response 200** — the saved preferences object.

---

## Feedback

### `POST /api/feedback`

Auth required.

**Request**
```json
{
  "page": "search",
  "rating": 4,
  "category": "general",
  "message": "Really helpful, loved the itinerary section!"
}
```

`category` values: `general`, `flights`, `hotels`, `activities`, `itinerary`, `bug`.

**Response 201** — the created feedback object.

---

### `GET /api/admin/feedback`

Admin only. Returns all feedback, with optional filters.

**Query parameters**: `page` (string), `category` (string), `min_rating` (int 1–5).

**Response 200**
```json
[
  {
    "id": 42,
    "username": "alice",
    "page": "search",
    "rating": 4,
    "category": "general",
    "message": "Really helpful!",
    "created_at": "2026-05-01T10:00:00Z"
  }
]
```

---

## Admin — User Management

All admin endpoints require a user with `is_admin: true`.

### `GET /api/admin/users`

Returns all registered users.

**Response 200**
```json
[
  {
    "username": "alice",
    "is_admin": false,
    "requires_password_change": false,
    "created_at": "2026-04-01T09:00:00Z"
  }
]
```

---

### `POST /api/admin/users`

Creates a new user.

**Request**
```json
{
  "username": "bob",
  "password": "TempPassword123!",
  "is_admin": false,
  "requires_password_change": true
}
```

**Response 201** — the created user object (no password field).

**Errors**: `409` username already exists.

---

### `PATCH /api/admin/users/{username}`

Updates a user's `is_admin` flag, `requires_password_change` flag, or resets their password.

**Request** (all fields optional)
```json
{
  "is_admin": true,
  "requires_password_change": false,
  "new_password": "ResetPassword456!"
}
```

**Response 200** — the updated user object.

---

### `DELETE /api/admin/users/{username}`

Deletes a user. Returns `204 No Content`.

**Errors**: `404` user not found, `403` cannot delete yourself.

---

## Health

### `GET /health`

No authentication required. Returns `200 OK` when the backend is running.

```json
{ "status": "ok" }
```

---

## Error Format

All error responses use standard FastAPI format:

```json
{ "detail": "Human-readable error message" }
```

Validation errors (422) return the Pydantic error list:

```json
{
  "detail": [
    { "loc": ["body", "departure_date"], "msg": "field required", "type": "value_error.missing" }
  ]
}
```
