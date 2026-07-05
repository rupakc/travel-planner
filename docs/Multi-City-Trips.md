# Multi-City Trips

Travel Planner supports full multi-stop journeys — e.g. **New York → Paris → Rome → Barcelona → New York** — with every section of the results page covering every stop, in the exact order you entered them.

## Requesting a multi-city trip

The **"To" city is the final destination**; any added stops are intermediate cities visited **on the way** there. The `destinations` list is the full journey in travel order — stops first, final destination last — and `destination` is that final city:

```json
{
  "origin": "NYC",
  "destination": "Barcelona",
  "destinations": ["Paris", "Rome", "Barcelona"],
  "departure_date": "2026-09-10",
  "return_date": "2026-09-19",
  "destination_nights": [2, 3, null],
  "nationality": "American"
}
```

`destination_nights` is optional and aligned with `destinations`: set exact nights for any stop and leave the rest `null` — unspecified cities (typically the final destination) share the remaining days automatically.

On the Search page, enter your final destination in **To**, then add stops in the order you'll pass through them; each stop has an optional nights field.

## How days are allocated — `city_stays`

Cities with explicit `destination_nights` get exactly those days; the remaining days are split proportionally across the rest (`TravelSearchRequest.city_stays` in `backend/app/schemas/request.py`). With no nights specified, an *N*-city trip of *D* days uses `round(i × D / N)` boundaries so every date is covered exactly once regardless of how unevenly the division falls:

| City | Start | End (move-on day) | Nights |
|---|---|---|---|
| Paris | Sep 10 | Sep 13 | 3 |
| Rome | Sep 13 | Sep 16 | 3 |
| Barcelona | Sep 16 | Sep 19 | 3 |

Each stay's `end_date` is the day the traveler moves on — it equals the next city's `start_date`, and the last city's end is the return date.

## Flights — one search per leg

`flight_legs` decomposes the journey into one-way legs: origin → city₁ on the departure date, an inter-city hop on each move-on day, and last city → origin on the return date.

The flights pipeline (`backend/app/services/serp_flights.py::search_multi_city`) then:

1. Resolves every endpoint to IATA codes (`lookup_city_iata`, country-aware, up to 2 airport codes per city).
2. Fires **parallel one-way Google Flights searches** (SerpAPI, `type: "2"`) — one per leg, with a 20 s timeout and one retry per leg.
3. Tags every result with `leg_index`, `leg_from`, `leg_to`, `leg_date`, and `city`, keeps the top 5 per leg, and sorts legs into the user's journey order before returning.
4. Any leg SerpAPI cannot serve (timeout, zero results) is **AI-filled** with realistic estimates (`FlightsAgent._ai_fill_legs`, marked `source: "estimate"`), so no leg ever shows an empty row.

If SerpAPI is unavailable entirely, the AI agent produces all legs from a prompt that lists each leg explicitly and demands `leg_index` per result; `FlightsAgent._group_legs` regroups the flat output into ordered legs.

The UI renders one group per leg ("Leg 1 · NYC → Paris · Sep 10") and lets you pick **one flight per leg**, with a running total for the chosen combination.

## Every section covers every stop

Specialist prompts carry a **mandatory coverage** block with per-city quotas so no stop is skipped:

| Section | Per-city quota |
|---|---|
| Places to See | 4–6 (with per-city Serper search context) |
| Activities | ≥ 5 |
| Hotels | ≥ 3 |
| What's On (events) | 2–4 |
| Getting Around | intra-city options per city + inter-city hops (train/bus/flight) |

Every result carries a `city` field, rendered as a 📍 city chip on each card so items are easy to attribute at a glance.

## Journey order is guaranteed, twice

LLM output order is not trusted:

- **Backend** — flight legs are sorted by `leg_index`; weather days are sorted by *(stay order, date)*.
- **Frontend** — `orderSectionByCity` (`ResultsPage.jsx`) stable-sorts every city-tagged section list by the index of its city in your entered stop order, the moment results arrive.

The itinerary agent is instructed to visit cities **in exactly the order requested** — it never reorders your route.

## Weather per stay

`WeatherAgent` forecasts each city only for the dates you are actually there:

- Trips starting within 16 days use the **Open-Meteo** forecast per stay (free, no key needed).
- Further-out trips fall back to one LLM climate-estimate call covering all stays. The parser tolerates the model nesting output per city (`_flatten_days`), assigns each day's city **authoritatively from the stay date ranges**, dedupes hand-over dates, and sorts by stop order.

The UI groups day cards under a 📍 header per city, in journey order.

## Visas across countries

For multi-country routes the visa agent evaluates entry requirements for **every country** on the itinerary against your nationality, residence permits, and existing visas — not just the first stop.
