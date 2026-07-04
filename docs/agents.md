# Agent System

This page is the authoritative reference for every agent in Travel Planner: how they are defined, how they execute, what they return, and how to add new ones.

---

## Agent definition format

Every agent is defined by a single file in `.agents/`. The file has a YAML frontmatter block followed by a markdown system prompt body.

```
.agents/
  flights.md
  hotels.md
  activities.md
  places.md
  visa.md
  sim.md
  tips.md
  forex.md
  getting-around.md
  weather.md
  emergency_card.md
  pricing_advisor.md
  packing_list.md
  itinerary.md
  discovery.md
  chat.md
  chat-itinerary.md
  orchestrator.md
```

### YAML frontmatter fields

```yaml
---
name: flights
description: Search for flights between two cities
tools:
  - web_search
max_turns: 3
---

You are a flight search specialist...
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Identifier used by the loader. Must match the filename stem. |
| `description` | string | yes | Short human-readable description shown in logs and tooling. |
| `tools` | list or string | no | Tool names the agent may use. Can be a YAML list or a comma-separated string. Pass `null` or omit for no tools. |
| `max_turns` | integer | no | Maximum conversation turns. Default: 5. |

The markdown body below the closing `---` is used verbatim as the system prompt. The loader appends `"\n\nReturn ONLY valid JSON. No prose, no tool calls, no markdown."` before every API call to enforce structured output.

---

## BaseAgent execution model

`BaseAgent` (in `backend/app/agents/base_agent.py`) is the root class for all agents. Its `execute()` method implements the full lifecycle:

```
1. Load definition
   loader.py reads .agents/{name}.md
   Parses YAML frontmatter → AgentDefinition(name, description, tools, max_turns, system_prompt)

2. Build prompt
   Subclass run() constructs a user prompt from the TravelSearchRequest fields.

3. Call Anthropic API
   Direct anthropic.AsyncAnthropic client (claude-haiku-4-5-20251001, max_tokens=8192).
   System prompt = definition.system_prompt + "Return ONLY valid JSON…"

4. Retry on failure
   Up to 4 attempts with 0.5 s exponential backoff.
   Network errors and empty responses both trigger a retry.

5. Parse JSON (3-strategy fallback)
   Strategy 1: json.loads(text.strip())            — clean JSON output
   Strategy 2: extract ```json … ``` code block     — wrapped output
   Strategy 3: regex \{.*\} first brace block       — embedded JSON

6. Return dict
   Successful parse → dict with domain data.
   All 4 attempts fail → {"error": "<message>"}
