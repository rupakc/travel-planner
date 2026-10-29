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

**Additional UI elements:**

- **Travel Confidence Score banner** — appears instantly at the top (Phase 0 static data). Shows an overall score (green / amber / red) with five sub-scores: visa ease, safety, English friendliness, cost vs budget, and tourist infrastructure. Expandable to show per-score notes.

- **Flight Price Advisor banner** — appears inside the Flights section once the pricing agent has run. Shows whether current prices are above or below typical, a booking recommendation, and an SVG sparkline of the historical price curve.

- **Badge / chip strip** — a row of chips below the page header linking to each section. Wraps across multiple rows as needed. Each chip shows the section status (loading / enhancing / done / error).

- **View switcher (Cards / Timeline)** — appears once the itinerary loads. Cards view shows each section as a card. Timeline view renders the itinerary as an interactive day grid: each day is a collapsible card with morning / afternoon / evening columns, a weather header, expandable activity cards, and a daily spend bar.

- **My Plan drawer** — a slide-in panel for selecting and saving trip components. Supports flight, hotel, activities, places, free walking tours (`selections.walking_tours`, keyed by url), SIM, tips, transport options, itinerary slots, and packing list. Shows a live cost total. Plans can be named, saved, and reloaded.

- **Editing the itinerary (Cards view)** — activities can be dragged (grip handle) to another day or time of day, or moved with each activity's **Move** menu, which is the keyboard and touch path (it lists every valid target, labels swaps, and offers "Remove from day"). Moving onto an occupied spot swaps the two activities; multi-city trips only allow moves within the same city. Removed activities show under "Removed" with Restore. Editing is off while a saved plan is open (click New in My Plan to edit again). The toolbar offers Undo (last 20 actions, in memory, cleared by a new search, loading a plan, or Save & clear) and Reset. Edits, notes and My Plan picks follow the activity. The layout is stored as `selections.itinerary_layout` (an overlay of positions keyed by original slot, with a fingerprint of the original itinerary), so it is saved with plans, and Timeline view, the map, exports (.ics, print), shared plans and the saved-plan viewer show the arranged itinerary. A layout whose fingerprint doesn't match the itinerary is ignored. When moves exist, the Itinerary Health Check shows "Checked against the original itinerary — your moves aren't re-checked."

- **Best-value package card** — shown after "Remix this trip" once the search finishes. Deterministic rules (`utils/bestValuePackage.js`, no extra agent) pick real listed items: a balanced flight per leg, one 3-4 star well-reviewed hotel, cheap/free activities, free walking tours and places, and a SIM plan covering the trip. The total uses the drawer's cost arithmetic and equals the drawer total when nothing else is selected (once applied on top of other picks the card also shows the full "My Plan total"). "Add all to My Plan" merges without duplicates in one update; Undo restores the selections from just before the click (cleared by a new search, remix, or loaded plan). Disabled while a saved plan is open (click New in My Plan).

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
