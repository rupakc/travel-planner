# API Reference

Interactive Swagger UI is available at `https://<backend-url>/docs` when the backend is running.

## Authentication

All endpoints except `/api/auth/login` and `/health` require a JWT bearer token:

```
Authorization: Bearer <token>
```

Obtain a token via `POST /api/auth/login`.

## Key Endpoints

### `POST /api/auth/login`
```json
{ "username": "string", "password": "string" }
```
Returns:
```json
{
  "access_token": "...",
  "token_type": "bearer",
  "user": { "username": "...", "is_admin": false, "requires_password_change": false }
}
```

### `POST /api/search`
Streams SSE events. Request body: `TravelSearchRequest`.
```json
{
  "origin": "MUC",
  "destination": "TYO",
  "departure_date": "2026-06-01",
  "return_date": "2026-06-14",
  "interests": ["food", "history"],
  "nationality": "German",
  "budget_usd": 3000,
  "num_travelers": 2
}
```
Each SSE event:
```
data: {"section": "flights", "data": {...}, "status": "done", "source": "ai"}
```

### `POST /api/feedback`
```json
{
  "page": "search",
  "rating": 4,
  "category": "general",
  "message": "Really helpful!"
}
```

### `GET /api/admin/feedback`
Query params: `page`, `category`, `min_rating`. Admin only.

### `POST /api/analytics/events`
```json
{
  "events": [
    { "feature": "search_submit", "page": "search", "metadata": { "destination": "Tokyo" }, "ts": 1234567890 }
  ]
}
```
Returns 204 No Content. Events are logged to stdout → Cloud Logging.