```

### ToolAgent and URL enrichment

`ToolAgent` extends `BaseAgent` with a two-phase pattern for agents that need real URLs:

1. `run()` — calls `execute()` immediately; returns fast Haiku-generated data (potentially with placeholder URLs).
2. `enrich(data)` — called by the orchestrator in the background *after* the initial result has been streamed. Subclasses override `_enrich_urls()` or `enrich()` to run web searches and replace placeholder URLs.

The orchestrator streams the initial result first, then streams the enriched result as a second update to the same section. The UI overwrites the section with the enriched data when it arrives.

Agents that implement `enrich()`: FlightsAgent, HotelsAgent, ActivitiesAgent, PlacesAgent, VisaAgent, ForexAgent.

---

## All agents by phase

### Phase 0 — Static instant data (< 1 second)

Phase 0 data comes from `backend/app/agents/static_results.py`, not from AI. Results are yielded before any agent is launched. Source field on every event: `"static"`.

| Section | Function | Coverage |
|---|---|---|
| `visa` | `get_static_visa()` | Nationality × destination lookup table |
| `sim` | `get_static_sim()` | Carrier plans per destination |
| `tips` | `get_static_tips()` | Safety, culture, practical tips per country |
| `getting_around` | `get_static_getting_around()` | Transport modes per destination |
| `forex` | `get_static_forex()` | Currency pair lookup |
| `emergency_card` | `get_static_emergency_card()` | Emergency numbers for 40+ destinations (`_EMERGENCY_NUMBERS`) |
| `confidence` | `get_confidence_score()` | Safety / visa complexity / budget / infrastructure scores for 49 destinations (`_DESTINATION_SCORES`) |

If a static function returns no data for the destination (not in the lookup table), the section is skipped — no static event is emitted and the AI result will be the first data the user sees.

---

### Phase 1 — Parallel AI agents (8–15 seconds)

Eleven agents run concurrently via `asyncio.create_task`. Each streams its result the moment it completes. Source field: `"ai"`.

#### FlightsAgent

**File:** `backend/app/agents/flights_agent.py`

**What it does:** Searches for flights on the requested route. If a SerpAPI key is configured, it calls the Google Flights SerpAPI endpoint first; if that returns no results, it falls back to an LLM-generated response.

**Inputs:** origin, destination, departure date, return date (optional), num_travelers, budget_usd, optional filter dict (max_stops, max_price_usd, departure/arrival time windows).

**Returns:** `{"results": [{airline, price_usd, outbound: {departure, arrival, stops, duration}, return: {...}, booking_url, source}, ...]}`

**Special behaviour:**
- Supports both one-way and round-trip. Round-trip results include both `outbound` and `return` legs and a total per-person price.
- `enrich()` runs web searches per unique airline to find real booking URLs (route-specific first, airline homepage as fallback). Skipped if results already have `source: "google_flights"` (SerpAPI already provides authoritative URLs).

---

#### HotelsAgent

**File:** `backend/app/agents/hotels_agent.py`

**What it does:** Generates hotel options across all four budget tiers.

**Inputs:** destination, check-in/check-out dates, num_travelers, budget_usd, optional filters (num_beds, max_price_per_night_usd, wifi_quality, max_distance_from_center_km, private_washroom).

**Returns:** `{"results": [{name, tier, price_per_night_usd, rating, amenities, location, distance_from_center_km, booking_url, source}, ...]}`

**Special behaviour:**
- Always requests 12 hotels split across luxury, premium, mid-range, and budget tiers.
- `enrich()` runs web searches for up to 12 hotels to find real booking URLs, using the hotel name + destination + platform hint. Falls back to the hotel's official website if the platform search fails.

---

#### ActivitiesAgent

**File:** `backend/app/agents/activities_agent.py`

**What it does:** Generates a ranked list of activities and experiences at the destination.

**Inputs:** destination, interests, trip duration (nights), num_travelers, optional filters (filter_interests, max_price_usd, available_from/to, min_rating).

**Returns:** `{"results": [{name, category, description, price_usd, duration_hours, rating, review_count, similarity_score, booking_url, source}, ...]}`

**Special behaviour:**
- Requests 15–20 activities sorted by `similarity_score` (0.0–1.0) descending.
- After `execute()` returns, `run()` immediately assigns a deterministic Tier 1 booking URL to every activity using `_build_search_url()` — a parameterised search URL for GetYourGuide / Viator / Klook / TripAdvisor / Tiqets / Musement, based on the platform in the `source` field.
- `enrich()` calls the activity URL resolver (SerpAPI-backed or web search fallback) to replace search URLs with real booking page URLs for the top activities.
- The orchestrator feeds the activities result into the sentence-transformers relevance scoring pipeline before streaming, re-sorting by cosine similarity to the user's stated interests.

---

#### PlacesAgent

**File:** `backend/app/agents/places_agent.py`

**What it does:** Finds must-see landmarks and sights using Serper/Google data combined with Claude synthesis.

**Inputs:** destination, interests, trip duration.

**Returns:** `{"results": [{name, category, description, info_url, source, rating, ...}, ...]}`

**Special behaviour (Serper pipeline):**
1. If a Serper API key is configured, `SerperPlacesClient` fetches `/places` and `/guides` results in parallel. Results are cached for 30 minutes per destination.
2. The formatted Serper context is injected into the Claude prompt so the model synthesises real Google data with its internal knowledge.
3. After `execute()` returns, Tier 1 URL matching: Serper `/places` entries include official website URLs; these are matched to result items by name fuzzy match. Unmatched items get a TripAdvisor search URL.
4. `enrich()` calls `SerperPlacesResolver.resolve_top_places()` to replace TripAdvisor fallback URLs with real official or review URLs for the top results.

---

#### VisaAgent

**File:** `backend/app/agents/visa_agent.py`

**Static fallback:** yes

**What it does:** Determines visa requirements, vaccination advisories, and customs rules.

**Inputs:** nationality, destination, intended stay (days), residence_permits, existing_visas.

**Returns:** `{"requirement": {visa_type, max_stay_days, fee_usd, processing_time, official_url, ...}, "vaccinations": {required: [], recommended: [], source_url}, "customs": {duty_free_allowances, prohibited_items, source_url}}`

**Special behaviour:**
- Considers existing visas and residence permits in the prompt (e.g., a US resident permit may grant visa-free entry to certain destinations).
- `enrich()` runs three targeted web searches to find official URLs for the visa requirement, vaccination advice, and customs rules.
- If the AI result contains `{"error": ...}`, the Phase 0 static data is retained and the error is not streamed.

---

#### SimAgent

**File:** `backend/app/agents/sim_agent.py`

**Static fallback:** yes

**What it does:** Recommends SIM card and eSIM options for the destination.

**Inputs:** destination, trip duration, num_travelers, nationality.

**Returns:** `{"plans": [{carrier, plan_type, data_gb, validity_days, price_usd, coverage, purchase_url}, ...]}`

**Special behaviour:** If the AI result contains `{"error": ...}`, the Phase 0 static data is retained.

---

#### TipsAgent

**File:** `backend/app/agents/tips_agent.py`

**Static fallback:** yes

**What it does:** Provides safety, cultural, and practical tips for the destination.

**Inputs:** destination, nationality, interests.

**Returns:** `{"tips": [{category, content, severity}, ...]}`

**Special behaviour:** If the AI result contains `{"error": ...}`, the Phase 0 static data is retained.

---

#### ForexAgent

**File:** `backend/app/agents/forex_agent.py`

**Static fallback:** yes

**What it does:** Provides live exchange rates and money-handling advice for the destination.

**Inputs:** destination, nationality, travel dates.

**Returns:** `{"exchange_rates": [{from_currency, to_currency, rate, source}, ...], "exchange_advice": [...], "atm_advice": ..., "tipping_customs": ..., "source_urls": [...]}`

**Special behaviour:**
- Runs 4 parallel web searches (USD→local, EUR→local, best exchange places, ATM/card info) before calling the LLM.
- If the traveler's home currency is neither USD nor EUR, a fifth search (home→local rate) is added.
- The LLM prompt includes the full raw search snippets; the model extracts real rates from them rather than hallucinating.
- Has lookup tables for 50+ nationalities (`_NATIONALITY_CURRENCY`) and 45+ destinations (`_DESTINATION_CURRENCY`) to determine relevant currency pairs up front.
- `enrich()` searches for authoritative forex guides for the destination country.
- If the AI result contains `{"error": ...}`, the Phase 0 static forex data is retained.

---

#### GettingAroundAgent

**File:** `backend/app/agents/getting_around_agent.py`

**Static fallback:** yes

**What it does:** Explains local transportation options and inter-city travel.

**Inputs:** destination, origin (for inter-city context), budget.

**Returns:** `{"options": [{mode, description, estimated_cost_usd, booking_url, tips}, ...]}`

**Special behaviour:** If the AI result contains `{"error": ...}`, the Phase 0 static data is retained.

---

#### WeatherAgent

**File:** `backend/app/agents/weather_agent.py`

**What it does:** Provides day-by-day weather forecasts or climate estimates for the trip period.

**Inputs:** destination, departure_date, return_date.

**Returns:** `{"days": [{date, description, temp_high_c, temp_low_c, precipitation_mm, wind_kmh, weather_code, is_poor}, ...], "poor_weather_day_count": N, "source": "open-meteo"|"llm-estimate"}`

**Special behaviour:**
- If the departure date is ≤ 16 days from today AND the city is in `CITY_COORDS` (a static lat/lng lookup), the agent fetches real forecast data from the Open-Meteo API (free, no key required). WMO weather codes are decoded to human labels via `_WMO_LABELS`.
- If the departure is > 16 days away, or the city is not in `CITY_COORDS`, or the API call fails, the agent falls back to an LLM seasonal estimate based on historical averages.
- `source` field in the response indicates which path was taken.
- WeatherAgent completion (or failure) unblocks PackingListAgent.

---

#### EmergencyCardAgent

**File:** `backend/app/agents/emergency_card_agent.py`

**Static fallback:** yes

**What it does:** Generates a compact emergency reference card containing embassy contacts, hospital information, emergency numbers, 10 phonetic local phrases, and local laws with severity levels.

**Inputs:** destination, nationality.

**Returns:** `{"emergency_numbers": {police, ambulance, fire, ...}, "embassy": {address, phone, email, ...}, "hospitals": [{name, address, phone, english_spoken}, ...], "phrases": [{local, phonetic, meaning}, ...], "local_laws": [{law, severity, notes}, ...]}`

**Special behaviour:**
- `_same_country()` heuristic detects home-country travel (e.g., American visiting USA). In this case, the prompt instructs the agent to set `embassy` to null and add a `home_country_note` instead.
- If the AI result contains `{"error": ...}`, the Phase 0 static emergency numbers data is retained.

---

### Phase 1 deferred — Triggered mid-Phase-1

These two agents start inside the Phase 1 result-collection loop, not at the beginning of Phase 1. They are launched by the orchestrator as soon as their preconditions are met. Both have a 45-second timeout; if they exceed it or fail, the section is omitted (no fallback data).

#### PricingAdvisorAgent

**File:** `backend/app/agents/pricing_advisor_agent.py`

**Trigger:** FlightsAgent result arrives AND contains ≥ 3 entries with `price_usd`.

**Inputs:** origin, destination, departure_date, computed avg_price from flight results, days_until_departure.

**Returns:** `{"recommendation": ..., "best_time_to_book": ..., "sparkline_data": [{week_offset, relative_price}, ...], "confidence": ...}`

**Special behaviour:** The sparkline data encodes relative price trend for the route, intended for SVG rendering on the frontend. No static fallback.

---

#### PackingListAgent

**File:** `backend/app/agents/packing_list_agent.py`

**Trigger:** ActivitiesAgent result arrives AND WeatherAgent result arrives (or has already failed).

**Inputs:** destination, trip duration (nights), traveler context, interests, weather summary (avg high temp + poor-day count, derived from WeatherAgent output), activity summary (first 8 activity names from ActivitiesAgent output).

**Returns:** `{"categories": [{name, items: [{item, essential, notes}, ...]}, ...]}`

**Categories:** Documents, Clothing, Electronics, Medications, Activity Gear, Destination-Specific.

**Special behaviour:**
- Weather and activities are summarised to plain text before being passed to the LLM (raw JSON is not injected into the prompt).
- The result is saved to My Plan on the frontend; checkbox state for each item is persisted in localStorage.
- No static fallback. If the agent fails or times out, the Packing List section is not shown.

---

### Phase 2 — Sequential synthesis

#### ItineraryAgent

**File:** `backend/app/agents/itinerary_agent.py`

**When it starts:** As soon as both `activities` AND `hotels` Phase 1 results are available. If both arrive during Phase 1 processing, the itinerary task is spawned immediately (before all other Phase 1 agents have finished). Worst case: starts at the end of Phase 1.

**Inputs:** destination, origin, departure/return dates, traveler context, interests, hotel name (first hotel result), top 12 activities (name, category, duration, price, location).

**Returns:** `{"days": [{day_number, date, theme, city, slots: [{time_of_day, activity, location, duration_hours, notes, estimated_cost_usd, lat, lng}], daily_estimated_cost_usd}, ...], "total_estimated_cost_usd": N}`

**Special behaviour:**
- Supports multi-city trips. If `destinations` (list) is passed, the prompt instructs the model to optimise city visit order (minimise backtracking), allocate nights across cities, and add inter-city travel days.
- Every slot includes `lat`/`lng` decimal coordinates for map rendering.
- **Timeout: 60 seconds.** If the agent exceeds this, `_build_fallback_itinerary()` is called instead — a fully local template builder that fills arrival/departure slots from scratch and distributes available activity results across middle days. No AI call; instant.
- If the model returns an empty or malformed result (no `days`), the template fallback is also used.

---

### Discovery — Separate sync endpoint

#### DiscoveryAgent

**File:** `backend/app/agents/discovery_agent.py`

**Endpoint:** `POST /api/discover` (synchronous, not part of the search stream)

**What it does:** Suggests 5 destinations that match a traveler profile when the user has not yet chosen where to go.

**Inputs:** `DiscoveryRequest` — origin, nationality, budget_usd, departure_date, return_date, interests, adults, children, seniors.

**Returns:** `{"destinations": [{city, country, description, why_recommended, estimated_budget_usd, visa_type, visa_verified, highlights: [...]}, ...]}`

**Special behaviour:**
- After the LLM returns its destination suggestions, the agent overrides the `visa_type` field for known nationality × destination pairs using `_VISA_TABLE` from `static_results.py`.
- Destinations with a matching table entry get `visa_verified: true`; unmatched destinations get `visa_verified: false` and the UI renders an amber "Verify" badge.

---

## Static-backed pattern

Six agents have Phase 0 static counterparts: visa, sim, tips, getting_around, forex, emergency_card.

The lifecycle for these agents:

```
Phase 0: static data → streamed (source: "static")
           UI shows section with "Enhancing..." badge

