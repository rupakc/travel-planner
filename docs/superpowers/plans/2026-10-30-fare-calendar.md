# Fare Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Show whether today's fares are low/typical/high (from data Google Flights already returns), and an opt-in strip of the cheapest real fare for departure dates ±3 days (same trip length), with one click to re-plan on a cheaper date.

**Spec:** Backlog #9. Facts: research-16-18-9.md (#9 section). Choices are Claude's.

## Design (binding)

Options weighed: (a) LLM-estimated date grid — rejected (fabricated numbers; contradicts the verification rule); (b) 7×7 departure×return grid — rejected (49 SerpAPI calls); (c) **price_insights from existing responses (0 extra calls) + opt-in ±3-day departure strip keeping trip length (6 extra calls, cached)** — chosen.

Backend:
- `serp_flights.py`: capture `price_insights` from the outbound search response (`lowest_price`, `price_level`, `typical_price_range`, `price_history`) and include it in the flights result as `price_insights` (single-city only); absent → omitted. Not cached separately (rides with the result). Verification for flights unchanged.
- New `search_calendar(api_key, request, window=3)` in serp_flights.py: for each offset in −3..+3 (skip dates before tomorrow; skip offset 0 if the main search result is cached — reuse it), build params via `_build_params(request.model_copy(update={departure_date, return_date shifted by the same offset}))`, ONE outbound call per date (no return-leg calls), cheapest `price` across best/other flights; concurrency limited (semaphore 4); per-date cache key `serp-cal:{origin}:{dest}:{dep}:{ret}:{adults}` (30-min TTL, shared cache); a failed date → `null` price, not an error.
- Route `POST /api/flights/fare-calendar` (auth required like other routes; `light_ai` rate-limit bucket from the hardening branch if present, else no limiter) body = TravelSearchRequest; 422 for multi-city; 503 `{"detail": "Fare calendar needs live flight data, which isn't configured."}` when `settings.serpapi_key` is empty; response `{ dates: [{ departure_date, return_date, cheapest_usd|null, is_selected }], currency: "USD", source: "google_flights" }`.
- Tests: mocked `_call` (no network) — window dates, past-date skipping, null on failure, cache hit, 422/503/401, price_insights passthrough.

Frontend:
- Flights section: when `results.flights.price_insights` exists, a chip under the pricing banner: "Fares are low right now · typical $420–$610" (green/gray/amber for low/typical/high) — real data, linked to the verification idea (no AI).
- "Fare calendar" pill in the Flights header actions (next to Filters) shown only when `/health` reports `serpapi_configured` (fetch once; cache in module) and the trip is single-city. Click → loads `FareCalendarStrip` below the banner: 7 cells (weekday, date, price or "—"), cheapest highlighted emerald, selected date outlined, delta vs selected ("−$45"). Loading skeleton; error row with Retry (string detail via existing error helpers; 429 detail shown).
- Clicking a different date opens an inline confirm: "Re-plan for Tue 3 Nov – Tue 10 Nov? This runs a new search." → on confirm, `runSearch({...searchData, departure_date, return_date})` (existing full search path; selections reset as with Remix) and `track('fare_calendar_replan', 'results', { offset })`.
- Pure helpers in `frontend/src/utils/fareCalendar.js` (shiftDates, cheapest/delta, formatting) + tests; component `FareCalendarStrip.jsx` + test.
- Fix the PricingAdvisorBanner date bug noted in research (it parses the destination as a date) since we touch this area: use `searchData.departure_date`.
- Docs: API-Reference (endpoint), Frontend.md, CLAUDE.md API table.

Non-goals: multi-city calendars, return-date grid, LLM fallback grid, price alerts.

## Global Constraints
No new deps; no network in tests; backend pytest/ruff, frontend vitest/eslint/build.

---
### Task 1: Backend price_insights + fare-calendar endpoint (+tests)
### Task 2: Frontend helpers + FareCalendarStrip + insights chip + wiring + banner fix + docs
