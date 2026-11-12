# Frontend

A React 18 single-page app built with Vite 6, React Router 6 (`react-router-dom` 6.28) and Tailwind CSS 3.4. Maps use Leaflet with `react-leaflet`, icons come from `lucide-react`, and HTTP goes through axios. `@tanstack/react-query` provides a `QueryClientProvider` in `main.jsx`. What the user sees is described in [Trip Planning Features](Trip-Planning-Features.md); this page covers how the code is organised.

---

## Project structure

```
frontend/src/
├── main.jsx                  QueryClientProvider, BrowserRouter, ThemeProvider, AuthProvider, i18n and telemetry start-up
├── App.jsx                   routes, auth guards, always-mounted tabs, footer
├── index.css                 Tailwind directives
├── pages/
│   ├── SearchPage.jsx        known / surprise-me / compare modes, recent searches, tour
│   ├── ResultsPage.jsx       streamed sections, planning tools, My Plan drawer (~4,300 lines)
│   ├── ChatPage.jsx          chat, TripPlanView, chat plan drawer
│   ├── PreferencesPage.jsx   preferences + Taste Graph card + fare-alert email
│   ├── AlertsPage.jsx        watched fares (fare watch and price alerts)
│   ├── TripsPage.jsx         Trips hub (journey): next trip, all trips, where next, countries
│   ├── TripPage.jsx          one trip: overview, prep, offline pack, today, expenses, journal, recap tabs
│   ├── PlayPage.jsx          game and bucket list (journey)
│   ├── YouPage.jsx           account, preferences and settings (journey)
│   ├── NearbyPage.jsx        Near me: places around the user's location
│   ├── AdminPage.jsx         users, feedback and Analytics tab (admins only)
│   ├── LoginPage.jsx
│   ├── ChangePasswordPage.jsx
│   └── SharePage.jsx         public read-only shared plan, PNG download
├── components/
│   ├── BestValuePackage, BudgetPlanner, CompareTable, CostBreakdown,
│   │   FareCalendarStrip (+ PriceInsightsChip), FeedbackWidget, ItinerarySection,
│   │   OnboardingTour, PlanExport, PlanViewModal, RecentSearches, TimelineView,
│   │   TripMap, VerificationBadge, WalkingToursSection, ConsentPrompt
│   ├── alerts/               WatchFareButton, WatchDialog, WatchCard, Sparkline,
│   │                         NotificationBell, AlertToast, AlertEmailField,
│   │                         LiveCheck ("Search the web now"), cards/
│   ├── alerts2/              price alerts 2.0 (see below): PriceStory, PriceChart, TargetSlider,
│   │                         DropMoment, SavingsTally, SavingsShareCard, DealHunterTrack,
│   │                         QuickWatchButton, WatchSuggestions, TripPricesCard, AlertPrefsPanel, ...
│   ├── admin/                TelemetrySummary (Analytics tab)
│   ├── trips/                trip hub and trip-screen pieces: TripCard, TripHeader, TripTabs, PhaseMenu,
│   │                         PrepChecklist, OfflinePack, TodayView, ExpenseLog, Journal, Recap,
│   │                         PassportStamp, BucketRing, JourneyTour, ...
│   ├── auth/                 SocialSignInButtons (Apple, Google, Facebook, GitHub)
│   └── ui/                   AirportSearch, NationalitySearch, NavBar, TagInput,
│                             TravelerPanel, AttributionFooter, LanguagePicker, ThemeToggle
├── context/
│   ├── AuthContext.jsx       token, user, preferences and two-way sync
│   ├── AlertsContext.jsx     unread count polling, toasts, watch lookups
│   └── SearchDataContext.jsx search form and results state
├── hooks/useFirstRunTour.js  when to show the onboarding tour
├── journey/                  paths.js (journey route matching), tripTabs.js
├── offline/                  registerSW, packStore (IndexedDB packs), outbox (queued writes), useOfflinePack, useOnline
├── i18n/                     i18next set-up, locales/<lang>/<ns>.json, format.js (see Internationalization)
├── telemetry/                web SDK: client, consent, autocapture, perf, routes (see Telemetry)
├── theme/                    ThemeContext, themeStorage, generated tokens.css (see Theming)
├── services/api.js           axios client and API helpers
├── utils/                    pure helpers (see below)
└── workers/
    ├── sseWorker.js          parses the /api/search stream
    └── chatWorker.js         parses the /api/chat stream
```

