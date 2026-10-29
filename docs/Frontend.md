# Frontend

The Travel Planner frontend is a React 18 single-page application built with Vite 6 and styled with Tailwind CSS 4.

---

## Project structure

```
frontend/src/
├── pages/
│   ├── SearchPage.jsx          — trip search form + "Surprise Me" discovery mode
│   ├── ResultsPage.jsx         — streaming results, 16 sections, My Plan drawer
│   ├── ChatPage.jsx            — conversational AI assistant + auto-planning
│   ├── PreferencesPage.jsx     — saved nationality, interests, budget
│   ├── LoginPage.jsx
│   └── ChangePasswordPage.jsx
├── components/
│   ├── ui/
│   │   ├── NavBar.jsx          — top navigation with active tab highlight
│   │   ├── AirportSearch.jsx   — typeahead airport/city input
│   │   ├── NationalitySearch.jsx
│   │   └── TagInput.jsx
│   ├── TimelineView.jsx        — itinerary timeline grid (day cards, morning/afternoon/evening)
│   ├── TripMap.jsx             — Leaflet map for itinerary activity stops
│   ├── PlanViewModal.jsx       — modal for viewing/editing a saved plan
│   ├── VerificationBadge.jsx   — source-verification chip + popover, conflict banner, Found-online tag
│   └── FeedbackWidget.jsx      — floating feedback button on all pages
├── context/
│   ├── AuthContext.jsx         — auth state, JWT token, user preferences sync
│   └── SearchDataContext.jsx   — search form state, streaming results, SSE worker
├── workers/
│   ├── sseWorker.js            — SSE parser for /api/search stream (off main thread)
│   └── chatWorker.js           — SSE parser for /api/chat stream
├── services/
│   └── api.js                  — Axios client + all API call functions
├── utils/
│   ├── planHelpers.js          — plan name generation, cost calculation, selection counting
│   ├── verification.js         — clear stale pending labels, strip link evidence from saved plans
│   └── analytics.js            — frontend event tracking
└── data/
    └── airports.js             — static airport/city data for typeahead
```

---

## Routing and tab persistence

React Router 7 handles client-side routing. Routes are defined in `App.jsx`.

| Path | Page | Protected |
|---|---|---|
| `/login` | LoginPage | No |
| `/change-password` | ChangePasswordPage | Yes |
| `/` | SearchPage / ResultsPage | Yes |
| `/chat` | ChatPage | Yes |
| `/preferences` | PreferencesPage | Yes |
| `/admin` | AdminPage | Yes (admin) |

**Important**: `SearchTab` (SearchPage + ResultsPage) and `ChatPage` are **always mounted** in the DOM, shown or hidden with `display: none / block`. This means:

- Navigating away from the Results page never loses your streaming results
- Navigating away from Chat never loses your conversation or interrupts a response in progress
- When you return to either tab, you land exactly where you left off

`PreferencesPage` and `AdminPage` are conditionally rendered (they reset cleanly on each visit, which is the desired behaviour).

---

## AuthContext

`AuthContext` (`src/context/AuthContext.jsx`) wraps the whole app and manages:

- Whether the user is logged in, their JWT token, username, and role
- Token storage in `localStorage` — restored on page reload
- Auto-logout on 401 responses
- Two-way preference sync: preferences are fetched on login; search form values are synced back to preferences on submit

```jsx
const { user, token, isAuthenticated, login, logout, preferences } = useAuth()
```

---

## SearchDataContext

`SearchDataContext` (`src/context/SearchDataContext.jsx`) manages shared state between the search form and the results page:

- Search form values (destination, dates, budget, nationality, interests)
- Whether there are current search results (`hasSearchResults`) — controls which tab is visible
- The active SSE Web Worker reference

---

## Web Worker SSE

Both the search stream and the chat stream are parsed off the main thread by Web Workers.

`sseWorker.js` opens a `fetch` POST to `/api/search`, reads the response body as a stream, and posts each parsed SSE event back to the main thread. The main thread handles only React state updates. This keeps the UI smooth even when large JSON payloads (activities, itinerary) arrive mid-stream.

The same pattern applies to `chatWorker.js` for `/api/chat`.

---

## Key pages

### SearchPage

Two modes controlled by a toggle at the top of the form:

**Known destination mode (default)**
Standard search form: destination (with airport typeahead), departure date, return date, nationality, interests, budget, and number of travellers. Pre-fills from saved preferences. On submit, calls the SSE search stream and switches to the results view.

**Discover / Surprise Me mode**
For users without a specific destination. Form collects origin, dates, nationality, budget, and interests. Calls `POST /api/discover`. Returns 5 destination cards, each showing estimated cost range, typical weather, visa status (with a "Verify" badge for unconfirmed entries), approximate flight time from origin, and the specific reasons this destination suits the user's interests. "Plan this trip" pre-fills the destination in the standard form and switches back to Known mode.

**Compare mode**
A third toggle, "Compare", seeded once from the known-destination form. Collects an origin, two or three destinations ("Add another" / remove), dates, nationality, budget, travellers and interests. Submitting is blocked with an inline message unless there are at least two different destinations (plus the usual required origin, departure date and nationality). One `POST /api/compare/destination` call per destination runs in parallel (`buildCompareRequests` in `utils/compare.js`); each column has its own loading/error state with Retry, which re-runs only that destination, and responses from an earlier run are ignored. A destination typed as free text and the same city picked from the dropdown (IATA code) are treated as different entries. Results render in `CompareTable` (best value per row marked; stacked cards on phones). "Plan this trip" on a column switches to Known mode with that exact request and submits it through the normal search path. Analytics: `compare_run` (`count`), `compare_plan_clicked` (`position`).

**First-run tour**
People new to the app — no search history yet — get a short tooltip tour of the Search page the first time they reach it (`components/OnboardingTour.jsx`; steps in `SEARCH_TOUR_STEPS` in `SearchPage.jsx`; when to show it in `hooks/useFirstRunTour.js`). In page order it covers recent searches, the route fields, interests, the Preferences tab (form ↔ preferences sync) and the Plan button, then ends on a centred card about My Plan and export. Steps point at elements by `data-tour` attribute; a step whose element isn't on screen when the tour opens (no recent searches, or the nav collapsed on a phone) is skipped.

It is a proper dialog for keyboard and screen-reader users: each step is a fresh dialog that receives focus (so its title and text are announced), Tab stays inside it, Esc closes it from anywhere, and focus returns afterwards. It only shows while the Search form itself is visible — SearchPage stays mounted behind Chat and the results — and navigating away mid-tour hides it without marking it done. Completion is remembered per user in `localStorage` (`tp_tour_done:<username>`); "New here? Take a quick tour" under the page subtitle replays it for anyone.

---

### ResultsPage

The main results view. Receives streaming events from `sseWorker.js` via `SearchDataContext` and renders sections as they arrive.

**16 result sections** (in display order):
1. Flights
2. Weather
3. Hotels
4. Activities
5. Places to See
6. Free Walking Tours
7. What's On (Events)
8. Visa
9. SIM Cards
10. Travel Tips
11. Safety & Emergency Card
12. Getting Around
13. Forex
14. Itinerary
15. Itinerary Health Check
16. Packing List

**Free Walking Tours** (`WalkingToursSection.jsx`) renders one card per tour with provider, rating, duration, price note and a short "why" for this traveller. Each card links to the original tour page (`safeUrl`, opens in a new tab). The chip is labelled "Walking Tours".

**Source verification labels** — each section header shows a chip from `data.verification` (`VerificationBadge.jsx`): Verified, Partly verified, AI-generated, Check details, or a spinning "Checking…" while hotel/activity/place links are still being looked up (`pending`). Clicking the chip opens a popover with the summary and each check (pass / fail / note, with its source link where there is one); counts appear only in the check details (e.g. "1 of the 5 checked were found online by name"). Visa and emergency conflicts also show a rose `VerificationConflictBanner` (`role="status"`) in the section body. Items whose link was matched by name show a small "Found online" tag. When the stream ends with a section still pending, `finalize()` clears `pending` (copying the results). Results from the Flights / Hotels / Activities filter panels carry their own final label. Saved plans strip `link_verified` / `link_checked` from their items (`utils/verification.js`), since that evidence belongs to the live search. Chat does not show these labels.

**Additional UI elements:**

