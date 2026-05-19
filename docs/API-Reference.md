# API Reference

The Travel Planner backend is a FastAPI application running on port 8001. All endpoints are under `/api/`. Interactive documentation (Swagger UI) is available at `/docs` and ReDoc at `/redoc`.

**Base URL (local):** `http://localhost:8001`

**Authentication:** Protected endpoints use JWT Bearer tokens. Include the token from the login response in the `Authorization` header:
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
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin"
  }
}
```

If `requires_password_change` is `true`, the frontend redirects to the password change screen before allowing further navigation.

---

### `POST /api/auth/change-password`

Change the current user's password.

**Auth required:** Yes

**Request body:**
```json
{
  "current_password": "old-password",
  "new_password": "new-password"
}
```

**Response:** `200 OK` with `{"message": "Password changed successfully"}`

---

### `GET /api/auth/me`

Get the currently authenticated user's profile.

**Auth required:** Yes

**Response:**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "created_at": "2025-01-01T00:00:00Z"
}
```

---

## Search endpoints

### `POST /api/search` (SSE streaming)

The primary endpoint. Submits a travel search and streams results as they become available via Server-Sent Events.

**Auth required:** Yes

**Request body:**
```json
{
  "destination": "Tokyo",
  "start_date": "2025-06-01",
  "end_date": "2025-06-14",
  "nationality": "German",
  "budget": "medium",
  "interests": "street food, anime, temples, nightlife"
}
```

**Budget values:** `"budget"`, `"medium"`, `"luxury"`

**Response:** `Content-Type: text/event-stream`

The response is a stream of SSE events. Each event has this structure:
```
data: {"section": "<section_name>", "content": <object>, "phase": <0|1|2>}\n\n
```

**Section names and phases:**

| Section | Phase | Description |
|---|---|---|
| `visa_static` | 0 | Static visa category lookup |
| `sim_static` | 0 | Static SIM data |
| `tips_static` | 0 | Static country tips |
| `transport_static` | 0 | Static transport modes |
| `flights` | 1 | FlightsAgent result |
| `hotels` | 1 | HotelsAgent result |
| `activities` | 1 | ActivitiesAgent result (relevance-sorted) |
| `visa` | 1 | VisaAgent result |
| `sim` | 1 | SimAgent result |
| `tips` | 1 | TipsAgent result |
| `getting_around` | 1 | GettingAroundAgent result |
| `forex` | 1 | ForexAgent result |
| `itinerary` | 2 | ItineraryAgent result |

The final event is:
```
data: [DONE]\n\n
```

On agent failure, a section is still emitted with `"error": true` in the content, so the frontend can display a "not available" card for that section rather than hanging.

---

### `POST /api/search/sync`

Same as `/api/search` but waits for all agents to complete and returns the full result as a single JSON response. Useful for testing; not recommended in production due to latency.

**Auth required:** Yes

**Request body:** Same as `/api/search`

**Response:**
```json
{
  "destination": "Tokyo",
  "sections": {
    "flights": {...},
    "hotels": {...},
    "activities": [...],
    "itinerary": {...}
  },
  "generated_at": "2025-06-01T10:00:00Z"
}
```

---

## Chat endpoints

### `POST /api/chat` (SSE streaming)

Conversational follow-up chat with travel context awareness.

**Auth required:** Yes

**Request body:**
```json
{
  "message": "Can you suggest some vegetarian restaurants in Shinjuku?",
  "session_id": "optional-session-id-for-continuity",
  "trip_context": {
    "destination": "Tokyo",
    "start_date": "2025-06-01",
    "end_date": "2025-06-14"
  }
}
```

**Response:** `Content-Type: text/event-stream`

Events:
```
data: {"type": "chunk", "content": "Here are some great..."}\n\n
data: {"type": "chunk", "content": " vegetarian options..."}\n\n
data: [DONE]\n\n
```

---

## Plans endpoints

### `GET /api/plans`

List all saved plans for the authenticated user.

**Auth required:** Yes

**Response:**
```json
[
  {
    "id": 1,
    "destination": "Tokyo",
    "start_date": "2025-06-01",
    "end_date": "2025-06-14",
    "created_at": "2025-05-01T12:00:00Z"
  }
]
```

---

### `POST /api/plans`

Save a trip plan.

**Auth required:** Yes

**Request body:**
```json
{
  "destination": "Tokyo",
  "start_date": "2025-06-01",
  "end_date": "2025-06-14",
  "plan_data": { ... }
}
```

**Response:** The saved plan with its assigned `id`.

---

### `GET /api/plans/{plan_id}`

Retrieve a specific saved plan.

**Auth required:** Yes (must be the owner)

**Response:** Full plan object including `plan_data`.

---

### `DELETE /api/plans/{plan_id}`

Delete a saved plan.

**Auth required:** Yes (must be the owner)

**Response:** `204 No Content`

---

## Preferences endpoints

### `GET /api/preferences`

Get the authenticated user's travel preferences.

**Auth required:** Yes

**Response:**
```json
{
  "default_nationality": "German",
  "default_budget": "medium",
  "interests": "museums, street food, architecture"
}
```

---

### `PUT /api/preferences`

Update travel preferences.

**Auth required:** Yes

**Request body:** Same structure as GET response. All fields optional — only provided fields are updated.

---

## Feedback endpoints

### `POST /api/feedback`

Submit feedback on a plan section.

**Auth required:** Yes

**Request body:**
```json
{
  "plan_id": 1,
  "section": "activities",
  "rating": 4,
  "comment": "Good suggestions but missing some famous spots"
}
```

**Rating:** Integer 1–5

**Response:** `201 Created` with the saved feedback object.

---

## Admin endpoints

All admin endpoints require a user with `role: admin`.

### `GET /api/admin/users`

List all user accounts.

**Auth required:** Yes (admin only)

**Response:** Array of user objects (without password hashes).

---

### `POST /api/admin/users`

Create a new user account.

**Auth required:** Yes (admin only)

**Request body:**
```json
{
  "username": "newuser",
  "password": "TemporaryPassword123",
  "role": "user"
}
```

**Roles:** `"user"`, `"admin"`

New users are flagged as requiring a password change on first login.

---

### `DELETE /api/admin/users/{user_id}`

Delete a user account.

**Auth required:** Yes (admin only)

**Response:** `204 No Content`

---

## Health endpoints

### `GET /api/health`

Basic liveness check.

**Auth required:** No

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2025-06-01T10:00:00Z"
}
```

---

### `GET /api/health/ready`

Readiness check — confirms databases are accessible and the application is ready to serve traffic.

**Auth required:** No

**Response:**
```json
{
  "status": "ready",
  "databases": {
    "users": "ok",
    "plans": "ok",
    "preferences": "ok",
    "feedback": "ok"
  }
}
```

Cloud Run uses this endpoint for startup and readiness probes.
