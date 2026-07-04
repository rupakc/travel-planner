# Agent System

Travel Planner's AI capabilities are built on a lightweight agent framework. This page explains how the framework works, how agents are defined, what each of the 15 specialist agents does, and how the system handles failures.

---

## How agents work

### BaseAgent

Every agent inherits from `BaseAgent` (`backend/app/agents/base_agent.py`). It handles:

1. **Loading the agent definition** — reads `.agents/{name}.md`, parses the YAML frontmatter, and stores the system prompt body
2. **Building the conversation** — constructs the messages array with the system prompt and a user message derived from the search context
3. **Calling Claude** — uses `claude-agent-sdk` with configurable model, max_tokens, and max_turns from frontmatter
4. **Retrying on failure** — up to 4 attempts with exponential backoff
5. **Parsing the response** — applies a 3-strategy JSON extraction fallback
6. **Returning a typed result** — all agents return a Pydantic model, never raw dicts

### Agent definition format

Agent prompts live in `.agents/` at the project root. Each file is a markdown document with YAML frontmatter:

```markdown
---
name: flights
description: Finds typical flight routes, airlines, and price guidance
tools: []
max_turns: 1
---

You are a specialist travel flights analyst...
```

**Frontmatter fields:**

| Field | Type | Description |
|---|---|---|
| `name` | string | Agent identifier, must match the filename |
| `description` | string | Human-readable description, used in logs |
| `tools` | list | Tool-use configuration; most agents use `[]` (no tools) |
| `max_turns` | int | Maximum conversation turns passed to the SDK |

Changing agent behaviour means editing the `.md` file — no Python changes needed.

### Retry and JSON parsing logic

**Retry:** Each agent wraps its API call in a retry loop with up to 4 attempts. On rate limits, server errors, or network timeouts, it waits with exponential backoff. On the 4th failure, it returns a structured error result instead of raising an exception.

**JSON parsing (3-strategy fallback):**

1. **Direct parse** — `json.loads()` on the full response text
2. **Code block extraction** — extract content from ` ```json ... ``` ` fences
3. **Regex extraction** — find the first `{...}` block via regex

If all three fail, the agent returns a fallback error result, which the frontend renders as a "not available" section.

---

## The orchestrator phases

### Phase 0 — Static data (instant)

Static lookup tables in `static_results.py` yield results before any AI call:

- `VisaAgent.static()` — visa category from `_VISA_TABLE` keyed by `(nationality, destination)`
- `SimAgent.static()` — SIM options by destination
- `TipsAgent.static()` — travel tips by destination
- `GettingAroundAgent.static()` — transport options by destination
- `get_static_emergency_card()` — emergency numbers from `_EMERGENCY_NUMBERS` (40+ destinations)
- `get_confidence_score()` — safety / visa / budget / infrastructure score from `_DESTINATION_SCORES` (49 destinations)

All stream to the browser within 1 second with `source: 'static'`. The UI shows them as "Enhancing…" until AI results arrive.

### Phase 1 — Parallel AI agents

Thirteen agents run concurrently via `asyncio.gather()`. As each finishes, its result is yielded over SSE:

| Agent | File | Purpose |
|---|---|---|
| FlightsAgent | `flights_agent.py` | Routes, airlines, pricing, booking advice |
| HotelsAgent | `hotels_agent.py` | Neighbourhoods and accommodation tiers |
| ActivitiesAgent | `activities_agent.py` | Activities with interest-relevance scoring |
| PlacesAgent | `places_agent.py` | Landmarks from Serper/Google + Claude synthesis |
| VisaAgent | `visa_agent.py` | Entry requirements, documents, fees |
| SimAgent | `sim_agent.py` | SIM cards, eSIM, local carriers |
| TipsAgent | `tips_agent.py` | Etiquette, safety, health, local knowledge |
| ForexAgent | `forex_agent.py` | Currency, exchange rates, payment tips |
| GettingAroundAgent | `getting_around_agent.py` | Local and intercity transport |
| WeatherAgent | `weather_agent.py` | Forecast for travel dates |
| EmergencyCardAgent | `emergency_card_agent.py` | Embassy, hospitals, phrases, local laws |
| PricingAdvisorAgent | `pricing_advisor_agent.py` | Price trend + booking timing (deferred) |
| PackingListAgent | `packing_list_agent.py` | Personalised packing checklist (deferred) |

**Deferred tasks** (triggered by Phase 1 results, not at start):
- `pricing_advisor` starts when ≥ 3 flight prices are available
- `packing_list` starts when activities are ready AND weather is done (or has failed)

**Static-backed agents**: If visa, SIM, tips, getting around, or emergency card AI calls fail, the error is suppressed and the Phase 0 static data is retained. Users never see a degraded experience for these sections.

### Phase 2 — Itinerary synthesis

`ItineraryAgent` starts once both activities and hotels are available. It synthesises a day-by-day schedule with morning / afternoon / evening slots, daily cost estimates, and weather-aware themes. Has a 60-second timeout with a template-based fallback.

---

## All 15 agents in detail

### FlightsAgent

Generates guidance on flight options between the user's origin and destination. Covers typical routes, airlines, rough price ranges, and booking timing advice. Does not make live flight API calls — uses Claude's knowledge enriched by web search context.

### HotelsAgent

