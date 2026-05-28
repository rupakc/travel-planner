# Architecture

This page explains how Travel Planner is structured end to end: from the moment a user submits a search to the moment the last itinerary line appears on screen.

---

## The three-phase orchestration flow

```
User submits search (destination, dates, budget, nationality, interests)
        │
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE 0 — Instant static data  (< 1 second)                         │
│                                                                      │
│  static_results.py                                                   │
│  ├── visa category map   (_VISA_TABLE, nationality × destination)    │
│  ├── SIM card data       (carrier plans per destination)             │
│  ├── country travel tips (safety, culture, practical)                │
│  ├── transport modes     (_GETTING_AROUND_TABLE)                     │
│  ├── forex baseline      (currency pair lookup)                      │
│  ├── emergency card      (_EMERGENCY_NUMBERS, 40+ destinations)      │
│  └── confidence score    (_DESTINATION_SCORES, 49 destinations)      │
│      └── sub-scores: safety / visa_complexity / budget / infra       │
│                                                                      │
│  All 7 results streamed to browser immediately as SSE events         │
│  Source field on each event: "static"                                │
└──────────────────────────────────────────────────────────────────────┘
        │
        ▼ (Phase 0 results already in browser)
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE 1 — 11 specialist agents in parallel  (8–15 seconds)          │
│                                                                      │
│  asyncio.create_task() for each:                                     │
│    FlightsAgent       HotelsAgent        ActivitiesAgent             │
│    PlacesAgent        VisaAgent          SimAgent                    │
│    TipsAgent          ForexAgent         GettingAroundAgent          │
│    WeatherAgent       EmergencyCardAgent                             │
│                                                                      │
│  As each agent completes, its result is streamed immediately.        │
│  Static-backed agents (visa, sim, tips, getting_around, forex,       │
│  emergency_card): if the AI result contains {"error": ...}, the      │
│  error is suppressed and the Phase 0 static data is retained.        │
│                                                                      │
│  Post-stream enrichment: agents with an enrich() method (Activities, │
│  Places, Forex) run URL resolution in the background concurrently    │
│  with Phase 2. Enriched results are streamed as a second update.     │
│                                                                      │
│  ActivitiesAgent result → sentence-transformers cosine similarity    │
│    scored against user interests → sorted list                       │
│                                                                      │
│  PlacesAgent → Serper/Google Maps API → Claude synthesis →           │
│    SerperPlacesResolver enriches top results with real URLs          │
│                                                                      │
│  ForexAgent → 4 parallel web searches for live rates → LLM          │
│    extracts structured JSON from real search snippets                │
│                                                                      │
│  WeatherAgent → Open-Meteo API (CITY_COORDS, ≤16 days out) or        │
│    LLM seasonal estimate fallback                                    │
└──────────────────────────────────────────────────────────────────────┘
        │
        │  Deferred tasks start as soon as their preconditions are met:
        │
        │  PricingAdvisorAgent: triggers when ≥ 3 flight prices available
        │    → route + avg_price + days_until_departure → recommendation
        │    → SVG sparkline trend data  (timeout: 45 s)
        │
        │  PackingListAgent: triggers when activities ready AND
        │    weather done (or failed)
        │    → destination + weather summary + activity names
        │    → categorised checklist  (timeout: 45 s)
        │
        ▼ (Phase 1 results already streaming to browser)
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE 2 — Itinerary synthesis  (5–15 seconds)                       │
│                                                                      │
│  ItineraryAgent                                                      │
│    Inputs: activities results + hotels results                       │
│    Output: structured day-by-day plan                                │
│    Starts: as soon as BOTH activities AND hotels results arrive       │
│    Timeout: 60 seconds → template fallback (_build_fallback_         │
│             itinerary, fully local, no AI call)                      │
│                                                                      │
│  Runs concurrently with deferred tasks and URL enrichment.           │
│  Streamed as final section SSE event.                                │
└──────────────────────────────────────────────────────────────────────┘
        │
        ▼
  Browser renders complete trip plan
  (done event: {"type": "done"})
```

---

## Static-first design philosophy

Phase 0 exists because some data does not benefit from being generated by a language model. A lookup table for visa categories is faster, cheaper, and more deterministic than asking Claude whether a German passport holder needs a visa for Thailand. Static data is pre-computed, served instantly, and gives the user something to read while the AI agents run. This also makes the application feel significantly faster than a pure AI approach.