The offline service worker is `frontend/public/sw.js` (see [Deployment on GCP](Deployment-GCP.md#offline-pack-and-the-journey-flag)); `vite/swAssets.js` writes the `/sw-assets.json` list it precaches.

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
| `/nearby` | NearbyPage | Signed in |
| `/trips`, `/explore`, `/play`, `/you` | TripsPage, Search and Results, PlayPage, YouPage | Signed in, only with `features.journey` |
| `/trips/:id` (`/:tab`) | TripPage | Signed in, only with `features.journey` |
| `/alerts` | AlertsPage (`?watch=ID`, `&replan=1`) | Signed in |
| `/preferences` | PreferencesPage | Signed in |
| `/admin` | AdminPage | Admins (`RequireAdmin`) |
| anything else | redirect to `/` | |

Search/Results and Chat are **always mounted** and hidden with CSS, so navigating away never loses streaming results, a half-typed message or a response in progress. Preferences, Near me, Alerts and Admin mount on each visit (Near me's live results are dropped when you leave it). `SearchDataProvider` sits inside the signed-in `Layout`, so logging out discards all search state. A user flagged `requires_password_change` is redirected to `/change-password`. `AttributionFooter` renders the GeoNames and OurAirports credit under every page. Each route change sends a page-view analytics event, and the telemetry SDK records a screen view. `LoginPage` shows `SocialSignInButtons`, which ask `GET /api/auth/providers` (the endpoint does not exist yet): a `404`, an empty list or an unconfigured provider shows "coming soon" (OAuth itself arrives in Phase 1). `ConsentPrompt` shows the one-time telemetry choice where consent is required.

---

## State

- **AuthContext** keeps the JWT (`localStorage['tp_token']`), the user (`username`, `is_admin`, `requires_password_change`) and the saved preferences. It loads preferences after login and writes Search-form values back to them on submit (the two-way binding).
- **AlertsContext** (inside the signed-in `Layout`) polls `GET /api/notifications/unread-count` every 60 s while the tab is visible (stopped while hidden, refreshed on return and focus), turns a newly arrived alert into one toast or, when the window isn't focused and permission was granted, a native notification, and caches each trip's watch for the "Watch fare" buttons. Outside the provider `useAlerts()` is inert, so components keep rendering in isolation.
- **SearchDataContext** holds the search form, the streamed results and per-agent status, shared by SearchPage and ResultsPage.
- Plan selections, itinerary overlays and planner settings are local state in ResultsPage and ChatPage.
- Grounded live answers (Near me and "Search the web now") are component state only: never in context, browser storage or the React Query cache.

## Streaming workers

`sseWorker.js` POSTs to `/api/search`, reads the body as a stream, splits `data:` events, and posts each parsed event to the main thread, which only updates React state. If the stream closes without a `done` event it posts `__interrupted`. `chatWorker.js` does the same for `/api/chat`. Keeping the parsing off the main thread keeps the UI responsive while large payloads arrive.

## API layer

`services/api.js` is an axios instance that adds `Authorization: Bearer <token>`, plus helpers: `streamSearch` (spawns the worker), the filtered searches, `fetchFareCalendar`, `getSerpapiConfigured` (reads `/health` once per page load), `discoverDestinations`, the recent-search calls, `compareDestination` and `recheckStressTest`. `utils/httpError.js` turns error responses into messages, showing a string `detail` (such as the 429 rate-limit message) as-is.

## Price alerts 2.0

`components/alerts2/` is rendered only when `useAlertsV2` says so: `features.price_alerts_v2` from `/api/config` is true, or `features.alerts_api === 2` and `localStorage.tp_alerts2 = "1"` (`"0"` always turns it off). Against a backend without `features.alerts_api` the classic Alerts page renders and no v2 control appears. Each watch card gets a price story (inline-SVG chart, keyboard-scrubbable, typical range, target slider, verdict and advice translated from codes plus params), the Alerts page a savings tally with milestones and a shareable "I caught $X" card (Canvas 2D, Web Share API), the notification bell a drop moment card (count-up skipped under `prefers-reduced-motion`) and the preferences panel the digest, quiet-hour, cap and grouping controls. One-tap watch and the suggestions sheet appear on Results, Chat and Trip cards and are hidden when `features.live_prices` is false. The Deal-hunter track follows the account's `hide_game` setting. Strings live in the `priceStory`, `savings`, `quickWatch`, `watchSuggest`, `alertPrefs` and `alertsHub` namespaces, plus added keys in `alerts` and `game`. `AlertsContext` also surfaces a drop's `data.drop` and `data.game`.

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
