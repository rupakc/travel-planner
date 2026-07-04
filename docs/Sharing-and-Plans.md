# My Plan, Saved Plans & Sharing

## My Plan drawer

Both the Results page and Chat page carry a plan drawer. Anything in the results can be selected into it:

- **Flights** — one per leg on multi-city trips (`selections.flights` is an array keyed by `leg_index`); a single round-trip selection otherwise
- **Hotel**, **activities**, **places to see**, **events**, **SIM plan**, **tips**, **transport options**
- **Itinerary slots** — individual morning/afternoon/evening blocks

The drawer shows a live cost total (`computePlanCost` sums flight legs, hotel nights, and per-person activity prices) and supports drag-and-drop from result cards.

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
