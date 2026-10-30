# Agent System

How agents are defined and executed, what each one does, and how static data and verification wrap around them.

---

## Agent definitions

Each agent's system prompt lives in `.agents/<name>.md` at the repo root: YAML frontmatter with `name` and `description`, followed by the prompt body.

```markdown
---
name: flights
description: Expert flight search specialist — finds available round-trip flights ...
---

You are a flight search specialist...
```

`backend/app/agents/loader.py` reads the file into an `AgentDefinition(name, description, system_prompt)`. The directory comes from `AGENTS_DIR` (default `<repo>/.agents`). Changing an agent's behaviour usually means editing its prompt; the Python class builds the user prompt and post-processes the JSON.

There are 22 definition files:

| `.agents` file | Python class (`backend/app/agents/`) | Used by |
|---|---|---|
| `flights.md` | `flights_agent.py` | search, `/flights`, compare, chat fallback |
| `weather.md` | `weather_agent.py` | search, compare |
| `hotels.md` | `hotels_agent.py` | search, `/hotels`, compare, chat |
| `activities.md` | `activities_agent.py` | search, `/activities`, chat |
| `places.md` | `places_agent.py` | search (`places_to_see`) |
| `walking_tours.md` | `walking_tours_agent.py` | search, `/walking-tours` |
| `events.md` | `events_agent.py` | search, `/events`, chat warnings |
| `visa.md` | `visa_agent.py` | search, `/visa`, compare, chat |
| `sim.md` | `sim_agent.py` | search, `/sim`, chat |
| `tips.md` | `tips_agent.py` | search, `/tips`, chat |
| `emergency_card.md` | `emergency_card_agent.py` | search |
| `getting-around.md` | `getting_around_agent.py` | search, `/getting-around`, chat |
| `forex.md` | `forex_agent.py` | search, `/forex` |
| `packing_list.md` | `packing_list_agent.py` | search (deferred) |
| `pricing_advisor.md` | `pricing_advisor_agent.py` | search (deferred) |
| `itinerary.md` | `itinerary_agent.py` | search Phase 2, `/itinerary` |
| `stress_test.md` | `stress_test_agent.py` | search (after the itinerary), `/stress-test` |
| `discovery.md` | `discovery_agent.py` | `/discover` |
| `layover.md` | `layover_agent.py` | `/layover` |
| `chat.md` | `chat_agent.py` | `/chat` |
| `chat-itinerary.md` | `chat_itinerary_agent.py` | chat comprehensive planning |
| `orchestrator.md` | none | Descriptive only; the orchestrator is the Python `TravelOrchestrator` |

---

## Execution: `BaseAgent`

`backend/app/agents/base_agent.py`:

- **One API call per attempt.** `execute(prompt)` calls `AsyncAnthropic.messages.create` with model `claude-haiku-4-5-20251001`, `max_tokens` 16384, the definition's prompt as the system prompt (plus "Return ONLY valid JSON") and the agent's prompt as the single user message. No tools are passed to the model.
- **Concurrency.** A global semaphore limits concurrent calls to `AGENT_MAX_CONCURRENCY` (default 6), so a burst of agents does not trip the organisation's rate limits. The SDK client also retries 3 times on its own.
- **Retries.** Up to 4 attempts. Rate-limit, overload and connection errors back off `min(2^n, 10)` seconds; other errors back off `2n` seconds.
- **Token cap.** If a response stops at `max_tokens`, the next attempt adds a "be compact" instruction instead of repeating the same request.
- **JSON parsing** (`_parse_json`), three strategies: parse the whole text, extract a fenced code block, then take the outermost `{...}`.
- **Failure.** After the last attempt the agent returns `{"error": "..."}` rather than raising.