The confidence score (`_DESTINATION_SCORES`) gives the UI four numeric sub-scores (safety, visa complexity, budget, infrastructure) that render as a dashboard widget while the main content loads.

The same philosophy applies to the ItineraryAgent's template fallback: if the model is slow or unavailable, the application degrades gracefully rather than timing out with an error. The fallback itinerary is built entirely from already-available activities and hotels data with no additional API calls.

---

## SSE streaming mechanism

The backend uses FastAPI's `StreamingResponse` with `text/event-stream` content type. Every event follows a consistent JSON envelope:

```
data: {"type": "visa",            "data": {...}, "source": "static"}\n\n
data: {"type": "confidence",      "data": {...}, "source": "static"}\n\n
data: {"type": "agent_status",    "agent": "flights", "status": "searching"}\n\n
data: {"type": "flights",         "data": {...}, "source": "ai"}\n\n
data: {"type": "activities",      "data": {...}, "source": "ai"}\n\n
data: {"type": "packing_list",    "data": {...}, "source": "ai"}\n\n
data: {"type": "itinerary",       "data": {...}}\n\n
data: {"type": "done"}\n\n
: keepalive
```

Key conventions:

- **`source: "static"`** — data came from a lookup table; the UI renders it with an "Enhancing..." badge.
- **`source: "ai"`** — data came from an AI agent; the UI replaces static content and shows "Done".
- **`agent_status` events** — sent before Phase 1 starts, one per agent. The UI uses these to show progress spinners.
- **keepalive comments** (`: keepalive`) — sent every 3 seconds when waiting for slow agents, preventing proxy timeouts.

Each event is flushed immediately. The browser receives and renders sections progressively rather than waiting for the full response.

---

## Web Worker pattern

Parsing a high-frequency SSE stream on the browser's main thread risks blocking UI rendering. Travel Planner uses a dedicated Web Worker (`sseWorker.js`) to handle the SSE connection and parse incoming events off the main thread. Parsed section data is posted back to the main thread via `postMessage`, where React state updates trigger re-renders. This keeps the UI responsive throughout the streaming period.

The same pattern is used for the chat interface (`chatWorker.js`), which may trigger the full specialist-agent pipeline if it detects a trip-planning intent in user messages.

---

## Agent dependency diagram

```
Phase 0 (static, instant)
──────────────────────────────────────────────────────────────
  static_results.py → visa / sim / tips / getting_around /
                       forex / emergency_card / confidence

Phase 1 (parallel AI, 8-15 s)
──────────────────────────────────────────────────────────────
  FlightsAgent ──────────────────────────────────────── (stream)
               └─ ≥3 prices ready → PricingAdvisorAgent (deferred)

  HotelsAgent ──────────────────────────────────────── (stream)
              └─────────────────────────────────────► ItineraryAgent (P2)

  ActivitiesAgent → relevance scoring ────────────── (stream)
                  └───────────────────────────────► ItineraryAgent (P2)
                  └─ activities ready + weather done → PackingListAgent

  PlacesAgent → Serper + Claude + Resolver ──────── (stream + enrich)

  VisaAgent ─────────────────────────────────────── (stream / static fallback)
  SimAgent ──────────────────────────────────────── (stream / static fallback)
  TipsAgent ─────────────────────────────────────── (stream / static fallback)
  ForexAgent → web searches → LLM ───────────────── (stream + enrich)
  GettingAroundAgent ─────────────────────────────── (stream / static fallback)
  WeatherAgent (Open-Meteo / LLM estimate) ───────── (stream)
               └─ done/failed → unblocks PackingListAgent

  EmergencyCardAgent ─────────────────────────────── (stream / static fallback)

Phase 1 deferred (start mid-Phase-1 when preconditions met)
──────────────────────────────────────────────────────────────
  PricingAdvisorAgent (45 s timeout) ─────────────── (stream)
  PackingListAgent    (45 s timeout) ─────────────── (stream)

Phase 2 (sequential, starts when activities + hotels ready)
──────────────────────────────────────────────────────────────
  ItineraryAgent (60 s timeout → template fallback) ─ (stream)

Separate endpoint (not part of search stream)
──────────────────────────────────────────────────────────────
  DiscoveryAgent (POST /api/discover, sync) ──────── (response)
```

