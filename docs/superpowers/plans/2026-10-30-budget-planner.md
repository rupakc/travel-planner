# Budget Planner (Interactive Budget Slider) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A "Budget planner" panel on the Results page that splits the trip budget into Flights / Stay / Activities / Everything else with sliders, instantly shows which loaded options fit each share, and can fetch cheaper hotels when too few fit.

**Spec:** Backlog #16 (Future_Improvements.md). Facts: `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/research-16-18-9.md` (#16 section). Choices are Claude's (user delegated).

## Design (binding)

Options weighed: (a) slider drives `/api/*/filtered` (LLM re-run, 3–10 s each) — rejected as the primary mechanism: too slow for a slider and replaces the result lists; (b) **client-side caps over already-loaded results** — chosen, instant; the existing hotel filter endpoint is used only on demand ("Find cheaper hotels").

Model (pure util `frontend/src/utils/budgetPlanner.js`, unit-tested, `// @vitest-environment node`):
- Units: the same per-person convention as the My Plan drawer and best-value package (flight `price_usd` per person; hotel nightly × nights; activity `price_usd`). Total = `searchData.budget_usd` (editable in the panel; not saved back to the search).
- `defaultAllocation(searchData, results)` → `{ flights, stay, activities, other }` summing exactly to the budget (integers, remainder to `other`): flights = cheapest valid fare (min with multi-city legs summed), stay = median nightly of priced hotels × nights, activities = 15% of budget, other = rest; if those exceed the budget, scale flights/stay/activities proportionally so other ≥ 0. No budget → panel hidden.
- `reallocate(allocation, key, value, total)` → moving one category takes from / gives to `other` first; if `other` would go below 0, the change is clamped. Total stays constant.
- `fitResults(results, allocation, searchData)` → `{ hotels: {fits:Set(name), count, total}, flights: {fits:Set(identity), count, total}, activities: {picked:Set(name), spent}, nights }`: hotel fits when nightly × nights ≤ stay; flight fits when price ≤ flights (multi-city: per-leg fare ≤ flights share × leg's share of the cheapest total); activities: greedy pick by `similarity_score` desc (ties price asc) while cumulative price ≤ activities share; free ones always fit. Junk prices are "unknown" → never counted as fitting and never dimmed.
- Edge: nights from dates (min 1, default 7) like planHelpers.

UI (`frontend/src/components/BudgetPlanner.jsx` + test):
- Placed directly after the Best-value package card (only when `isDone` and budget > 0), collapsible (default expanded on desktop, collapsed below 640px).
- Editable total (number input) + stacked bar (Flights sky, Stay purple, Activities green, Everything else gray — same colours as CostBreakdown) + three labelled range sliders (step $10) with values and "per person" note; "Everything else" shown read-only with a hint "food, transport, extras".
- Under each slider: "6 of 12 hotels fit" / "4 of 9 flights fit" / "Fits 5 activities ($212)".
- Toggle "Show only what fits" (default off). Off: over-budget hotel/flight cards are dimmed (opacity) with a small "Over your stay budget" / "Over your flight budget" tag; on: they are hidden with a "N hidden — show all" row. Activities picked by the planner get a "Fits your budget" tag.
- When fewer than 3 hotels fit: button "Find cheaper hotels" → calls the existing `handleApplyHotelFilters({ max_price_per_night_usd: floor(stay / nights) })` path (existing loading state, badge, verification). 
- "Reset" restores `defaultAllocation`.
- Allocation state lives in ResultsPage, resets on new search/remix and when results for flights/hotels change (recompute default only if the user hasn't moved a slider).
- Best-value package: `buildBestValuePackage(results, searchData, { caps })` — when caps provided, hotel candidates limited to those that fit (fallback to current behaviour if none fit) and flight pool limited to fitting fares (fallback likewise); ResultsPage passes caps only when the user has touched the planner. Existing package tests must pass unchanged; add tests for caps.
- Accessibility: sliders are `<input type="range">` with `aria-valuetext` "$1,200 for stay"; changes announced politely ("Stay budget $1,200 — 5 of 12 hotels fit").
- Analytics: `track('budget_planner_changed', 'results', { key })` (debounced), `track('budget_planner_cheaper_hotels', 'results', {})`.
- Docs: Frontend.md paragraph; CLAUDE.md one line.

Non-goals: saving the allocation in plans, chat, multiplying by travellers, LLM calls from slider moves.

## Global Constraints
No new deps; frontend tests createRoot+act; vitest/eslint/build clean; backend untouched.

---
### Task 1: budgetPlanner util (+tests)
### Task 2: BudgetPlanner component (+tests)
### Task 3: ResultsPage wiring (caps into Hotels/Flights/Activities sections, package caps, cheaper-hotels, reset rules) + docs