- **Travel Confidence Score banner** — appears instantly at the top (Phase 0 static data). Shows an overall score (green / amber / red) with five sub-scores: visa ease, safety, English friendliness, cost vs budget, and tourist infrastructure. Expandable to show per-score notes.

- **Flight Price Advisor banner** — appears inside the Flights section once the pricing agent has run. Shows whether current prices are above or below typical, a booking recommendation, and an SVG sparkline of the historical price curve.

- **Badge / chip strip** — a row of chips below the page header linking to each section. Wraps across multiple rows as needed. Each chip shows the section status (loading / enhancing / done / error).

- **View switcher (Cards / Timeline)** — appears once the itinerary loads. Cards view shows each section as a card. Timeline view renders the itinerary as an interactive day grid: each day is a collapsible card with morning / afternoon / evening columns, a weather header, expandable activity cards, and a daily spend bar.

- **My Plan drawer** — a slide-in panel for selecting and saving trip components. Supports flight, hotel, activities, places, free walking tours (`selections.walking_tours`, keyed by url), SIM, tips, transport options, itinerary slots, and packing list. Shows a live cost total. Plans can be named, saved, and reloaded.

- **Editing the itinerary (Cards view)** — activities can be dragged (grip handle) to another day or time of day, or moved with each activity's **Move** menu, which is the keyboard and touch path (it lists every valid target, labels swaps, and offers "Remove from day"). Moving onto an occupied spot swaps the two activities; multi-city trips only allow moves within the same city. Removed activities show under "Removed" with Restore. Editing is off while a saved plan is open (click New in My Plan to edit again). The toolbar offers Undo (last 20 actions, in memory, cleared by a new search, loading a plan, or Save & clear) and Reset. Edits, notes and My Plan picks follow the activity. The layout is stored as `selections.itinerary_layout` (an overlay of positions keyed by original slot, with a fingerprint of the original itinerary), so it is saved with plans, and Timeline view, the map, exports (.ics, print), shared plans and the saved-plan viewer show the arranged itinerary. A layout whose fingerprint doesn't match the itinerary is ignored. When moves exist, the Itinerary Health Check shows "Checked against the original itinerary — your moves aren't re-checked."