Breaks down accommodation by neighbourhood and type. Covers the best areas to stay (matched to the user's interests), accommodation categories from budget to boutique, price ranges per night, and booking tips. A nightlife-focused user gets different neighbourhood recommendations than a museum-focused user.

### ActivitiesAgent

Generates a list of activities, experiences, and attractions. After the agent returns, the backend applies **relevance scoring**:

1. `sentence-transformers` encodes each activity description and the user's interests string into embedding vectors
2. Cosine similarity is computed between each activity and the interests
3. Activities are sorted descending by similarity score

This means a "street food and local markets" user sees food-focused activities ranked above generic tourist attractions.

### PlacesAgent

Surfaces must-see landmarks, temples, museums, viewpoints, and markets using live data. The pipeline:

1. Calls the Serper `/places` and `/search` APIs to fetch Google Maps data and editorial mentions
2. Sends the raw data to Claude for synthesis into structured results
3. `SerperPlacesResolver` enriches the top results with TripAdvisor, Timeout, and Lonely Planet URLs

Falls back to Claude-only results if `SERPER_KEY` is not configured.

### VisaAgent

Entry requirements specific to the user's nationality: visa category (visa-free / on-arrival / e-visa / embassy), application process, required documents, processing times, fees, and any notable conditions.

### SimAgent

Mobile connectivity: local carriers and prepaid SIM data plans, eSIM availability, coverage quality, and where to buy. Notes whether home-country roaming might be better for short trips.

### TipsAgent

Cultural and practical information: local customs and etiquette, safety, health precautions, tipping culture, bargaining norms, dress codes for religious sites, local laws tourists sometimes accidentally break.

### ForexAgent

Currency guidance: local currency and ISO code, current exchange rate context, whether to exchange before travel or at destination, ATM availability and fees, card acceptance, digital payment adoption.

### GettingAroundAgent

Transport at the destination: airport transfer options with price ranges, public transport usage, ride-hailing apps, taxi culture, car rental, and intercity travel for multi-city trips.

### WeatherAgent

Fetches forecast data from the Open-Meteo API using destination coordinates from `CITY_COORDS`. Returns daily high/low temperatures, weather codes (mapped to emoji), and precipitation probability. Used by the weather section and the Timeline view day headers.

### EmergencyCardAgent

The safety-critical agent. Given destination and nationality, returns:

- Emergency phone numbers (police, ambulance, fire, tourist police)
- The traveller's embassy: address, phone, emergency after-hours line, opening hours
- Nearby international hospitals with English-speaking staff
- Ten phonetic survival phrases in the local language
- Local laws with severity levels (critical / warning)

The backend detects home-country trips and skips the embassy section in that case. The frontend renders a printable card via `window.open()` — reliable across all browsers and mobile.

Phase 0 provides static numbers (from `_EMERGENCY_NUMBERS`, 40+ destinations) immediately. AI enrichment adds the embassy, hospitals, phrases, and laws. If AI fails, the static numbers are retained.

### PricingAdvisorAgent (deferred)

Triggers when ≥ 3 flight prices are available. Receives the route, average price, and days until departure. Returns whether current prices are above or below typical, a booking recommendation, historical relative price trend data for the sparkline, and confidence level. Rendered as a banner above the Flights section.

### PackingListAgent (deferred)

Triggers when activities are ready and weather is done. Receives a summarised prompt (destination, duration, weather summary, planned activities, traveller profile). Returns categories — Documents, Clothing, Electronics, Medications, Activity Gear, Destination-Specific — with items marked essential or optional. Saved to My Plan as a persistent checklist with localStorage-backed checkbox state.

### DiscoveryAgent

Powers the "Surprise Me" flow (`POST /api/discover`). Given origin, budget, dates, nationality, and interests, suggests five curated destinations with cost range, seasonal weather, visa type, flight duration, match reasons, and highlights.

Visa types are post-processed: the LLM's guess is overridden by `_VISA_TABLE` lookup when available. If not in the table, the badge shows "Verify" rather than potentially wrong data.

Runs as a synchronous endpoint (not SSE) with a 30-second timeout and in-memory caching.

### ItineraryAgent

Phase 2 synthesis. Receives activities, hotels, the full search context, and weather data. Generates a structured day-by-day schedule:

- Day number, date, theme, and city
- Morning / afternoon / evening activity slots with name, location, duration, estimated cost, notes
- Daily estimated cost
- Coordinates for the Timeline map view

60-second timeout with a template-based fallback that distributes activities mechanically.

---

## Adding a new agent

1. Create `.agents/{name}.md` with YAML frontmatter and a system prompt
2. Create `backend/app/agents/{name}_agent.py` as a subclass of `BaseAgent`
3. Add it to the orchestrator in `backend/app/agents/orchestrator.py`
4. Add the SSE event type to `AGENT_CONFIG` and `AGENT_ORDER` in `ResultsPage.jsx`
5. Write a section component to render the data

---

## Multi-city behaviour

When `request.is_multi_city` is true, agents change behaviour:

| Agent | Multi-city behaviour |
|---|---|
| flights | One search per leg via `serp_flights.search_multi_city` (parallel one-ways, retry, AI fill for empty legs); results grouped into ordered `legs` |
| weather | Per-stay forecasts (`city_stays`); LLM fallback parses nested per-city output, assigns cities authoritatively by date range, sorts by stop order |
| hotels / activities / places / events | Mandatory per-city quotas; every result tagged with `city` |
| getting_around | Intra-city options per city plus inter-city hops (train/bus/flight) tagged with a `city` route label |
| visa | Evaluates every country on the route |
| itinerary | Allocates days per `city_stays` and visits cities in exactly the user's order — never reorders |

The chat assistant (`chat_agent.py`) is documented separately in [Chat Assistant](Chat-Assistant.md): topic queries are answered from model knowledge only, with specialists as a failure-only fallback; planning requests stream the full pipeline.
