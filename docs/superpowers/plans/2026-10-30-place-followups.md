# Place Resolution Follow-ups (Round 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the four follow-ups parked after PR #17: a US/CA/AU/BR state narrows a city's airports ("Portland, OR" → PDX only), Washington spellings resolve, accented input resolves, and the fare calendar's selected-date price agrees with the flight cards.

**Spec:** User request 2026-10-30 ("these are things we should explicitly account for and resolve"). Facts gathered by the controller are listed under each item. Choices are Claude's.

## Facts (verified against the seed and code)
- `backend/app/db/seed_airports.py`: 544 airports; city names are ASCII-folded ("Sao Paulo", "Zurich", "Montreal", "Krakow", "Reykjavik", "Malmo", "Dusseldorf", "Bogota", "Medellin"); the only non-ASCII city is "Ålesund". No state/region column. US 81, CA 11, AU 11, BR 10 airports.
- Same-name cities more than 60 km apart: within one country only "portland" (PDX/US, PWM/US, 4070 km); across countries birmingham, san jose, victoria (already None via the country-code ambiguity rule).
- Washington is stored as city "Washington D.C." (IAD, DCA); BWI is a separate city. "St. Petersburg" is stored with the period; "New York" (JFK, LGA).
- Fare calendar (`serp_flights.search_calendar`): non-selected dates use `_cheapest(outbound response)` (the cheapest `price` from the first, outbound-stage call). The selected date uses `_cached_selected_price(main)`, which prefers Google's `price_insights.lowest_price`. Flight cards are return-stage round-trip totals (`_map_result` on return items). Observed live: selected $360 (lowest_price) vs cheapest card $341.

## Design (binding)

1. **State/region narrows airports** (`lookup_city_iata`):
   - Add a curated `AIRPORT_REGION: dict[str, str]` (IATA → region code: US state / CA province / AU state / BR UF, lower-case 2–3 letters matching `core/places.py` region codes) covering **every** US, CA, AU and BR airport in the seed. A completeness test fails when a seed airport in those countries has no region. Put the map next to the seed data (e.g. `backend/app/db/airport_regions.py`); no DB schema change.
   - When the stated last segment is a region code or US state name, keep only the rows whose `AIRPORT_REGION` equals that region; rows without region data (other countries, web rows) are dropped by a region filter.
   - Same-country, far-apart matches: if the remaining rows span more than one region (by `AIRPORT_REGION`) and no region was stated, the city is ambiguous → None. ("Portland" → None; "Portland, OR" → PDX; "Portland, Maine" → PWM; "Portland, ME" → PWM.) Rows from countries without region data keep today's behaviour (London still → LHR,LGW,STN).
   - Tests for each example above plus "Springfield, IL" when present in the seed (else skip), "Birmingham, AL" → BHM, "Birmingham, UK" → BHX, "San Jose, CA" → SJC, "Victoria, BC" → YYJ.

2. **City spelling normalisation** (both `lookup_city_iata` and `static_results.normalise_place` / `_place_country`):
   - One shared helper in `backend/app/core/places.py`: `fold_place(text) -> str` — NFKD + strip combining marks, plus explicit transliteration for ß→ss, ø→o, æ→ae, œ→oe, ł→l, đ→d, ı→i, þ→th, ð→d; lower-case, collapse whitespace.
   - A small `CITY_ALIASES` map (folded alias → DB city spelling), at minimum: washington / washington dc / washington d c / washington d.c. / dc → "Washington D.C."; saint petersburg / st petersburg → "St. Petersburg"; new york city / nyc → "New York" (only when not a bare code — the bare-code path wins for "NYC"); saigon → "Ho Chi Minh City"; bombay → "Mumbai". Verify each target exists in the seed (test).
   - `lookup_city_iata` queries `city IN (:typed, :folded, :alias)` with COLLATE NOCASE (still indexed, one query). "Ålesund" must still match when typed with or without the ring.
   - `_place_country`: fold the city before the city-map lookup and fold the map keys once (accented keys like "são paulo" stay valid). "Zürich" / "Zurich, Switzerland" / "São Paulo, BR" / "Washington" / "Washington DC" / "Washington, D.C." all resolve (switzerland / brazil / usa). "Washington" alone must not become ambiguous with the US state name — usa either way.
   - Tests: "São Paulo" → GRU (+ others in the seed), "Zürich" → ZRH, "Düsseldorf" → DUS, "Kraków" → KRK, "Malmö" → MMX, "Reykjavík" → RKV (+KEF if seeded as Reykjavik), "Washington" / "Washington, DC" / "Washington D.C." → IAD,DCA, "Saint Petersburg" → LED, "St Petersburg" → LED, "Ålesund"/"Alesund" → AES.

3. **Fare calendar selected-date price agrees with the cards** (`serp_flights.py`):
   - The main round-trip / one-way search records the cheapest outbound-stage price (`_cheapest(data1)` / `_cheapest(data)`) for its dates when it ran unfiltered, by writing the per-date calendar cache entry the calendar already reads (`serp-cal:` key, same format as `search_calendar` uses).
   - `search_calendar` selected date: `min(cheapest outbound-stage price for that date, cheapest mapped card price from the cached main search)`, either may be missing; fall back to Google's `lowest_price` only when both are missing. Update `_cached_selected_price` and its docstring accordingly; non-selected dates unchanged.
   - Tests (mocked `_call`): main search writes the cal cache entry when unfiltered and not when filtered; selected date = cheapest card when the cards are cheaper than lowest_price (the $341 vs $360 case); selected date = outbound cheapest when no cards; lowest_price only when neither exists; existing calendar tests stay green.

Docs: API-Reference / Agent-System lines that describe city resolution and the fare calendar.

## Global Constraints
No new deps; no network in tests; backend pytest + ruff check + ruff format --check; frontend untouched. Existing tests change only where they asserted the old selected-date preference.

---
### Task 1: Region-narrowed airports (+tests)
### Task 2: Spelling normalisation in both lookups (+tests)
### Task 3: Fare calendar selected-date price (+tests) + docs
