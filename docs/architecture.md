# Architecture

## Multi-Agent Orchestration

The backend uses a **three-phase orchestrator** pattern:

```
POST /api/search
       │
       ▼
TravelOrchestrator.stream_run()
       │
       ├── Phase 0 (instant ~1s)
       │     Static lookup tables → visa, SIM, tips, transport
       │     Yields SSE events immediately
       │
       ├── Phase 1 (parallel ~8-15s)
       │     asyncio.gather() → 7 specialist agents run concurrently
       │     Each yields its SSE event as soon as it finishes
       │
       └── Phase 2 (sequential ~5-10s)
             Itinerary agent waits for activities + hotels
             Synthesises day-by-day plan
```

**Static-first, AI-enhanced pattern:**

Agents with curated static data (visa, SIM, tips, transport) send static results immediately in Phase 0 (tagged `source: "static"`). In Phase 1 they send AI-enhanced results (`source: "ai"`). The frontend replaces static with AI. If the AI agent errors, the error is suppressed and static data is retained.

## SSE Streaming

The search and chat endpoints return `Content-Type: text/event-stream`. Each event is:

```
data: {"section": "flights", "data": {...}, "status": "done"}\n\n
```

The frontend parses SSE in a Web Worker (`sseWorker.js`) to keep parsing off the main thread.

## SQLite on Cloud Run

Cloud Run containers have ephemeral local storage. On startup, all `*.db` files are restored from GCS. A background asyncio task runs every 5 minutes to backup. SIGTERM is handled to run a final backup before shutdown.

## Authentication

JWT-based with bcrypt password hashing. Tokens carry `sub` (username), `is_admin`, and `is_first_login`. On first login, users are redirected to a forced password-change page before they can access the app.

## Frontend State

- `AuthContext` — auth state, preferences, token management
- `SearchDataContext` — shared search data and results between SearchPage and ResultsPage
- Local state — all other UI state (selections, filters, modals)
- Web Workers — SSE parsing for search (`sseWorker.js`) and chat (`chatWorker.js`)
