# Trip Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user compare 2–3 destinations side by side for the same origin, dates and travellers — estimated trip cost, cheapest flight, typical hotel price, weather, visa, safety and ease — then start the full plan for the one they pick with one click.

**Architecture:** A new lightweight backend endpoint `POST /api/compare/destination` summarises ONE destination by running only the decision-relevant agents (flights, hotels, weather; visa only when the static table can't answer) in parallel plus the instant static scores, then reducing them to a compact summary with a pure, unit-tested function. The frontend adds a third Search-page mode, "Compare", that fires one request per destination in parallel and fills each column as it arrives.

**Tech Stack:** FastAPI + Pydantic v2, existing agents (`FlightsAgent`, `HotelsAgent`, `WeatherAgent`, `VisaAgent`), static tables in `backend/app/agents/static_results.py`, in-memory TTL cache (`backend/app/core/cache.py`); React 18 + Tailwind; pytest (asyncio_mode=auto), vitest.

**Spec:** Backlog item #1 in `Future_Improvements.md` ("Trip Comparison / Side-by-Side View"). Facts: `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/research-1-28.md` Part A. Design choices are Claude's (user delegated them).

## Design (binding)

Options weighed:
- (a) Run two or three full `/api/search` streams side by side — rejected: ~17 LLM calls each through a process-wide semaphore of 6 (each search ~2× slower), minutes of waiting, and the Results page holds only one result set.
- (b) Reuse Discover (one LLM call guessing costs) — rejected: estimates only, no real flights/weather; exactly the "is this real?" problem.
- (c) **Per-destination lightweight summary endpoint** — chosen: ~2–3 LLM calls per destination (flights unless SerpAPI is configured, hotels, visa only if not in the static table, weather only for cities Open-Meteo can't serve), real weather, static scores instant; parallel per destination; cacheable per request.

Backend:
- `POST /api/compare/destination`, auth required like other routes, body = `TravelSearchRequest` (single destination; `destinations` must be null/≤1 — multi-city is rejected with 422 "Compare works with single destinations").
- Runs concurrently with per-piece timeouts: `FlightsAgent.run` (45 s), `HotelsAgent.run` (45 s; **no enrich** — URLs aren't needed for comparing), `WeatherAgent.run` (30 s), visa = `get_static_visa(request)` if it returns data else `VisaAgent.run` (30 s). A piece that fails or times out becomes `null` in the summary with its name listed in `missing`; the endpoint still returns 200 if at least one piece succeeded, else 502.
- Summary (pure function `summarize_destination(request, flights, hotels, weather, visa, confidence) -> dict` in `backend/app/services/compare.py`):
  - `destination` (as given), `label` (city name: hotels/flights destination string's first comma segment if present, else request.destination)
  - `flight`: cheapest valid fare `{price_usd, stops, duration_minutes, airline, source}` where stops/duration sum outbound + return; `price_usd > 0` finite only; prefer non-`estimate` sources when any exist. `null` if none.
  - `hotel`: `{typical_nightly_usd, cheapest_good_nightly_usd, count}` — typical = median nightly price of 3★–4★ hotels (fallback all priced hotels); cheapest_good = lowest nightly with `review_score >= 7` (null if none). `null` if no priced hotels.
  - `weather`: `{avg_high_c, avg_low_c, poor_days, total_days, source}` from `weather.days`; `null` if no days.
  - `visa`: `{visa_type, max_stay_days, fee_usd, processing_time, verified}` — `verified = True` only when it came from the static table.
  - `ease`: from `get_confidence_score(request)`: `{total, grade, safety, english, infrastructure, visa_ease}` (sub-score `score` values); `null` when the destination isn't in the table.
  - `daily_cost_usd`: the table's `avg_daily_cost_usd` for the destination (expose via a small helper next to `get_confidence_score`; null when unknown).
  - `estimate`: `{total_usd, flight_usd, stay_usd, daily_usd, nights}` per traveller — flight price + typical nightly × nights + daily cost × days (days = nights, min 1; nights from dates, default 7). Any missing part → that part null and `total_usd` = sum of known parts with `partial: true`. `budget_status`: `'under' | 'over' | null` vs `request.budget_usd`.
  - `missing`: list of piece names that failed.
  - All numbers coerced defensively (strings/junk → ignored).
- Cache: key `"compare:" + md5(request.model_dump_json())` in the shared TTL cache; store only complete-enough results (≥1 piece) and never cache a 502.
- Chat is untouched.

Frontend:
- SearchPage mode toggle gains **"Compare"** (third button). Its form: origin, 2–3 destination fields (AirportSearch; "Add another" up to 3; remove ×), departure/return dates, nationality, budget, travellers, interests — prefilled from the known-mode form/preferences the same way Discover prefills.
- On "Compare", one `compareDestination(request)` call per destination in parallel (new function in `frontend/src/services/api.js`, axios like the others); each column shows its own loading/error state ("Couldn't load — Retry").
- **Comparison table** (`frontend/src/components/CompareTable.jsx`): one column per destination; rows: Estimated trip cost per traveller (with budget chip; "partial" note), Cheapest flight (price · stops · duration · "estimate" badge when source is estimate), Hotel per night (typical / from), Weather (avg high/low °C, "N of M days poor", "climate estimate" when not Open-Meteo), Visa (type, fee, max stay; "Verified" vs "AI — check official site"), Travel Ease (total/100 + grade colour), Safety /20, English /20, Typical daily spend. Per numeric row the best value gets an emerald "Best" marker (lowest cost/price, fewest poor days, highest ease/safety/english); ties mark all; rows with <2 known values mark none. Mobile: columns become stacked cards (no horizontal page scroll at 375px).
- Each column has **"Plan this trip"**: switches to known mode with the form prefilled with that destination and the shared fields, and submits it (the normal full search).
- Pure helpers in `frontend/src/utils/compare.js`: `buildCompareRequests(form) -> TravelSearchRequest[]`, `bestByRow(summaries) -> { [rowKey]: Set<index> }`, formatters. Unit-tested.
- Analytics: `track('compare_run', 'search', { count })`, `track('compare_plan_clicked', 'search', { position })`.

Non-goals: comparing saved plans, multi-city comparison, chat, sharing a comparison, more than 3 destinations.

## Global Constraints

- No new dependencies. Backend route registered in `backend/app/main.py` like the others; document it in CLAUDE.md's API table and `docs/API-Reference.md`.
- Backend tests: `cd backend && python3 -m pytest -q` (baseline 333). Agents are mocked the established way: `Agent.__new__(Agent)` + `AsyncMock` on `run` / patching (see `backend/tests/test_walking_tours_agent.py`, `backend/tests/test_discover.py`); never call Anthropic in tests.
- Frontend: `NODE_OPTIONS=--experimental-require-module npx vitest run`, `npx eslint src/ --max-warnings 0`, `npm run build`. Component tests `createRoot` + `act`, mock `../utils/analytics`.
- Every external link (none expected) via `safeUrl`.

## Review Focus

1. One destination failing or timing out — other columns still render; the failed column offers Retry; endpoint returns partial data with `missing`.
2. Junk agent output (string prices, missing outbound/return, empty lists) — summary never contains NaN or crashes.
3. Destinations not in the static tables (no ease/daily cost/visa) — rows show "—", estimate marked partial, no "Best" on rows with <2 values.
4. Same destination entered twice / fewer than 2 destinations — form validation blocks submit with a message.
5. "Plan this trip" — exactly the compared request (dates, travellers, budget, nationality, interests) runs as a normal search.

---

### Task 1: Backend summary + endpoint

**Files:**
- Create: `backend/app/services/compare.py` (`summarize_destination`), `backend/app/api/routes/compare.py`
- Modify: `backend/app/agents/static_results.py` (add `get_destination_daily_cost(request) -> float | None` beside `get_confidence_score`), `backend/app/main.py` (register router)
- Test: `backend/tests/test_compare.py`

- [ ] **Step 1: Failing tests:** `summarize_destination` — cheapest fare with stops/duration summed and estimates de-preferred; hotel median of 3–4★ and cheapest review ≥7; weather averages and poor days; visa verified flag; ease sub-scores; estimate total and `partial`; budget_status under/over/null; junk values ignored; all-empty inputs → nulls without crashing. Route — mocked agents: happy path 200 with summary; one agent raising → 200 with `missing` naming it; all failing → 502; multi-city body → 422; static visa present → `VisaAgent.run` not called; second identical call served from cache (agents called once); unauthenticated → 401 like other protected routes.
- [ ] **Step 2–4:** implement; agent instances as module-level lazy singletons like `discover.py`; `asyncio.gather` with per-piece `asyncio.wait_for`. Full backend suite passes.
- [ ] **Step 5: Commit** `feat(compare): per-destination comparison summary endpoint`.

### Task 2: Frontend compare helpers + table

**Files:**
- Create: `frontend/src/utils/compare.js` (+ `.test.js`), `frontend/src/components/CompareTable.jsx` (+ `.test.jsx`)
- Modify: `frontend/src/services/api.js` (`compareDestination(request)`)

**Interfaces — Produces:** `buildCompareRequests(form)`, `bestByRow(summaries)`, `CompareTable({ columns, onPlan, onRetry })` where `columns = [{ destination, status: 'loading'|'done'|'error', summary? , error? }]`.

- [ ] **Step 1: Failing tests:** requests share fields and differ only in destination, drop blanks and duplicates (case-insensitive); `bestByRow` picks lowest/highest per row, marks ties, skips rows with <2 values; table renders one column per destination, loading skeleton, error with Retry calling `onRetry(index)`, "Best" markers, "estimate"/"Verified"/"climate estimate" labels, "—" for nulls, Plan button calls `onPlan(index)`.
- [ ] **Step 2–4:** implement; responsive (table on ≥md, stacked cards below). Suite + lint.
- [ ] **Step 5: Commit** `feat(compare): comparison table and helpers`.

### Task 3: Search page "Compare" mode, docs

**Files:**
- Modify: `frontend/src/pages/SearchPage.jsx` (mode toggle `'known'|'discover'|'compare'`, compare form, parallel calls, Plan this trip → known mode prefilled + submit through the existing submit path), `CLAUDE.md`, `docs/API-Reference.md`, `docs/Frontend.md`
- [ ] **Step 1:** implement the mode, validation (≥2 distinct destinations, origin, dates, nationality), parallel calls with per-column state and Retry; preserve existing known/discover behaviour and the onboarding tour targets.
- [ ] **Step 2:** suite, lint, build, backend suite.
- [ ] **Step 3: Commit** `feat(compare): compare destinations from the Search page`.

End-to-end (controller, Chrome): compare 3 real destinations (e.g. Barcelona, Lisbon, Rome from Berlin), check numbers against the APIs' raw output, one destination outside the static tables, Retry after a forced failure, Plan this trip → full search with the same parameters, 375px layout, console clean.
