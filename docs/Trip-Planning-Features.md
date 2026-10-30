# Trip Planning Features

What a user can do in the app, and where each feature lives in the code. Chat, multi-city routing, personalization and plan sharing have their own pages: [Chat Assistant](Chat-Assistant.md), [Multi-City Trips](Multi-City-Trips.md), [Personalization](Personalization.md) and [Sharing and Plans](Sharing-and-Plans.md).

---

## App shell

- Routes (`frontend/src/App.jsx`): `/login`, `/share/:token` (public), `/change-password`, and the signed-in layout with `/` (Search and Results), `/chat`, `/preferences` and `/admin` (admins only). Any other path redirects to `/`.
- Search, Results and Chat stay mounted and are hidden with CSS, so a running search or chat stream survives switching tabs. Logging out clears all search state.
- A user who must change their password is sent to `/change-password` first.
- The footer credits the place data: "Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports".

---

## Search page

`frontend/src/pages/SearchPage.jsx` has three modes.

### "I know where I'm going"

- **Route.** From and To use the airport/place typeahead (`components/ui/AirportSearch.jsx` → `GET /api/airports/search`). "Add a stop on the way (multi-city)" adds up to 3 intermediate stops, each with optional nights (1–30). The To city is the final destination.
- **Trip.** Departure and return dates, budget in USD, nationality (`NationalitySearch` → `GET /api/nationalities/search`), residence permits and existing visas, interests.
- **Travellers** (`TravelerPanel`): adults 18–64, seniors 65+, children 5–17, infants 0–4, plus accessibility needs (wheelchair, visual, hearing, cognitive).
- **Discovery style** slider (serendipity 0–1): Famous classics, Balanced mix, Hidden gems.
- Submitting records a recent search and writes the fields back to Preferences. Saved preferences pre-fill the form on load; the budget category maps to USD as low 1000, medium 3000, high 8000.
- There is no pace control on the form. `pace` (relaxed / balanced / packed) is set by the "Slow it down" remix or through the API.

### "Surprise me 🎲"

Origin, nationality, dates, optional budget, interests and travellers. `POST /api/discover` returns 5 destinations. Each card shows city and country, a weather emoji and description, a visa badge (⚠️ when not confirmed by the static table), flight time, a rough cost range and why it matches. "Plan this trip →" fills in the known-destination form.

### "Compare ⚖️"

Seeded once from the known-destination form. Takes 2–3 destinations plus shared trip fields, and makes one `POST /api/compare/destination` call per destination in parallel, each column with its own loading and error state and a Retry that re-runs only that column. Responses from an earlier run are ignored. `components/CompareTable.jsx` shows cost estimate, flight, hotel, weather, visa and the Travel Ease grade, marking the best value in each row (stacked cards on phones). "Plan this trip" runs that exact request as a normal full search. Pure helpers are in `utils/compare.js`. Compare is single-city only (multi-city requests get 422).

### Recent searches

A collapsible strip above the known-destination form (`components/RecentSearches.jsx`). Its open/closed state is remembered per browser. Clicking a card loads the whole search (route, stops, dates, travellers, budget, visas) into the form; "Search again" re-runs it; each card can be deleted. Past dates are moved to start a week from today with the same trip length. The backend keeps the newest 8 per user and merges identical searches, ignoring interest order (`/api/recent-searches`).

### Onboarding tour

A first-run tooltip tour (`components/OnboardingTour.jsx`, `hooks/useFirstRunTour.js`, `utils/tour.js`). It opens once, 400 ms after load, for users with no recent searches, and only on the Search page in known-destination mode. Six steps: recent searches, route, interests, Preferences, the plan button and My Plan. A step whose element is not on screen is skipped. Each step is a focus-trapped dialog (Esc closes it). Completion is stored in `localStorage['tp_tour_done:<username>']`; "New here? Take a quick tour" replays it.

---

## Results page

`frontend/src/pages/ResultsPage.jsx`. Results stream through `services/api.js` → `workers/sseWorker.js`. The header shows progress (`completed/16`) and a status chip per agent (searching, enhancing, done, error) that links to its section. If the stream ends without `done`, the page reports that the connection was interrupted.

### Sections

In display order (`AGENT_ORDER`):

