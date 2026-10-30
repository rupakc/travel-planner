# Sharing and Plans

The My Plan drawer, saved plans, export and public share links.

## My Plan drawer

Both the Results page and Chat page carry a plan drawer. Anything in the results can be selected into it:

- **Flights**: one per leg on multi-city trips (`selections.flights` is an array keyed by `leg_index`); a single round-trip selection otherwise
- **Hotel**, **activities**, **places to see**, **free walking tours** (`selections.walking_tours`, keyed by url), **events**, **SIM plan**, **tips**, **transport options** and **packing-list items**
- **Itinerary slots**: individual morning, afternoon or evening activities. A picked slot keeps its estimated start and end times, so My Plan, saved and shared plans show, for example, "Day 2 · Afternoon · 13:30–16:00".

Alongside the picks, a plan stores an `itinerary` snapshot and the itinerary overlays: `itinerary_layout` (drag-and-drop moves and removals), `itinerary_edits` (edited activity, location or cost) and `itinerary_notes`. See [Trip Planning Features](Trip-Planning-Features.md#itinerary).

The drawer shows a live cost total (`computePlanCost` sums flight legs, hotel nights, and per-person activity prices) and supports drag-and-drop from result cards.

Under the plan name, **Where the money goes** (`components/CostBreakdown.jsx`) breaks that total down by category — flights, hotel, activities, SIM — as a stacked bar plus one row per category with its amount and share, biggest first. The rows come from `computePlanCostBreakdown()` and `computePlanCost()` is defined as their sum, so the parts always add up to the total. Local transport only carries free-text fares, so it's left out and the drawer says so when transport options are selected.

## Export: calendar and print/PDF

The My Plan drawer (Results and Chat) and the saved-plan viewer have two export buttons (`components/PlanExport.jsx`):

- **Add to calendar** downloads an `.ics` file (`buildPlanIcs` in `frontend/src/utils/planExport.js`) that Google Calendar, Apple Calendar and Outlook can import. It holds one event per itinerary activity at its estimated start and end time (the same derived schedule the Results page shows, `scheduleDays` in `utils/schedule.js`, applied to the arranged itinerary), with your slot edits and notes. Picks from plans saved before timed itineraries fall back to fixed slot hours (morning 09:00–12:00, afternoon 13:00–17:00, evening 18:00–21:00). Flights are timed events from their departure time and duration (all-day when the time is unknown), the hotel is an all-day span from check-in to check-out, and selected local events cover their dates. Times are *floating* — they read as local time at the destination; a flight's description also gives its local arrival time and booking link. Event IDs come from the saved plan's id (or, for an unsaved plan, its route, dates and name), so two plans never overwrite each other's events and renaming a saved plan keeps its IDs. How a calendar app treats a re-import of the same file varies — some skip events they already have, some update them. Selected walking tours are not exported to the calendar, because tours carry no dates.
- **Print / PDF** opens a clean, printable page of the whole plan (`buildPlanPrintHtml` in `frontend/src/utils/planPrint.js`): cost breakdown, flights, hotel, day-by-day itinerary, activities, places, free walking tours, events, SIM, transport and tips. Print it or choose *Save as PDF* in the print dialog. All plan text is HTML-escaped, only `http(s)` booking links are kept, and the page carries a Content-Security-Policy that lets nothing run except its own print button.

When a saved plan is loaded into a drawer, export (and the cost breakdown, budget status and saving) use **that plan's** trip details and itinerary snapshot — never the itinerary of the search currently on screen, which may be a different trip.

## Saved plans

Plans are stored in the `plans` table through `/api/plans` (list, create, get, rename/update, delete; each user sees only their own). The drawer can save, rename, load and delete plans, and the current plan can be dragged onto the saved-plans drop zone. Saving records Taste Graph signals (see [Personalization](Personalization.md)).

A saved plan embeds a **snapshot of the generated itinerary** (days and estimated cost) alongside the selections, so reopening a plan months later shows the schedule as it was, including moves, edits and notes. Live verification evidence (`link_verified`, `link_checked`) is stripped from saved items, because it belongs to the live search. While a saved plan is loaded, itinerary editing is off until the user starts a new plan.

`PlanViewModal` shows a saved plan in full (flights per leg, hotel, the day-by-day itinerary and every selected item), each removable individually.

## Share links

**Share** calls `POST /api/plans/{id}/share`, which creates a random token (or returns the existing one), and copies `${origin}/share/<token>` to the clipboard. Anyone with the link can open it without logging in.

`GET /api/share/{token}` returns a sanitised plan: the name, timestamps, the selections and only these search fields: origin, destination(s), dates, interests, traveller counts and pace. Nationality, visas, residence permits, accessibility needs and budget are dropped.

`frontend/src/pages/SharePage.jsx` renders a read-only trip card:

- Route header (origin → stops in journey order) and dates
- Flights (each leg with airline, times and price), hotel and cost summary
- The **arranged day-by-day itinerary**, including edits and notes
- Activities, free walking tours, events, SIM plan, transport picks and tips

**Download as PNG** draws the whole share page onto a canvas sized to fit (one pass measures and wraps every line, a second pass paints it) and downloads a single image, with no external libraries or server round-trip.

`DELETE /api/plans/{id}/share` revokes a link, but no UI calls it yet; it is available through the API only.