`ToolAgent` (a `BaseAgent` subclass) adds `enrich(data)`, which the orchestrator runs in the background after the first result has streamed; a changed result is streamed again. Flights (LLM results only), hotels, activities, places, visa, sim, tips, getting around and forex override it to look up real links (DuckDuckGo through `web_tools.py`, at most 4 concurrent searches; Serper as a second tier for activities and places when `SERPER_KEY` is set). Only hotels, activities and places_to_see mark their first yield as verification-pending.

Every specialist subclass overrides `run(request)` to build its user prompt and post-process the result. No agent has its own API plumbing.

---

## The specialists

**Flights.** With `SERPAPI_KEY`, live Google Flights results via SerpAPI (`services/serp_flights.py`), marked `live_fare`; single-city results may carry Google's `price_insights`. Multi-city trips search one leg at a time (see [Multi-City Trips](Multi-City-Trips.md)). Without a key, or for legs SerpAPI cannot serve, the LLM produces estimates.

**Weather.** Open-Meteo forecast when the trip starts within 16 days and the city has coordinates (`utils/geo.py`), otherwise an LLM seasonal estimate. Multi-city trips get a forecast per stay.

**Hotels.** Options across budget tiers (luxury, premium, mid-range, budget); links are searched and checked during enrichment.

**Activities.** Activities matched to the traveller's interests. The model itself assigns each activity a relevance `similarity_score`; there is no embedding model in the code base.

**Places to See.** Landmarks and sights. With `SERPER_KEY`, Google Places data from Serper is passed to the model; otherwise the model works alone.

**Free Walking Tours.** `services/walking_tours.py` crawls the public city pages of GuruWalk, FreeTour.com, FreeWalkingTour.com and SANDEMANs NewEurope (free and pay-what-you-wish tours only; cached per provider and city). The LLM only picks and explains tours by candidate id, so every URL comes from the crawl. Each city is topped up to at least `min(4, available)` tours; if the LLM fails, a rating-and-reviews ranking is used.