| Section | What it shows |
|---|---|
| **Flights** | Outbound and return legs, airline, stops, price and booking link; one group per leg on multi-city trips. Pricing-advisor banner with sparkline, Google Flights price-insights chip, opt-in fare calendar. Filters: max stops, max price, departure and arrival windows (`/api/flights/filtered`). A Layover button per connection opens a layover mini-plan (`POST /api/layover`). |
| **Weather Forecast** | Day cards; Open-Meteo data within 16 days, else an LLM estimate; grouped per stay on multi-city trips. |
| **Hotels** | Options across budget tiers. Filters: beds, max price per night, wifi, distance from centre, private washroom (`/api/hotels/filtered`). |
| **Activities** | Interest-matched activities with price and rating, and weather hints. Filters: interests, max price, availability dates, min rating (`/api/activities/filtered`). |
| **Places to See** | Landmarks and sights; Google Places data when `SERPER_KEY` is set. |
| **Free Walking Tours** | Crawled tours (GuruWalk, FreeTour.com, FreeWalkingTour.com, SANDEMANs NewEurope), top picks first per city, each linking to the provider's tour page (`components/WalkingToursSection.jsx`). |
| **What's On** | Festivals, concerts and markets during the trip; `~` marks a typical-season date. |
| **Visa** | Entry requirement, permitted stay, fee, documents and official link. |
| **SIM Cards** | Local SIMs and global eSIMs. |
| **Travel Tips** | Safety, culture, scams, money. |
| **Emergency Card** | Per-city police, ambulance and fire numbers, embassy, phrases and local laws; printable. |
| **Getting Around** | Local and inter-city transport options. |
| **Currency & Forex** | Exchange rates, where to exchange, card, cash and ATM advice. |
| **Itinerary** | Day-by-day plan with Cards and Timeline views (`components/TimelineView.jsx`) and a route map (`components/TripMap.jsx`, Leaflet with OpenStreetMap tiles). See [Itinerary](#itinerary). |
| **Trip Health Check** | The stress test: a score ring, issues with suggested fixes, and a re-check of the edited plan. |
| **Packing List** | Weather- and activity-aware checklist; checkbox state is kept in the browser, and items can be added to the plan. |

Above the sections:

- **Travel Ease banner** (`ConfidenceBanner`): the Phase 0 grade from the static destination scores.
- **Search panel** to edit and re-run the search.
- **Trip Remix** (`RemixBar`, `utils/remix.js`): five presets — A week later, Half the budget, Make it luxe, Slow it down (relaxed pace), Long weekend. Each re-plans the trip and shows a before/after banner.

On multi-city trips every list is stable-sorted into journey order (`utils/orderSectionByCity.js`).

### Verification badges

Each section header shows a chip from `data.verification` (`components/VerificationBadge.jsx`): **Verified**, **Partly verified**, **AI-generated**, **Check details**, or a spinning **Checking…** while hotel, activity and place links are still being checked. Clicking the chip opens a popover with the summary and each check (pass, fail or note, with its source link). Visa and emergency conflicts also show a banner in the section body, and items whose link was matched by name get a "Found online" tag. When the stream ends with a chip still pending, `utils/verification.js` resolves it. Saved plans drop the live link evidence. Chat does not show badges. The rules are in [Agent System](Agent-System.md#source-verification).

### Best-value package

Shown once the search has finished (`utils/bestValuePackage.js`, `components/BestValuePackage.jsx`). Deterministic rules, no extra agent: a balanced flight per leg, one well-reviewed 3–4 star hotel, cheap or free activities (2 per city, 4 in total), free walking tours (up to 3) and places (2 per city, 4 in total), and a SIM plan covering the trip. Every pick is a real listed item. "Add all to My Plan" merges them in one update without duplicates, and Undo restores the previous selections. Its total uses the drawer's cost arithmetic. It is disabled while a saved plan is open.

### Budget planner

Shown after the best-value package when the search has a budget (`utils/budgetPlanner.js`, `components/BudgetPlanner.jsx`). It runs entirely in the browser. The budget is split per person into Flights, Stay and Activities sliders ($10 steps) plus a read-only "Everything else". Defaults: the cheapest fare (summed per leg on multi-city), median nightly rate × nights, and 15% for activities; if those overshoot, activities shrink first, then stay. Under each slider it counts what fits ("6 of 12 hotels fit"). Once the user touches it, over-budget hotel and flight cards are dimmed and tagged, and "Show only what fits" can hide them (selected cards always stay visible). When fewer than 3 hotels fit, **Find cheaper hotels** runs the hotel filter with the stay share per night; this is the only action that calls the API. Reset restores the defaults; a new search or remix resets everything.

### Fare calendar and price insights

- **Fare calendar** (`components/FareCalendarStrip.jsx`, `utils/fareCalendar.js`). A "Fare calendar" button in the Flights header, offered only when `GET /health` reports `serpapi_configured`, the user is signed in and the trip is single-city. It loads `POST /api/flights/fare-calendar`: seven cells for departure dates ±3 days with the trip length kept the same, each with the cheapest live fare and its difference from the chosen dates; the cheapest is highlighted. Clicking another date asks for confirmation, then runs a new search with both dates shifted.
- **Price insights.** When live fares come with Google's verdict, a chip reads, for example, "Fares are low right now · typical $420–$610" (green, grey or amber for low, typical or high). This is Google's data, not an AI estimate.
- **Pricing advisor.** The deferred agent's banner: whether prices look high or low for the route, when to book, and a sparkline.

---

## Itinerary

`components/ItinerarySection.jsx`, with helpers in `utils/`.

- **Drag-and-drop.** Activities can be dragged (grip handle) to another day or time of day. The drag uses a custom MIME type so the plan drawer never mistakes it for a plan drop. Each activity also has a **Move** menu for keyboard and touch users, listing every valid target. Moving onto an occupied slot swaps the two; on multi-city trips moves stay within the same city. Removed activities appear under "Removed" with Restore. The toolbar has Undo (last 20 actions) and Reset, and empty slots show "Free time".
- **Layout overlay.** Moves are not written into the itinerary. `utils/itineraryLayout.js` stores an overlay keyed by each activity's original slot (`"<day>-<time_of_day>"`) and fingerprinted to the itinerary, saved as `selections.itinerary_layout`. Timeline view, the map, exports, shared plans and the saved-plan viewer all show the arranged itinerary. An overlay whose fingerprint does not match is ignored.
- **Timed schedule.** `utils/schedule.js` estimates start and end times for each activity from its slot (anchors 09:00, 13:30, 18:30), its `duration_hours` and the travel time from the previous stop (walking up to 1.5 km, else transit, from the slots' coordinates; a 20-minute buffer without them). Times are always derived, never stored, and the UI says they are estimates. A day that starts activities more than 45 minutes late or runs past 23:00 gets a "Tight schedule" note. Activities picked into My Plan keep their scheduled times ("Day 2 · Afternoon · 13:30–16:00").
- **Edits and notes.** A slot's activity, location and cost can be edited (`selections.itinerary_edits`), and notes added (`selections.itinerary_notes`). Editing is off, with the reason shown, while a saved plan is loaded.
- **Health check.** The stress-test agent audits the generated itinerary. After the user rearranges or edits it, **Re-check my edited plan** sends the arranged itinerary with edits and times, plus current flights, visa and weather (`utils/stressTestPayload.js`), to `POST /api/stress-test`. The result replaces the findings on screen; a later change shows "Your plan changed since this check", and errors keep the previous findings.

---

## My Plan drawer

On both Results (`MyPlanDrawer`) and Chat (`ChatPlanDrawer`). Users pick flights (one per leg on multi-city trips), a hotel, activities, places, walking tours, events, a SIM plan, tips, transport options, packing-list items and itinerary slots. The drawer shows a cost breakdown, exports to calendar and print/PDF, and saves, loads and shares plans. Details: [Sharing and Plans](Sharing-and-Plans.md).

---

## Chat, Preferences, Admin and feedback

- **Chat**: see [Chat Assistant](Chat-Assistant.md).
- **Preferences** (`pages/PreferencesPage.jsx`): Travel Budget, Identity (nationality, current residence, used as the default departure city), Documents (permits, visas), Travel Style (interests, travellers, accessibility), and a Taste Graph card with Reset. Bound two ways to the Search form; see [Personalization](Personalization.md).
- **Admin** (`pages/AdminPage.jsx`, admins only): a Users tab to create users with a temporary password (at least 8 characters; they must change it on first login), list them, deactivate, reactivate and reset passwords; and a Feedback tab, filterable by page, category and minimum rating.
- **Feedback widget** (`components/FeedbackWidget.jsx`): on every signed-in page. 1–5 stars, a category (bug, feature request, general, praise) and an optional message up to 500 characters, sent to `POST /api/feedback`.
- **Rate limits**: when a limit is hit, the API's 429 message ("Too many requests — please wait N seconds and try again.") is shown as-is (`utils/httpError.js`). Defaults per 10 minutes: 10 searches, 30 chat messages, 30 compare calls, 10 discover calls, 60 single-agent calls.