---

## Deferred tasks

Two agents are not launched at the start of Phase 1. They are triggered mid-Phase-1 as soon as their inputs become available.

**PricingAdvisorAgent**

- Trigger: `flights` result arrives AND contains ≥ 3 entries with `price_usd`.
- Inputs: flight results, computed average price, days until departure.
- Output: booking timing recommendation + SVG sparkline price trend data.
- Timeout: 45 seconds. If it times out or fails, the section is omitted (no fallback).

**PackingListAgent**

- Trigger: `activities` result arrives AND `weather` result arrives (or has failed).
- Inputs: destination, trip duration, traveler context, weather summary (avg high temp + poor-day count), first 8 activity names.
- Output: categorised checklist — Documents, Clothing, Electronics, Medications, Activity Gear, Destination-Specific.
- Saved to My Plan; checkbox state persisted in localStorage on the frontend.
- Timeout: 45 seconds. If it times out or fails, the section is omitted.

Both deferred agents are also started unconditionally at the beginning of Phase 2 as a safety net, in case their trigger conditions were met but not caught during Phase 1 processing (e.g., if the queue was processed very quickly).

---

## SQLite + GCS backup strategy

Travel Planner uses four SQLite databases:

| Database | Contents |
|---|---|
| `users.db` | User accounts, hashed passwords, roles |
| `plans.db` | Saved trip plans per user |
| `preferences.db` | User travel preferences |
| `feedback.db` | User feedback on plans |

SQLite was chosen for operational simplicity: no separate database process to manage, no connection pooling, no migrations to coordinate. For the expected scale of this application (hundreds to low thousands of users), SQLite is more than sufficient.

**Backup mechanism:** A background task runs every 5 minutes and uploads all four database files to a Google Cloud Storage bucket. A SIGTERM handler also triggers a final backup before the process exits (important for Cloud Run deployments, which send SIGTERM before terminating instances).

**Restore on startup:** On application start, if the local database files are missing or empty (as they will be on a fresh Cloud Run instance), the application downloads them from GCS before accepting traffic. This gives Cloud Run's stateless compute the behaviour of a persistent database.

---

## Caching

In-memory caching via `cachetools` (TTL 30 minutes, max 500 entries). Cache keys are used for:

- Serper Places API responses (`serper:places_ctx:{destination}`) — avoids repeated external API calls within a session.
- The cache is shared process-wide, so repeated searches for the same destination within 30 minutes reuse the Serper data.

---

## Why these choices were made

**FastAPI over Django/Flask:** Native async support is essential for running 11+ concurrent agent calls without blocking. FastAPI's `StreamingResponse` makes SSE straightforward to implement. The `asyncio.create_task` + queue pattern allows the orchestrator to stream each result the moment it arrives.

**SQLite over PostgreSQL/MySQL:** Zero infrastructure overhead. The GCS backup strategy handles durability. Cloud Run's ephemeral filesystem is the only risk, and the backup/restore lifecycle addresses it.

**Sentence-transformers for relevance scoring:** A deterministic, locally-run semantic similarity model gives meaningful activity ranking without an extra API call. It runs fast enough (< 500ms) to not add noticeable latency to Phase 1.

**`.agents/*.md` for agent definitions:** Keeping system prompts as markdown files with YAML frontmatter means prompt engineers can edit them without touching Python code. The frontmatter carries metadata (name, description, tools, max_turns) that the BaseAgent reads at load time.

**Web Worker for SSE:** The alternative — parsing SSE on the main thread — causes frame drops on low-end devices during peak streaming. The worker approach is a small amount of complexity for a meaningful UX improvement.

**Deferred agent pattern:** PricingAdvisorAgent and PackingListAgent need data from other agents before they can run. Rather than waiting for all of Phase 1 to finish, they trigger as soon as their inputs are available, hiding their latency behind the remaining Phase 1 agents.

**Static-backed agent suppression:** For agents with Phase 0 static data (visa, sim, tips, getting_around, forex, emergency_card), an AI failure is silently suppressed. The user already has correct static data on screen; replacing it with an error would be a regression. Both the orchestrator (backend) and the SSE event handler (frontend) enforce this invariant independently.