- **Estimated times** — every itinerary activity shows an estimated start–end time and, between rows, the travel time from the previous stop (walk ≤ 1.5 km, else transit, from slot `lat`/`lng`; a 20-minute buffer when coordinates are missing). `scheduleDays` in `utils/schedule.js` derives them after `arrangeItinerary` (anchors 09:00 / 13:30 / 18:30, the slot's `duration_hours` or a default), so they follow every move; a day whose activities start > 45 min late or that runs past 23:00 gets a "Tight schedule" note. Timeline view, .ics export, print, shared plans, the saved-plan viewer and the Health Check re-check use the same times.

- **Re-checking the edited plan (Health Check)** — when the layout differs from the original, the Itinerary Health Check also offers **Re-check my edited plan**. It POSTs to `/api/stress-test` (`recheckStressTest` in `services/api.js`) with the current search request plus the arranged itinerary — your edits to activity / location / cost applied, removed activities left out — and the current flights, visa and weather results without their `verification` objects (`buildStressTestPayload` in `utils/stressTestPayload.js`; `return_date` normalised by `apiReturnDate`). While it runs the button shows "Re-checking…". The result replaces the findings on screen (it is held in separate `recheck` state with a fingerprint of the itinerary it checked; `results.stress_test` stays the original audit) and the note reads "Checked against your edited itinerary". Any later move or edit shows "Your plan changed since this check — re-check again" with the button. Errors (including 429) show the server's string `detail` or "Couldn't re-check — try again" and keep the previous findings. The re-check is cleared by a new search, loading a plan, Reset, or clearing My Plan, and is only shown while the layout differs from the original. Each run tracks `health_recheck_run`. Re-checks are manual only and not offered in chat.

- **Best-value package card** — shown after "Remix this trip" once the search finishes. Deterministic rules (`utils/bestValuePackage.js`, no extra agent) pick real listed items: a balanced flight per leg, one 3-4 star well-reviewed hotel, cheap/free activities, free walking tours and places, and a SIM plan covering the trip. The total uses the drawer's cost arithmetic and equals the drawer total when nothing else is selected (once applied on top of other picks the card also shows the full "My Plan total"). "Add all to My Plan" merges without duplicates in one update; Undo restores the selections from just before the click (cleared by a new search, remix, or loaded plan). Disabled while a saved plan is open (click New in My Plan).
- **Budget planner** — shown right after the best-value package card once the search finishes, when the search has a budget (`components/BudgetPlanner.jsx`, model in `utils/budgetPlanner.js`, client-side only). It splits the budget (editable in the panel, not saved back to the search; per-person units like the drawer) into Flights / Stay / Activities sliders ($10 steps) plus a read-only "Everything else"; moving a slider takes from or gives to "Everything else" and is clamped at $0 there. Defaults: cheapest fare (multi-city: per-leg cheapest summed) and median nightly × nights, both rounded up to the next $10 so the cheapest options always fit; 15% for activities, rounded to the nearest $10; "Everything else" takes the rest. If those defaults overshoot the budget, activities shrink first (down to $0), then stay (down to $0), snapped down to the $10 grid; flights shrink only when the cheapest fare alone is more than the budget. Stay is always checked as nightly × nights, while the My Plan drawer prefers a hotel's `total_price_usd` when it has one, so the two can differ slightly for the same hotel. Under each slider it counts what fits ("6 of 12 hotels fit", "Fits 5 activities ($212)"); multi-city fares are checked per leg against the flight share split in proportion to each leg's cheapest fare; unknown prices never fit and are never marked. Only once the user moves a slider or edits the total ("touched") are over-budget hotel/flight cards dimmed and tagged ("Over your stay budget" / "Over your flight budget"; only the card content is dimmed, the tag stays at full opacity), planner-picked activities tagged "Fits your budget", and the best-value package limited to fitting hotels/fares (falls back when none fit); "Show only what fits" hides over-budget cards behind an "N hidden — show all" row (selected cards always stay visible and undimmed). When fewer than 3 hotels fit, "Find cheaper hotels" runs the hotel filter with `max_price_per_night_usd` = stay ÷ nights. Reset restores the defaults; a new search or remix resets everything. Collapsed by default below 640px. Slider changes are announced politely about 500 ms after the slider settles; Reset and total edits are announced right away.

---

### ChatPage

A persistent conversational interface. Survives tab switches (the component stays mounted — see Routing above). Key features:

- **Streaming responses** — each token appears as it is generated
- **Session memory** — conversation history is maintained in React state and backed up to `localStorage` every time a message completes
- **Auto-planning** — when the message contains a trip-planning request, the chat agent triggers the full search pipeline and renders structured section cards inline
- **Interactive itinerary map** — when an itinerary is generated, a Leaflet map renders the destination city markers and place pins. Map focuses on the destination area, not the origin (no intercontinental zoom-out)
- **My Plan drawer** — same plan management as ResultsPage

---

### PreferencesPage

Saves the user's default nationality, interests, budget, and travel documents (residence permits, existing visas). These are synced two-ways: the Search form reads them on load, and the Search form writes back to them on submit.

---

## TripMap component

`TripMap.jsx` is a shared Leaflet map component. It takes `days` (from the itinerary) and renders:

- Numbered, color-coded markers for each activity stop
- A dashed teal polyline connecting the stops in visit order (nearest-neighbour routing within each day)
- Popup details for each stop (activity name, location, day, time of day)
- Automatic `fitBounds` on mount, centred on the activity area

Used by ResultsPage's Itinerary section. ChatPage has its own inline map (for city-level + place-pin rendering) but uses the same visual style (22px markers, teal dashed polyline, 300px height, same `fitBounds` padding).

---

## Vite dev proxy

In development, Vite proxies `/api/*` to `http://localhost:8001`. This mirrors the production nginx setup. Config in `vite.config.js`:

```js
server: {
  proxy: {
    '/api': { target: 'http://localhost:8001', changeOrigin: true }
  }
}
```

---

## API service layer

`src/services/api.js` is an Axios instance that:

- Reads the JWT token from `localStorage`
- Adds `Authorization: Bearer <token>` to all requests
- Exports typed functions for every API call: `discoverDestinations`, `searchFlightsFiltered`, `searchHotelsFiltered`, `searchActivitiesFiltered`, and others
- `streamSearch` creates a Web Worker and wires up the `onResult / onDone / onError` callbacks
