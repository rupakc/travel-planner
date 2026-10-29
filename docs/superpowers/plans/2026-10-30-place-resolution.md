# Place Resolution Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) Free-text cities ("Berlin", "Berlin, Germany", "BER — Berlin, Germany") get real airport codes for live flight search and the fare calendar. (2) "City, XX" where XX is an ISO country code resolves to that country in the reference tables. (3) The chat itinerary prompt asks for durations and coordinates like the main itinerary prompt.

**Spec:** Follow-ups surfaced on 2026-10-30. Choices are Claude's (user delegated).

## Design (binding)

1. City → airport codes (backend):
   - Where: the `TravelSearchRequest` validator that today resolves 3-letter codes (backend/app/schemas/request.py `resolve_iata_codes`, `origin_iata` / `destination_iata` excluded fields) — extend it so that when origin/destination is NOT already a code, it looks the place up in the local airports database (the same data `/api/airports/search` serves; find the DB helper in backend/app/db/) by city name: first comma segment (after stripping a leading "XXX — " prefix), case-insensitive exact city match; if a country is given (last comma segment), restrict to that country (accept common names/aliases the DB uses); pick up to 3 airports in that city, primary/largest first if the DB has such a signal, else stable by code; set `origin_iata`/`destination_iata` to the comma-joined list (SerpAPI accepts comma lists for departure_id/arrival_id).
   - Multi-city: apply the same to each `destinations[]` entry wherever the multi-city flight search reads codes (check `serp_flights` multi-city params builder).
   - NEVER perform web/network lookups in this path (the existing web fallback for unknown 3-letter codes is untouched); unknown city → leave unset → today's behaviour (AI estimate).
   - `serp_flights._build_params` (and the calendar) must use the resolved codes; verify the existing code already prefers `origin_iata`/`destination_iata`, otherwise wire it.
   - Tests (DB seeded in tests as other tests do): "Berlin" → BER; "Berlin, Germany" → BER; "BER — Berlin, Germany" → BER; "London" → up to 3 London airports incl. LHR; "Paris, Texas" → none (no match in that country); "Springfield" ambiguity without country → pick only if all matches share one country, else none; codes passed through unchanged; `_build_params` uses the comma list; no network calls (monkeypatch any web helper to fail).
2. ISO country codes in reference lookups (backend/app/agents/static_results.py `_place_country` / normaliser):
   - Add an ISO-3166 alpha-2 → table-country map for every country present in the reference tables (and their aliases).
   - Rule for a trailing ≤2-letter segment: if the city-map country for the city equals the ISO code's country → that country; else if the code is an ISO code and the city is unknown → that country; else if it's a US state code and the city-map says usa (or the city is unknown and the code is not an ISO country) → usa; otherwise no row. Examples (tests): "Berlin, DE" → germany; "Toronto, CA" → canada; "Bali, ID" → indonesia; "Delhi, IN" → india; "Miami, FL" → usa; "Paris, FR" → france; "Paris, TX" → no row; "Paris, Texas" → no row. The existing lookup regression suite must stay green.
3. Chat itinerary prompt (backend/app/agents/chat_itinerary_agent.py): require `duration_hours` on every slot and lat/lng on every slot (approximate neighbourhood or hotel coordinates when there's no specific place), matching .agents/itinerary.md wording; prompt test like backend/tests/test_itinerary_timing_prompt.py.

Docs: API-Reference / Agent-System lines where these behaviours are described.

## Global Constraints
No new deps; no network in tests; backend pytest + ruff; frontend untouched.

---
### Task 1: City → airport codes (+tests)
### Task 2: ISO country codes (+tests)
### Task 3: Chat itinerary prompt (+test) + docs