Phase 1: AI agent runs in parallel with others
  ├── Success: AI result → streamed (source: "ai")
  │             UI replaces static section, badge becomes "Done"
  └── Error:   result contains {"error": ...}
               orchestrator suppresses the error event (does NOT stream it)
               Phase 0 static data remains on screen unchanged
```

Both the backend (orchestrator's `_STATIC_BACKED` set) and the frontend SSE handler enforce this rule independently. This means the user always has correct data — the static version is treated as the minimum quality floor.

---

## How to add a new agent

Follow these five steps:

**1. Create the agent definition file**

Create `.agents/my-agent.md` with valid YAML frontmatter and a system prompt that instructs the model to return JSON:

```yaml
---
name: my-agent
description: One-line description of what this agent does
tools: []
max_turns: 3
---

You are a specialist in X. Given Y, return a JSON object with the following shape:
{"results": [...]}

Always include the country name alongside the destination city.
```

**2. Create the Python agent class**

Create `backend/app/agents/my_agent.py`. Subclass `BaseAgent` (or `ToolAgent` if you need URL enrichment):

```python
from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class MyAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "my-agent"))

    async def run(self, request: TravelSearchRequest) -> dict:
        prompt = (
            f"Destination: {request.destination}\n"
            f"Travelers: {request.num_travelers}\n"
            "Do X for this trip."
        )
        return await self.execute(prompt)
