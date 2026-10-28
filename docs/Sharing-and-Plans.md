# My Plan, Saved Plans & Sharing

## My Plan drawer

Both the Results page and Chat page carry a plan drawer. Anything in the results can be selected into it:

- **Flights** — one per leg on multi-city trips (`selections.flights` is an array keyed by `leg_index`); a single round-trip selection otherwise
- **Hotel**, **activities**, **places to see**, **events**, **SIM plan**, **tips**, **transport options**
- **Itinerary slots** — individual morning/afternoon/evening blocks

The drawer shows a live cost total (`computePlanCost` sums flight legs, hotel nights, and per-person activity prices) and supports drag-and-drop from result cards.

Under the plan name, **Where the money goes** breaks that total down by category — flights, hotel, activities, SIM — as a stacked bar plus one row per category with its amount and share, biggest first. The rows come from `computePlanCostBreakdown()` and `computePlanCost()` is defined as their sum, so the parts always add up to the total. Local transport only carries free-text fares, so it's left out and the drawer says so when transport options are selected.

## Export: calendar and print/PDF

The My Plan drawer (Results and Chat) and the saved-plan viewer have two export buttons:

- **Add to calendar** downloads an `.ics` file (`buildPlanIcs` in `frontend/src/utils/planExport.js`) that Google Calendar, Apple Calendar and Outlook can import. It holds one event per itinerary slot (morning 09:00–12:00, afternoon 13:00–17:00, evening 18:00–21:00, or the slot's own duration), with your slot edits and notes. Flights are timed events from their departure time and duration (all-day when the time is unknown), the hotel is an all-day span from check-in to check-out, and selected local events cover their dates. Times are *floating* — they read as local time at the destination; a flight's description also gives its local arrival time and booking link. Event IDs come from the saved plan's id (or, for an unsaved plan, its route, dates and name), so two plans never overwrite each other's events and renaming a saved plan keeps its IDs. How a calendar app treats a re-import of the same file varies — some skip events they already have, some update them.
- **Print / PDF** opens a clean, printable page of the whole plan (`buildPlanPrintHtml` in `frontend/src/utils/planPrint.js`): cost breakdown, flights, hotel, day-by-day itinerary, activities, places, events, SIM, transport and tips. Print it or choose *Save as PDF* in the print dialog. All plan text is HTML-escaped, only `http(s)` booking links are kept, and the page carries a Content-Security-Policy that lets nothing run except its own print button.

When a saved plan is loaded into a drawer, export (and the cost breakdown, budget status and saving) use **that plan's** trip details and itinerary snapshot — never the itinerary of the search currently on screen, which may be a different trip.

## Saved plans

Plans persist via `/api/plans` (SQLite). A saved plan embeds a **snapshot of the generated itinerary** (days + estimated cost) alongside the selections, so reopening a plan months later shows the schedule as it was — including any edits and notes you made to itinerary slots.

`PlanViewModal` renders a saved plan in full: per-leg flights, hotel, complete day-by-day itinerary, and every selected item, each removable individually.

## Shareable trip card

Every saved plan has a public share page (`SharePage.jsx`) — a polished trip card with:

- Route header (origin → stops in journey order) and dates
- Flights (each leg with airline, times, price), hotel, and cost summary
- The **full day-by-day itinerary** including your edits and notes
- Activities, events, SIM plan, transport picks, and tips

### Download as PNG

The **Download as PNG** button renders the *entire* share page — every section, not just the header — onto a dynamically-sized canvas (two-pass renderer: a measuring pass wraps every line at the card width and computes the exact height, then the paint pass draws text, section dividers, and the gradient background). Output is a single self-contained image (e.g. 1080 × ~2600 px) ready for messaging apps — no external libraries, no server round-trip.
