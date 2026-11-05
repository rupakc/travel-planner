# Trip Planning Features

What a user can do in the app, and where each feature lives in the code. Chat, multi-city routing, personalization and plan sharing have their own pages: [Chat Assistant](Chat-Assistant.md), [Multi-City Trips](Multi-City-Trips.md), [Personalization](Personalization.md) and [Sharing and Plans](Sharing-and-Plans.md).

---

## App shell

- Routes (`frontend/src/App.jsx`): `/login`, `/share/:token` (public), `/change-password`, and the signed-in layout with `/` (Search and Results), `/chat`, `/alerts`, `/preferences` and `/admin` (admins only). Any other path redirects to `/`.
- Search, Results and Chat stay mounted and are hidden with CSS, so a running search or chat stream survives switching tabs. Logging out clears all search state.
- A user who must change their password is sent to `/change-password` first.
- The header has a notification bell for fare and price alerts (see [Fare watch and price alerts](#fare-watch-and-price-alerts) and [Price watch](#price-watch-hotels-activities-and-trips)).
- The footer credits the place data: "Place data © GeoNames (CC BY 4.0) · Airport data: OurAirports".

---

## Search page

`frontend/src/pages/SearchPage.jsx` has four modes.

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

### "From a link ✨"

Plan a trip around a travel blog, a YouTube or TikTok video, a caption, a friend's message or screenshots.

- **Ways in.** The fourth mode tab. A hero hint: "Saw a great trip online? Paste the link". A deep link, `/?import=<url>`: Chat offers it when a message is just a link, or a link plus "plan", and it opens the flow and starts reading. Dropping a screenshot anywhere on the Search page opens the tab with it, under a full-page "Drop it to plan a trip" overlay.
- **Input** (`components/import/ImportPanel.jsx`). One box tells a link from text as you type ("Link — we'll read the page" / "Text — we'll pick out the places"). A drop zone takes up to 4 screenshots, with thumbnails and remove buttons; pasting an image works too, and wrong types, HEIC, unreadable files and files that are still over 5 MB once shrunk are explained. Screenshots are shrunk in the browser before the size check and the upload (long edge ≤ 1568 px, WebP or JPEG at quality 0.85), so a 10 MB retina screenshot is fine. There are three "Try an example" texts. Enter submits a link; Cmd/Ctrl+Enter submits text.
- **Progress.** Three staged steps: "Reading the page", then "Finding places", then "Putting them on the map". They are announced in an ARIA live region, and the time so far is shown against the typical time. Skeleton rows appear meanwhile. Cancel or Esc stops the request.
- **Errors offer the next step.** A blocked source (Instagram and the like), a paywall or an empty page gets "Paste the text" and "Drop a screenshot" buttons. Timeouts get "Try again". The rate-limit message is shown as the server sends it.
- **Review** (`components/import/ImportPreview.jsx`, `ImportMap.jsx`).
  - "Here's what we found": the trip title and summary, plus a source card (favicon, title, site, author, link).
  - A Leaflet map with numbered pins coloured by kind. They drop in once; reduced motion is respected. Approximate places are hollow pins, fanned out around their town, with an "approximate location" tooltip.
  - The route, with a nights stepper per stop and the option to leave a stop out.
  - Places grouped by stop. Each has a checkbox (with All / None per stop), a kind icon, inline rename, a "Change city" stop picker, a "day trip to …" label, "On the map ★ 4.6" or "Approximate", the source's quote highlighted, and the note.
  - "Couldn't place" places get a town field. "Place it" calls `POST /api/import/resolve-place`, which drops the place into its stop, or adds the town as a new stop while the route has fewer than 3. A stop picker remains as an alternative.
  - The usual trip fields, prefilled from Preferences: From, leaving date (default a month out; the return date follows the nights), nationality, budget and travellers.
  - Hotels start unticked, and at most 25 places are planned.
- **Planning.** "Plan this trip (N places)" runs a normal full search, with the reviewed places as `must_include` and the source as `import_source`. Interests from the source are added to the search but not saved to Preferences. Pure helpers are in `utils/linkImport.js`.
- **Results.** The banner counts what the itinerary on screen holds, after the traveller's moves and removals. When the stream ends without an itinerary, the browser's fallback itinerary gives each day its city and places the link places the same way the server does (`utils/mustInclude.js`). When the itinerary fails, the banner says so and points to Activities instead of spinning. A dismissible banner says "Planned around 11 places from *48 hours in Lisbon* — all 11 are in your itinerary", or "10 of 11 … 1 didn't fit: show". Imported activity cards and itinerary rows carry an amber "From your link" chip; tapping it shows the quote and how the place was checked. Places that did not get a slot are listed as "Also from your link" under their day. Trip map pins from the link have an amber ring. The My Plan drawer and the share page show "Inspired by …", and saved plans from a link have a link icon. Print and calendar exports carry the credit and the tags.
- **Analytics.** `import_started` (kind), `import_preview_shown` (place_count), `import_planned`, `import_failed` (code) and `import_from_chat`.

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

## Fare watch and price alerts

A traveller can watch a trip's live fare and be told when it's worth acting on. Offered when `GET /health` reports `fare_watch_available` (SerpAPI configured and `FARE_WATCH_ENABLED`), for signed-in users and single-destination trips departing after today.

- **Watch this fare** (`components/alerts/WatchFareButton.jsx`, `WatchDialog.jsx`): from the Flights header, the fare calendar ("Watch these dates", with nearby dates pre-ticked), the selected flight in My Plan (Results and Chat), saved-plan cards and the saved-plan viewer. A watched trip reads "Watching · $412" and opens its watch. The dialog shows today's price on Google's typical range and offers "Tell me when the price drops" (default) or "…when it's below $___" (pre-filled with the low end of the typical range), "Include nearby dates (±3 days)", and "Also email me" (hidden without SMTP, disabled with a link to Preferences when the account has no email). Creating a watch takes today's price as the baseline; the first time, the confirmation offers browser alerts (never asked on page load).
- **Checks** (`backend/app/services/fare_watch.py`): a scheduler started with the backend re-checks each active watch every `FARE_WATCH_INTERVAL_HOURS` (12 h ±10 %) within a daily SerpAPI budget; one check is 1 call (exact dates) or up to 7 (±3 days), cached fares are free. Prices are totals for the trip's travellers. A watch ends when its departure day arrives (`watch_expired` notice), and three failed checks in a row put it on hold (`watch_error` notice with Retry).
- **When we tell you** (`evaluate`, one notification per check at most, highest first):
  1. *Below your target*: the price is at or under the target.
  2. *Price drop* (default mode): at least max($15, 5 %) below the reference (see below).
  3. *Low price*: a new lowest for the trip's own dates that Google rates "low" (default mode).
  4. *Cheaper nearby date* (±3 days): a departure at least max($25, 8 %) cheaper than the chosen dates, same trip length (in target mode only when it also beats the target).
- **References and re-arming**: the trip's own dates (rules 1–3) and the nearby dates (rule 4) each keep their own reference, so an alert about a nearby date never raises the bar for the trip's own dates. A signal's first alert is measured from the price when watching started; if that price was already under the target, or Google already rated it "low", the confirmation says so ("Already below your target — we'll tell you if it drops further") and the first alert needs a full max($15, 5 %) drop below it. After that, every repeat needs a further drop of max($15, 5 %) below that signal's last alerted price, unless the signal **re-armed**: in drop mode, once the price climbs back at least max($15, 5 %) above the last alert, the highest price since then becomes the reference (alert at $400, a week at $600, then $450: "dropped to $450 (−$150)"); in target mode, once the price is back above the target by max($15, 5 %), going under the target again alerts. So $1-a-day drifts never alert daily, and a real fall after a rebound is never missed.
- **Never spammy**: no alert on the first check (that's the baseline) and never for a rise above where watching started; at most one alert per watch per 24 h (across both signals) unless the price is at least 5 % below the latest alert. Rises are still recorded in the history.
- **Alerts page** (`pages/AlertsPage.jsx`, `components/alerts/WatchCard.jsx`): a card per watch with the route, dates and travellers, the current price, the change since watching, lowest seen, Google's verdict, a price sparkline with the target as a dashed line, and last/next check. Actions: Re-plan with this fare (runs the normal search with the traveller's preferences; flexible watches also offer the cheaper nearby departure), Book on Google Flights, Check now, Pause/Resume, Edit, and Delete (confirmed inline). Grouped Active / Past trips, with an empty state that points to search. `/alerts?watch=ID` scrolls to a watch; `&replan=1` (from emails) re-plans directly. Signed out, any such link goes through the login page (`/login?next=…`, same-site paths only) and returns to it after signing in. A watch on hold shows a plain-language reason (never the raw error).
- **Notifications** (`context/AlertsContext.jsx`, `components/alerts/NotificationBell.jsx`, `AlertToast.jsx`): the header bell shows the unread count and the latest 10 alerts ("Berlin → Lisbon dropped to $150 (−$70)"), each opening its watch and marking it read, with "Mark all as read". The unread count is polled every 60 s only while the tab is visible (and on focus). A new alert shows as one dismissible toast (a polite live region), or as a native browser notification when the window isn't focused and the traveller allowed it.
- **Email** (`backend/app/services/alert_email.py`, optional): when `SMTP_HOST` is set, the watch has email on and the account has an address (set on Preferences), fare alerts are also emailed: plain text plus inline-styled HTML with no remote images, old → new price, lowest seen, a text sparkline (▆▄█▁), "See flights" and "Re-plan with this fare" links to `APP_BASE_URL`, and a link that stops emails for that watch (it opens a confirmation page, so mail scanners that follow links can't turn emails off; mail clients' one-click unsubscribe, RFC 8058, works directly). Expiry and error notices stay in the app. The account email is not verified; changing it is signed-in only and rate-limited.
- **Analytics** (`track()`): `watch_created` (mode, flex, email), `watch_checked_now`, `alert_clicked` (kind), `watch_replanned`, `watch_booked`.

---

## Price watch: hotels, activities and trips

The fare-watch machinery also covers a hotel's price, an activity's price and a whole saved trip's price. Availability is the same (SerpAPI configured, signed-in user). The bell, toasts and optional email are shared, and the Alerts page gains tabs (All / Flights / Hotels / Activities / Trips).

- **Where the buttons are.** *Watch price* on a hotel card (Results and Chat), on the selected hotel in My Plan and in a chat plan; *Watch price* on an activity card and on picked activities in My Plan; *Watch whole trip* on saved-plan cards, in the saved-plan viewer and, once the plan is saved, in My Plan. A watched item reads "Watching · $398". The dialog works like the fare dialog ("Tell me when the price drops" or "…below $___", optional email), and the first look is the baseline, never an alert.
- **City names.** Watches name the city ("Lisbon"), even when the search stored an airport code ("LIS"): the buttons look the code up in the local airport data, and the server does the same as a safety net. On a multi-city trip an activity is watched in its own leg's city.
- **Hotels** (`price_sources/hotel.py`, `hotel_prices.py`): the hotel is matched by name and city to a property on Google Hotels (via SerpAPI) for the search's dates and travellers. The price is the total for the stay: all nights and all rooms (one room for up to 4 travellers, more beyond that; the dialog states the basis). "Not this one?" offers up to 3 other priced properties. Sold out for the dates is "unavailable", not a price.
- **Activities** (`price_sources/activity.py`, `activity_prices.py`): the price is the "from … per person" figure Google shows for the activity's GetYourGuide or Viator listing, times your travellers. It is read from Google results through SerpAPI; getyourguide.com and viator.com are never fetched or scraped. Only a specific listing is watched, never a category page, and it must carry every place / proper-noun word of the activity, so a generic "small group walking tour" can't match another city's tour. When nothing matches, up to 3 priced listings are suggested. The watch keeps the listing's own currency (a target must be typed in it) and only ever compares like with like; a check that can't find the listing, finds no price or finds another currency is "unavailable". Without a date the watch runs 180 days.
- **Trips** (`price_sources/trip.py`): one total for a saved plan's flight, hotel, activities and other priced parts, with a breakdown (each part marked Live or Estimate, and what its price is). The flight is Google's **cheapest fare on your dates** for the route, as a fare watch tracks it, not the specific flight you picked. At most 5 activities are priced live; the rest, non-USD listings, multi-city flights, the SIM plan and anything Google can't price are estimates. An alert says which part moved ("flights −$70, hotel −$42"). The watch works on a frozen copy of the plan, so deleting the plan doesn't stop it.
- **Honesty rules.** A price is either *observed* (a live look, with its source and link) or an *estimate* (the AI's price from your search). Estimates are labelled, frozen when the watch is created, count towards a trip's total but never move, and never trigger an alert. A watch needs at least one live component: if nothing live matches, it can't be created (`no_live_price`); the dialog shows the labelled estimate and the suggestions instead.
- **Thresholds.** A step per kind sets the drop needed for an alert, for a repeat alert and for re-arming after a rebound: fares and hotels max($15, 5 %), activities max(1 unit of the listing's currency, 5 %), whole trips max($25, 4 %) on the total.
- **Anti-spam** (same rules as fares): no alert on the baseline or for a rise; one notification per check; at most one per watch per 24 h unless the price is at least 5 % below the last alert; a repeat needs a further full-step drop unless the price rebounded first. Watching the same subject twice returns the existing watch (`already_watching`).
- **Checks and limits.** One scheduler checks fare and price watches every `FARE_WATCH_INTERVAL_HOURS` from **one** daily SerpAPI budget (the price pass runs alongside, so it never delays fare checks, and price checks reserve their worst case so they can't push the budget over), and `FARE_WATCH_MAX_ACTIVE_PER_USER` counts every kind together. A watch ends on check-in, the activity date or the departure (`watch_expired`); three failed, or three "unavailable", looks in a row put it on hold (`watch_error`, with Retry). Notification kinds: `hotel_drop`, `hotel_target`, `activity_drop`, `activity_target`, `trip_drop`, `trip_target`.
- **Alerts page**: a card per kind (`components/alerts/cards/`) with the current and lowest price, change since watching, sparkline, listing link, Check now, Pause/Resume, Edit and Delete; trip cards show the breakdown. `/alerts?kind=hotel&watch=ID` opens one watch.

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
- **Preferences** (`pages/PreferencesPage.jsx`): Travel Budget, Identity (nationality, current residence, used as the default departure city, and the email for fare alerts, saved on its own via `PUT /api/auth/email`), Documents (permits, visas), Travel Style (interests, travellers, accessibility), and a Taste Graph card with Reset. Bound two ways to the Search form; see [Personalization](Personalization.md).
- **Admin** (`pages/AdminPage.jsx`, admins only): a Users tab to create users with a temporary password (at least 8 characters; they must change it on first login), list them, deactivate, reactivate and reset passwords; and a Feedback tab, filterable by page, category and minimum rating.
- **Feedback widget** (`components/FeedbackWidget.jsx`): on every signed-in page. 1–5 stars, a category (bug, feature request, general, praise) and an optional message up to 500 characters, sent to `POST /api/feedback`.
- **Rate limits**: when a limit is hit, the API's 429 message ("Too many requests — please wait N seconds and try again.") is shown as-is (`utils/httpError.js`). Defaults per 10 minutes: 10 searches, 30 chat messages, 30 compare calls, 10 discover calls, 60 single-agent calls.
