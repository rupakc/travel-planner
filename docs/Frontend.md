# Frontend

A React 18 single-page app built with Vite 6, React Router 6 (`react-router-dom` 6.28) and Tailwind CSS 3.4. Maps use Leaflet with `react-leaflet`, icons come from `lucide-react`, and HTTP goes through axios. `@tanstack/react-query` provides a `QueryClientProvider` in `main.jsx`. What the user sees is described in [Trip Planning Features](Trip-Planning-Features.md); this page covers how the code is organised.

---

## Project structure

```
frontend/src/
├── main.jsx                  QueryClientProvider, BrowserRouter, AuthProvider
├── App.jsx                   routes, auth guards, always-mounted tabs, footer
├── index.css                 Tailwind directives
├── pages/
│   ├── SearchPage.jsx        known / surprise-me / compare modes, recent searches, tour
│   ├── ResultsPage.jsx       streamed sections, planning tools, My Plan drawer (~4,300 lines)
│   ├── ChatPage.jsx          chat, TripPlanView, chat plan drawer
│   ├── PreferencesPage.jsx   preferences + Taste Graph card
│   ├── AdminPage.jsx         users and feedback (admins only)
│   ├── LoginPage.jsx
│   ├── ChangePasswordPage.jsx
│   └── SharePage.jsx         public read-only shared plan, PNG download
├── components/
│   ├── BestValuePackage, BudgetPlanner, CompareTable, CostBreakdown,
│   │   FareCalendarStrip (+ PriceInsightsChip), FeedbackWidget, ItinerarySection,
│   │   OnboardingTour, PlanExport, PlanViewModal, RecentSearches, TimelineView,
│   │   TripMap, VerificationBadge, WalkingToursSection
│   └── ui/                   AirportSearch, NationalitySearch, NavBar, TagInput,
│                             TravelerPanel, AttributionFooter
├── context/
│   ├── AuthContext.jsx       token, user, preferences and two-way sync
│   └── SearchDataContext.jsx search form and results state
├── hooks/useFirstRunTour.js  when to show the onboarding tour
├── services/api.js           axios client and API helpers
├── utils/                    pure helpers (see below)
└── workers/
    ├── sseWorker.js          parses the /api/search stream
    └── chatWorker.js         parses the /api/chat stream
```

Tests sit next to the code as `*.test.js(x)` (vitest + jsdom); see [Testing and CI](Testing-and-CI.md).

---

## Routing and always-mounted tabs

Routes in `App.jsx`:

| Path | Page | Access |
|---|---|---|
| `/login` | LoginPage | Public |
| `/share/:token` | SharePage | Public |
| `/change-password` | ChangePasswordPage | Signed in |
| `/` | SearchPage, then ResultsPage | Signed in |
| `/chat` | ChatPage | Signed in |
| `/preferences` | PreferencesPage | Signed in |
| `/admin` | AdminPage | Admins (`RequireAdmin`) |
| anything else | redirect to `/` | |

Search/Results and Chat are **always mounted** and hidden with CSS, so navigating away never loses streaming results, a half-typed message or a response in progress. Preferences and Admin mount on each visit. `SearchDataProvider` sits inside the signed-in `Layout`, so logging out discards all search state. A user flagged `requires_password_change` is redirected to `/change-password`. `AttributionFooter` renders the GeoNames and OurAirports credit under every page. Each route change sends a page-view analytics event.

---

## State

- **AuthContext** keeps the JWT (`localStorage['tp_token']`), the user (`username`, `is_admin`, `requires_password_change`) and the saved preferences. It loads preferences after login and writes Search-form values back to them on submit (the two-way binding).
- **SearchDataContext** holds the search form, the streamed results and per-agent status, shared by SearchPage and ResultsPage.
- Plan selections, itinerary overlays and planner settings are local state in ResultsPage and ChatPage.

## Streaming workers

`sseWorker.js` POSTs to `/api/search`, reads the body as a stream, splits `data:` events, and posts each parsed event to the main thread, which only updates React state. If the stream closes without a `done` event it posts `__interrupted`. `chatWorker.js` does the same for `/api/chat`. Keeping the parsing off the main thread keeps the UI responsive while large payloads arrive.

## API layer

`services/api.js` is an axios instance that adds `Authorization: Bearer <token>`, plus helpers: `streamSearch` (spawns the worker), the filtered searches, `fetchFareCalendar`, `getSerpapiConfigured` (reads `/health` once per page load), `discoverDestinations`, the recent-search calls, `compareDestination` and `recheckStressTest`. `utils/httpError.js` turns error responses into messages, showing a string `detail` (such as the 429 rate-limit message) as-is.

## Utilities

Pure, unit-tested helpers in `src/utils/`:

| Module | Purpose |
|---|---|
| `analytics.js` | Batches UI events and posts them to `/api/analytics/events` (every 5 s or 10 events) |
| `bestValuePackage.js` | Rule-based best-value picks |
| `budgetPlanner.js` | Budget split and fit checks |
| `chatHistory.js` | Text stand-ins for structured chat turns |
| `compare.js` | Compare-mode requests and table model |
| `fareCalendar.js` | Fare-calendar cells and date shifting |
| `geo.js` | Great-circle distance (`haversineKm`) |
| `httpError.js` | Error messages from API responses |
| `itineraryLayout.js` | Drag-and-drop overlay (`arrangeItinerary`, fingerprints) |
| `orderSectionByCity.js` | Stable sort of multi-city lists into journey order |
| `planExport.js` | `.ics` export |
| `planHelpers.js` | Plan cost, cost breakdown, names, counts |
| `planPrint.js` | Print/PDF page |
| `recentSearches.js` | Recent-search formatting and date roll-forward |
| `remix.js` | Trip Remix presets |
| `schedule.js` | Estimated start/end times (`scheduleDays`) |
| `stressTestPayload.js` | Payload for the health-check re-check |
| `tour.js` | Onboarding-tour completion flag |
| `verification.js` | Resolving pending badges, stripping link evidence from saved plans |

## Maps

`TripMap.jsx` renders the itinerary with Leaflet and OpenStreetMap tiles: numbered markers per activity stop, a dashed polyline in visit order, popups, and `fitBounds` on the activity area. The chat page draws its own map in the same style for city markers and place pins, and leaves the origin out of the bounds so the view does not zoom out across continents.

---

## Dev server and production build

- `npm run dev` starts Vite on port 5174. `vite.config.js` proxies `/api` and `/health` to `http://localhost:8001`.
- `npm run build` writes `dist/`. The container (`frontend/Dockerfile`) builds with node:20-alpine and serves `dist/` from nginx:alpine on port 8080. `nginx.conf.template` proxies `/api/` and `/health` to `BACKEND_URL`, with buffering off for SSE and a 120 s read timeout.
- The app uses no `VITE_*` environment variables.
