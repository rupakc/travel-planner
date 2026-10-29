# Best-Value Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Best-value package" card on the Results page that picks a sensible, cheap set of real results (flight, hotel, activities, free walking tour, free places, SIM) and adds them all to My Plan in one click, with Undo.

**Architecture:** Pure, rule-based derivation in the browser from the results already streamed (`results[agent]`): no new agent, no backend change. A pure module builds the package and merges it into selections; a presentational component renders it; ResultsPage computes it with `useMemo` once the search is done and applies it with one `setSelections` call.

**Tech Stack:** React 18, Tailwind 4, lucide-react icons, vitest + jsdom (no testing-library; `createRoot` + `act`).

**Spec:** Backlog item #26 in `Future_Improvements.md` ("Virtual Interlining and Package Deals" → "Best Value Package" card). Design decisions below were made by Claude (user delegated all choices); facts about data shapes come from `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/research-26.md`.

## Design (binding)

Options weighed: (a) a new LLM agent that composes a package — rejected: extra latency and cost, and it could recommend items that are not in the results; (b) deterministic rules over the streamed results — chosen: instant, testable, and every pick is a real listed item with a link.

Pick rules (all numbers coerced with `Number()` + `Number.isFinite`; anything non-finite is "unknown"; any `results[x]` that has an `error` key or no list is treated as empty):

- **Flight (single-city: `results.flights.results`; multi-city: each `results.flights.legs[i].results`, one pick per leg).** Candidates: `price_usd > 0`. If any candidate has `source !== 'estimate'`, drop the `'estimate'` ones. Let P = cheapest price. Pool = candidates with price ≤ P × 1.15. Sort pool by total stops asc (`(outbound?.stops ?? stops ?? 0) + (return?.stops ?? 0)`), then total duration asc (`outbound?.duration_minutes ?? duration_minutes` + `return?.duration_minutes`, unknown last), then price asc. Reason: `"Cheapest fare"` if its price equals P, else `"Fewer stops or shorter for $D more than the cheapest fare"` (D rounded).
- **Hotel (one only — `selections.hotel` holds a single hotel).** Candidates: `price_per_night_usd > 0`. Multi-city (`searchData.destinations?.length > 1`): restrict to hotels whose `city` equals `searchData.destinations[0]` when any match. Stars = `Math.round(star_rating)`. Pool = stars 3; if empty stars 4; if empty all candidates. Sort by `review_score` desc (unknown last), then nightly price asc. Reason: `"Mid-range (3★), best-reviewed in its class"` (use the actual star count; add the city name for multi-city).
- **Budget fit.** If `searchData.budget_usd > 0` and the package total is over budget, swap the hotel for the cheapest candidate (same city restriction) whose `review_score` is unknown or ≥ 7, if that is cheaper; reason becomes `"Cheaper stay to fit your budget"`. Do nothing else to fit the budget.
- **Activities.** Candidates: price known and 0 ≤ price ≤ 30. Sort by `similarity_score` desc (unknown last), then price asc. Up to 3 per city (`a.city ?? ''`), 6 overall. Reason: `"Free"` or `"$12"`, plus `" · matches your interests"` when `similarity_score >= 0.5`.
- **Free walking tour.** One per city (`top_pick` first, then highest `rating`), 3 overall. Reason: the tour's `price_note`.
- **Free places to see.** `admission_fee_usd` coerces to exactly 0; top 2 by `rating` per city, 4 overall. Reason: `"Free entry"`.
- **SIM.** Candidates from `results.sim.plans` with `price_usd > 0`. Trip days = whole days between departure and return + 1 (null when either date is missing). Prefer plans with `validity_days` unknown or ≥ trip days; cheapest of those, else cheapest overall. Reason: `"Covers your N-day trip"` or `"Cheapest plan"`.
- Not included: events, getting-around, tips, itinerary slots.
- **No package** (return `null`) unless it has a flight or a hotel.
- **Total** = `computePlanCost(pkg.selections, searchData)` and budget = `getBudgetStatus(total, searchData.budget_usd)`, so the card matches the My Plan drawer exactly. The card states "Flight prices are per person" (same convention as the flights section).

Applying:
- One `setSelections` merge (never repeated `handleSelect`: its toggles would *remove* already-picked items). `flight`, `hotel`, `sim` are replaced; multi-city `flights` replace only the legs the package covers; `activities`, `places_to_see`, `walking_tours` are unioned without duplicates (identity: `name`, `name`, `url`). Nothing else is touched.
- If the package will replace a different flight, hotel or SIM the user already picked, the card says so before they click ("Replaces your current hotel and SIM.").
- After applying: button shows "Added to My Plan" (disabled) plus **Undo**, which restores the exact selections from just before the click. The undo snapshot is cleared by a new search/remix.
- While a saved plan from the drawer is open (`loadedPlanSearchData` is non-null), applying is disabled with a short reason, because the open plan may be a different trip.
- Placement: Results page, directly after "Remix this trip", only when `isDone`; it recomputes when results change (filters re-stream sections).
- Analytics: `track('best_value_package_applied', 'results', { items })` and `track('best_value_package_undone', 'results', {})`.