```

If the agent needs URL enrichment, subclass `ToolAgent` and override `enrich()` or `_enrich_urls()`.

**3. Instantiate in the orchestrator**

In `backend/app/agents/orchestrator.py`, add to `__init__`:

```python
from .my_agent import MyAgent

# inside __init__:
self.my_agent = MyAgent(agents_dir)
```

**4. Add to the correct phase**

For a standard Phase 1 agent, add it to the `phase1_agents` dict in `stream_run()`:

```python
phase1_agents = {
    ...
    "my_section": self.my_agent,
}
```

For a deferred agent, add the trigger condition inside the Phase 1 result-collection loop (alongside the existing PricingAdvisorAgent and PackingListAgent triggers).

For a Phase 2 agent (needs output from another agent), add it after the Phase 1 loop, similar to `itinerary_task`.

Also add `"my_section"` to the `agent_status` notification loop so the frontend shows a spinner.

**5. Add static-backed suppression if applicable**

If this agent has a Phase 0 static counterpart, add its section name to `_STATIC_BACKED`:

```python
_STATIC_BACKED = {
    "visa", "sim", "tips", "getting_around", "forex", "emergency_card",
    "my_section",  # add here
}
```

And yield the static data in the Phase 0 block before the Phase 1 tasks are launched.


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