**Events (What's On).** Festivals, concerts and markets during the dates. A `~` on a date marks a typical-season estimate.

**Visa, SIM, Tips, Getting Around, Forex.** Static-backed (see below). Forex runs several DuckDuckGo searches for current rates in parallel and has the model extract them.

**Emergency Card.** Per-city police, ambulance and fire numbers, the traveller's embassy (skipped for home-country cities), hospitals, survival phrases and local laws. The frontend can print it.

**Packing List** (deferred). Starts when activities and weather are both in; a template list is used after 120 s or on error.

**Pricing Advisor** (deferred). Starts once flights have at least 3 results; gives booking-timing advice and the data for the sparkline in the Flights section. Skipped after 120 s or on error.

**Itinerary.** Day-by-day plan with morning, afternoon and evening slots, each with `duration_hours` and `lat`/`lng`, which the frontend uses to derive estimated times. Template fallback after 60 s.

**Stress Test.** Audits the final itinerary against flights, visa and weather: pacing, timings, visa deadlines, weather clashes. Also callable with an edited itinerary through `POST /api/stress-test` (the "Re-check" button).

**Discovery.** Powers *Surprise me* (`POST /api/discover`): five destinations with cost range, weather, visa type, flight time and match reasons. The visa type is replaced by the static visa table when it has an entry; otherwise it is shown as unverified. 30 s timeout (504), cached.

**Layover.** A mini-plan for a long connection (`POST /api/layover`, up to 48 h).

**Chat and Chat-Itinerary.** See [Chat Assistant](Chat-Assistant.md).

---

## Static data and fallbacks

`backend/app/agents/static_results.py` holds curated tables:

| Table | Entries | Feeds |
|---|---|---|
| `_VISA_TABLE` | 34 (nationality, destination) pairs | Phase 0 visa, visa verification, discovery and compare visa |
| `_DESTINATION_SCORES` | 49 | Travel Ease grade (`get_confidence_score`), daily cost |
| `_EMERGENCY_NUMBERS` | 40 | Phase 0 emergency card, emergency verification |
| `_CITY_TO_COUNTRY` | 204 | Matching a destination to a table country |
| `_GLOBAL_ESIMS` / `_LOCAL_SIMS` | 4 / 10 countries | Phase 0 SIM |
| `_UNIVERSAL_TIPS` / `_DESTINATION_TIPS` | universal + 6 countries | Phase 0 tips |
| `_GETTING_AROUND_TABLE` | 13 | Phase 0 getting around |
| `_FOREX_TABLE`, `_DEST_CURRENCY`, `_NATIONALITY_TO_CURRENCY` | 6, 52, 37 | Phase 0 forex |

**Six agents are static-backed**: visa, sim, tips, getting_around, forex and emergency_card. Phase 0 sends their static result; Phase 1 replaces it with the AI result; if the AI fails, the error is suppressed and the static data stays. Phase 0 also sends a `confidence` event with the Travel Ease grade.

**Matching a destination to a table country** (`_place_country`) uses whole names only, never substrings. A stated country wins. Otherwise the city map is used, including St/Saint variants and city aliases, and checked against a stated region or ISO code ("Miami, FL", "Perth, WA", "Berlin, DE", "Cartagena, ES" → Spain). A city not in the map falls back to the GeoNames place resolver ("Zermatt" → Switzerland), then to unique region names or codes, then to "City Country" written without a comma.

---

## Source verification

The orchestrator attaches `data.verification` to every non-error section just before yielding it (`attach_verification` in `backend/app/services/verification.py`); the filtered endpoints attach the same final label. The function is pure: it uses only evidence already in the data and never calls the network or an LLM. The object never contains an `error` key, so it cannot trip the cache's error guard.

| Section | Evidence | Rule |
|---|---|---|
| flights | `live_fare` on options mapped from SerpAPI (never trusted from LLM output) | all live → verified; some → partial; none → unverified |
| hotels | `link_verified` from enrichment: a search result whose title or path contains the hotel's distinctive name words | counted over the hotels actually searched |
| activities, places_to_see | `link_checked` on every item the resolvers searched; `link_verified` when a trusted result's title contains the item's distinctive name words | "1 of the 5 checked were found online by name" |
| walking_tours | crawl provenance | verified |
| weather | `source: "open-meteo"` | verified; LLM estimates unverified |
| visa | compared with the static visa table | match → verified; different visa type → conflict; no entry → unverified |
| emergency_card | compared with the static emergency numbers | verified only when at least 2 of police/ambulance/fire were compared and all matched; any mismatch → conflict |
| sim, tips, getting_around, forex (Phase 0 yields) | curated reference data | verified |
| everything else (AI yields of the above, itinerary, stress test, packing list, pricing advisor) | none | unverified |

Name matching (`services/name_match.py`) drops destination words and generic words ("hotel", "tour", "museum", …) first, so "Berlin City Tour" is not evidence for a "Top Berlin Tours" page. The first, pre-enrichment yield of hotels, activities and places is `pending: true`; the frontend clears a still-pending label when the stream ends. Model-supplied `link_verified` and `link_checked` flags are stripped, and saved plans drop them.

---

## Adding an agent

1. Create `.agents/<name>.md` with `name` and `description` frontmatter and the system prompt.
2. Create `backend/app/agents/<name>_agent.py`: subclass `BaseAgent` (or `ToolAgent` if it needs link enrichment), load the definition, and implement `run(request)`.
3. Wire it into `TravelOrchestrator` (`backend/app/agents/orchestrator.py`) in the right phase, and add a route under `backend/app/api/routes/` if it should be callable alone (add the `light_ai` rate-limit dependency in `main.py`).
4. If the section should be labelled, add a rule to `verify_section` in `services/verification.py`; otherwise it is "AI-generated".
5. Frontend: add the event type to `AGENT_ORDER` / the agent config in `frontend/src/pages/ResultsPage.jsx` and write the section component.
6. Add tests under `backend/tests/` (the agent classes are excluded from coverage, so test the parsing and orchestration paths directly).