Non-goals: ChatPage (chat is knowledge-only), saved-plan viewer, share page, backend changes, per-traveller multiplication of prices (the drawer doesn't do it either).

## Global Constraints

- No new dependencies. No backend changes.
- Frontend tests: `cd frontend && NODE_OPTIONS=--experimental-require-module npx vitest run`; lint gate: `npx eslint src/ --max-warnings 0`; build: `npm run build`.
- Pure-logic tests start with `// @vitest-environment node`; component tests with `// @vitest-environment jsdom` and use `createRoot` + `act` (see `frontend/src/components/WalkingToursSection.test.jsx`).
- Links rendered from results must go through the existing `safeUrl` helper (find it with `grep -rn "export function safeUrl\|safeUrl =" frontend/src`).
- Baseline before this work: 158 frontend tests, 333 backend tests, lint clean.

## Review Focus

1. Junk prices (`"varies"`, `null`, `"120"` as a string, `NaN`) — must never produce `NaN`/`$0` totals or pick an unknown-price activity as "Free".
2. Multi-city results (`results.flights.legs`, items with `city`) — one flight per leg, hotel from the first city, per-city caps.
3. Re-applying / partial overlap with existing picks — no duplicates, no removal of the user's own picks.
4. Sections that errored (`{ error: '...' }`) or are missing — package still builds from the rest, or is `null`.
5. Undo after the user changed something else in between — Undo restores the pre-click snapshot (documented, accepted trade-off), and is gone after a new search.

---

### Task 1: Package builder and merge (pure logic)

**Files:**
- Create: `frontend/src/utils/bestValuePackage.js`
- Test: `frontend/src/utils/bestValuePackage.test.js`

**Interfaces:**
- Consumes: `computePlanCost`, `getBudgetStatus`, `sameFlight` from `frontend/src/utils/planHelpers.js`.
- Produces:
  - `buildBestValuePackage(results, searchData) -> Package | null` where `Package = { items: Array<{ type: 'flight'|'flights'|'hotel'|'activities'|'walking_tours'|'places_to_see'|'sim', item: object, reason: string, city?: string }>, selections: { flight, flights, hotel, activities, walking_tours, places_to_see, sim }, total: number, budget: ReturnType<getBudgetStatus> }` (`selections` holds only these keys; unused ones are `null` / `[]`).
  - `applyPackage(selections, pkg) -> selections` (new object, input not mutated).
  - `isPackageApplied(selections, pkg) -> boolean`.
  - `packageConflicts(selections, pkg) -> string[]` — human labels among `'flight'`, `'hotel'`, `'SIM'` that applying would replace with a *different* item.

- [ ] **Step 1: Write failing tests.** One `describe` per rule in the Design section. Required cases (fixture factories `flight(over)`, `hotel(over)`, `activity(over)` etc.):
  - flight: picks the 1-stop $500 over the 2-stop $480 (within 15%); picks $400 2-stop over $600 direct (outside 15%), reason `'Cheapest fare'`; drops `source:'estimate'` when a real one exists; multi-city → one per `leg_index`, into `selections.flights`, `selections.flight === null`.
  - hotel: prefers 3★ with best `review_score`; falls back to 4★ then any; ignores `price_per_night_usd: 'varies'`; multi-city restricts to `destinations[0]` city.
  - budget fit: over budget → cheaper hotel with review ≥ 7 swapped in with reason `'Cheaper stay to fit your budget'`; a cheaper hotel rated 5 is not used.
  - activities: `price_usd: null` is never picked; `price_usd: 0` → reason starts `'Free'`; `'45'` excluded (> 30); cap 3 per city / 6 total.
  - walking tours: `top_pick` chosen per city; places: only `admission_fee_usd` 0 (including `'0'`).
  - sim: 30-day plan chosen over cheaper 7-day plan for a 10-day trip; cheapest overall when none cover.
  - `results.hotels = { error: 'x' }` → still returns a package with the flight; no flight and no hotel → `null`.
  - `total` equals `computePlanCost(pkg.selections, searchData)` and is finite.
  - `applyPackage`: keeps the user's existing activities, adds package ones without duplicates, replaces hotel, leaves `tips`/`itinerary_notes` untouched, does not mutate input; multi-city replaces only covered legs.
  - `isPackageApplied` true right after `applyPackage`, false after removing one item.
  - `packageConflicts`: `['hotel']` when a different hotel is selected; `[]` when nothing or the same hotel is selected.
- [ ] **Step 2: Run** `NODE_OPTIONS=--experimental-require-module npx vitest run src/utils/bestValuePackage.test.js` — expect FAIL (module missing).
- [ ] **Step 3: Implement** the four exports per the Design section.
- [ ] **Step 4: Run the file, then the whole frontend suite** — all pass (158 baseline + new).
- [ ] **Step 5: Commit** `feat(package): best-value package builder and merge helpers`.

### Task 2: BestValuePackage card component

**Files:**
- Create: `frontend/src/components/BestValuePackage.jsx`
- Test: `frontend/src/components/BestValuePackage.test.jsx`

**Interfaces:**
- Consumes: `Package`, `isPackageApplied`, `packageConflicts` from Task 1.
- Produces: `export default function BestValuePackage({ pkg, selections, onApply, onUndo, canUndo, disabledReason })` — renders nothing when `pkg` is null. `disabledReason` (string|null) disables the apply button and is shown under it.

- [ ] **Step 1: Write failing tests:** renders one row per `pkg.items` entry with the item name and reason; total formatted like the drawer (`$1,234`, no decimals) and the budget chip text from `pkg.budget.label`; "Flight prices are per person" note present when the package has a flight; clicking "Add all to My Plan" calls `onApply` once; when `isPackageApplied` is true the button reads "Added to My Plan" and is disabled and, with `canUndo`, an "Undo" button calls `onUndo`; conflict note `Replaces your current hotel.` appears when `packageConflicts` returns `['hotel']`; `disabledReason` disables the button and shows the text; item links use `safeUrl` (a `javascript:` URL renders no `href`); `pkg={null}` renders nothing.
- [ ] **Step 2: Run** the test file — FAIL.
- [ ] **Step 3: Implement.** Match RemixBar's card style (`bg-white rounded-xl shadow-md border border-gray-100 ring-1 ring-black/5 p-4`), a teal/emerald gradient icon tile, the section heading "Best-value package", subtitle "Our picks for the best price-to-quality balance from your results". Rows: icon per type (lucide), name (linked to `booking_url`/`url`/`info_url` when present, `target="_blank" rel="noopener noreferrer"`), city badge when present, price when known, reason in muted text. Responsive: rows stack at 375px with no horizontal scroll. Buttons have visible focus rings and `aria-live="polite"` on the status line.
- [ ] **Step 4: Run** test file and full suite; `npx eslint src/ --max-warnings 0`.
- [ ] **Step 5: Commit** `feat(package): best-value package card`.

### Task 3: Wire into ResultsPage, docs

**Files:**
- Modify: `frontend/src/pages/ResultsPage.jsx` (state near `const [selections` ~L3406; `runSearch` ~L3468; render after the `RemixBar` block ~L3998)
- Modify: `docs/Frontend.md` (ResultsPage "Additional UI elements"), `CLAUDE.md` (My Plan selections line: mention the best-value package)

**Interfaces:**
- Consumes: Task 1 and Task 2 exports; existing `isDone`, `results`, `searchData`, `selections`, `setSelections`, `loadedPlanSearchData`, `track`.

- [ ] **Step 1:** `const bestValue = useMemo(() => (isDone ? buildBestValuePackage(results, searchData) : null), [isDone, results, searchData])`; `const [packageUndo, setPackageUndo] = useState(null)`; clear `packageUndo` at the start of `runSearch`.
- [ ] **Step 2:** `handleApplyPackage`: snapshot current selections into `packageUndo`, `setSelections(s => applyPackage(s, bestValue))`, track. `handleUndoPackage`: restore snapshot, clear it, track.
- [ ] **Step 3:** Render `<BestValuePackage>` in a `mb-5` wrapper with `id="section-best_value"` directly after the RemixBar block, only when `isDone`. `disabledReason` when `loadedPlanSearchData` is non-null — first check how the user leaves that state (read the drawer's clear/new-plan handler) and word the reason to name that exact action.
- [ ] **Step 4:** Full frontend suite, lint, `npm run build` — all clean. Backend suite unaffected (`cd backend && python3 -m pytest -q`).
- [ ] **Step 5:** Docs updates (one short paragraph in Frontend.md; one phrase in CLAUDE.md).
- [ ] **Step 6: Commit** `feat(package): show best-value package on Results page`.

End-to-end (controller, in Chrome after Task 3): real single-city search and a multi-city search; apply → drawer shows the items and the same total as the card; Undo restores; re-apply has no duplicates; filters re-stream → card updates; open a saved plan → apply disabled; 375px width layout.
