# Carbon Footprint

Voyager estimates the CO₂e (carbon dioxide equivalent) of a whole trip: flights, hotel nights, local transport, meals and some activities. The web app shows it as a card on the Results page and in the My Plan drawer (on the Results and Chat pages). The card has a breakdown bar, a diet picker, a "lower-carbon option" hint when a train could replace a short flight, and a "How we calculate" panel that lists every line with its method, the assumptions and the sources.

The work is done by `POST /api/carbon/trip` (`backend/app/services/carbon.py`). It is **pure computation**: no LLM and nothing stored. It reads a committed factor table and the airport coordinates already in the database. The one optional network read is the Voyager crawler's carbon data (see [Crawler data](#crawler-data)), only when the crawler is configured; without it, the same request always gets the same answer.

## Methods

Every line of the answer says how it was worked out:

| `method` | Meaning |
|---|---|
| `measured_tim` | The flight's figure from Google's [Travel Impact Model](Travel-Impact-Model.md), already on the flight result as `emissions`, times the number of travellers. |
| `factor` | A published factor times a quantity we know: great-circle km between airports, room-nights, km between itinerary stops. |
| `estimate` | A factor times a quantity we had to assume, such as km per day without itinerary coordinates, the length of a boat trip, or a basket of food. Always labelled. |

### Flights

- **TIM first.** When a leg carries `emissions` (TIM, `TIM_ENABLED`), that figure is used for the requested cabin (`by_class`), per passenger, times travellers. Connecting legs are covered too: TIM sums each flown segment when every segment has a flight number (see [Flight Emissions](Travel-Impact-Model.md)). A result from an older backend that has one `emissions` for the whole round trip is counted once.
- **DESNZ fallback.** Otherwise each hop (origin → each layover airport → destination) is the great-circle distance between the airports' coordinates times the DESNZ 2026 factor for its distance band and cabin, **with radiative forcing** (non-CO₂ effects of flying at altitude):

| Band | Distance | DESNZ rows used |
|---|---|---|
| Domestic | up to 500 km | Domestic, average passenger |
| Short-haul | 500–3,700 km | Short-haul economy or business (premium economy counts as economy, first as business) |
| Long-haul | over 3,700 km | Long-haul economy, premium economy, business or first |

  DESNZ publishes these for flights to or from the UK; we use them as distance-band factors for any route. No extra routing uplift is added to the great-circle distance. Note that TIM figures don't include non-CO₂ effects, so a TIM flight and a DESNZ flight of the same length differ.
- The cabin defaults to economy (`cabin` in the request).

### Stays

Room-nights × the DESNZ 2026 hotel-stay factor for the country (kg CO₂e per room per night). Rooms default to one per two travellers (`rooms` overrides). Multi-city trips split the nights per city (`destination_nights`, as the itinerary does) and use each city's country. A place without its own coordinates (Kyoto, Bali, Santorini) uses its resolved country, and its first airport for distances. A country DESNZ doesn't list gets the median of the listed countries, labelled `estimate`; with the crawler on, it gets the country's electricity grid intensity instead when the crawler has it (see [Crawler data](#crawler-data)). In a plan, stays count only once a hotel is picked; on the Results page they always count.

### Getting around

- **With an itinerary:** the straight-line distance between consecutive stops of each day (hops over 150 km are left to the inter-city lines), by the transport picked in My Plan (metro, tram, bus, taxi, car …; walking and bikes count as zero). Public transport is per passenger-km; taxis (4 seats) and cars (5 seats) are per vehicle-km.
- **Without coordinates:** 10 km a day, labelled `estimate`.
- **No transport picked** (or on the Results page): a mix of 40 % metro, 40 % bus and 20 % taxi.
- **Between cities** on a multi-city trip, a move with no picked flight goes by train (or the picked inter-city transport): the distance between the cities × 1.2 for the route.

### Food

A per-person day of food for the chosen diet, times days × travellers, from Our World in Data's kg CO₂e per kg of each product (Poore & Nemecek 2018). The daily baskets (grams of each product) are ours, set so the diets rank as published studies do:

| Diet | kg CO₂e per person per day |
|---|---|
| Lots of meat | 10.1 |
| Mixed (default) | 7.2 |
| Pescatarian | 5.3 |
| Vegetarian | 4.4 |
| Vegan | 2.9 |

Meals are counted in full, not as the difference from eating at home.

### Activities

Only transport-heavy activities are estimated, from the itinerary's slots plus any picked activities the itinerary doesn't mention (each distinct name once): boat trips and cruises (20 km by ferry), day trips and coach tours (100 km by coach) and jeep, safari, quad-bike, game or scenic drives (60 km by car). Keywords match whole words ("Rodeo Drive" or "the Ferry Building" is not a trip). A day trip or excursion whose slot has coordinates on a day with measured stops is left to the local-transport line, so it is not counted twice. Helicopter, seaplane and balloon flights are left out (no factor), and everything else is left out because there is no data. Each one is labelled `estimate`.

### Lower-carbon hint

For a flight whose rail distance (great-circle × 1.2) is under 700 km, between two airports in the same country or two European countries (not Ireland, Iceland, Cyprus or Malta; nor within Indonesia, the Philippines, New Zealand, the Maldives or Fiji), the answer adds a `lower_carbon` entry with the train's CO₂e (DESNZ national or international rail) and the saving. The way back joins the way out. It says a train *could* work: we don't check timetables, and a sea crossing inside a country (Barcelona–Palma) can still trigger it.

### Comparisons

`car_km` is the total divided by DESNZ's average car (unknown fuel, per km). `budget_share` is the per-person footprint as a share of a 2 t CO₂e yearly budget per person.

## The factor table

`backend/app/data/carbon_factors.json` is generated, never hand-edited:

```bash
python3 -I backend/scripts/build_carbon_factors.py \
    --desnz ghg-conversion-factors-2026-flat-format-revised.xlsx \
    --owid ghg-per-kg-poore.csv \
    --out backend/app/data/carbon_factors.json
```

Every value carries `value`, `unit` (always "kg CO₂e per …"), `source`, `year` and, for DESNZ, the publisher's `factor_id`. Our own choices (bands, diet baskets, default distances, the transport mix, activity rules) live under `assumptions` and the `voyager` source, so they are never mistaken for published figures. DESNZ publishes a new set every June: download the new flat file, update the URL and year in the script, and run it. `backend/tests/test_carbon.py` pins golden numbers, so a refresh that moves a value fails there first.

| Source | File | Licence |
|---|---|---|
| UK DESNZ, "Greenhouse gas reporting: conversion factors 2026", flat file (sheet "Factors by Category") | [ghg-conversion-factors-2026-flat-format-revised.xlsx](https://assets.publishing.service.gov.uk/media/6a6c9748862aaf18d9c62ac9/ghg-conversion-factors-2026-flat-format-revised.xlsx) | Open Government Licence v3.0 |
| Our World in Data, "Greenhouse gas emissions per kilogram of food product" (Poore & Nemecek 2018) | [ghg-per-kg-poore.csv](https://ourworldindata.org/grapher/ghg-per-kg-poore.csv?v=1&csvType=full&useColumnShortNames=true) | CC BY 4.0 |
| Google Travel Impact Model (flight figures already on results) | [travelimpactmodel.org](https://travelimpactmodel.org) | CC BY-SA 4.0 |

Attribution, shown in the card's "How we calculate" panel:

- "Contains public sector information licensed under the Open Government Licence v3.0"
- "Our World in Data, based on Poore & Nemecek (2018), CC BY 4.0"
- "Emissions estimates: Google Travel Impact Model, CC BY-SA 4.0" (when a TIM figure is used)

## Crawler data

The Voyager crawler also collects these files: `emission_factor` records from its `factor_table` adapter (DESNZ, EPA, OWID and others) and `grid_carbon_intensity` observations from OWID and Ember. When the crawler is configured (`CRAWLER_ENABLED`, see [Crawler Data](Crawler-Data.md)), `backend/app/services/carbon_live.py` reads two of its endpoints before the calculation and hands `compute` an overlay:

| Crawler read | Used for | Rule |
|---|---|---|
| `GET /v1/carbon/factors?source=od-desnz-ghg-factors` | Newer DESNZ factors | One probe (`limit=1`, newest year first). Only when the crawler's newest DESNZ year is **later** than the committed table's (2026), the rows of that year are read per category (flights, rail, bus, taxi, ferry, accommodation, average car). A newer row replaces the committed row with the same publisher label (the crawler's `activity` slug), the same unit and, for flights, the same gas basis (with radiative forcing). Hotel-stay rows match by country and, for a country the table has, by the same label too, so DESNZ's "UK (London)" row (which the crawler also files under GB) never replaces "Hotel stay / UK". A newer row may add a country the table lacks, but only its national row (`Hotel stay / <country>`) and only when it is that country's one row. Everything else (food, our assumptions) stays as committed. |
| `GET /v1/carbon/grid?country=<ISO2>&period=annual&basis=lifecycle` | Stays in a country with no hotel-stay factor (neither committed nor newer) | The newest `grid_ci:<ISO2>:annual:lifecycle` point: g CO₂e/kWh × **70 kWh-equivalent per room-night**, labelled `estimate` (assumption `hotel_grid`). The 70 is ours, not published: it is the DESNZ median hotel factor (33.5 kg) at a world-average grid of about 480 g/kWh, so a clean grid (Iceland, Norway) gives a low figure and a coal-heavy one a high figure. A country DESNZ lists keeps its hotel factor, which covers more than electricity. |

Rules:

- **Fallback is exact.** Crawler off, down, slow (4 s budget for all the reads, each read 1.5 s, circuit breaker as for every crawler read) or with nothing usable: the answer is byte for byte the committed-table answer. `backend/tests/test_carbon_crawler.py` checks exactly that.
- **Licences.** Only open or API-terms rows without a conflict are used; share-alike rows are never mixed in.
- **Sources on every number.** A line worked out from a crawler number carries `crawler_source` (`name`, `url`, `as_of`, `licence`, `attribution`, `licence_url`, `source_id`, `year`). The answer lists the crawler sources in `sources` (ids `crawler_desnz_<year>`, `crawler_grid_<source>_<country>`, one per country so each grid line shows its own year and as-of) and again in `crawler_sources`, and adds the assumption `factors_newer` when newer DESNZ factors were used. These keys appear only when a crawler number was used.
- **Cache.** The carbon reads are cached for 6 hours (factors change once a year).
- **Clients.** The web card shows "Includes newer official data from the Voyager crawler" with each source line (name, link, as-of date, attribution) when `crawler_sources` is present, and each line's source in "How we calculate". A response without these fields (an older backend, or the crawler off) renders as before.

## API

`POST /api/carbon/trip`. Anonymous calls are fine. It has its own `carbon` rate bucket (`RATE_LIMIT_CARBON`, 120 per 10 minutes per user or IP) and a 512 KB body cap (`413`). It answers `404` when `CARBON_FOOTPRINT_ENABLED=false`; clients check `features.carbon` in `/api/config` before calling.

Send exactly one of `selections` or `results` (`422` otherwise):

```json
{
  "search": {"origin": "London", "destination": "Paris", "departure_date": "2026-05-01",
             "return_date": "2026-05-05", "num_travelers": 2},
  "selections": {
    "flight": {"outbound": {"origin": "LHR", "destination": "CDG", "stops": 0}},
    "hotel": {"name": "Hôtel X", "country_code": "FR"},
    "getting_around": [{"type": "metro", "scope": "intra_city"}],
    "activities": [{"name": "Seine cruise"}]
  },
  "itinerary": {"days": [{"slots": [{"activity": "Louvre", "lat": 48.86, "lng": 2.34}]}]},
  "diet": "mixed",
  "cabin": "economy",
  "rooms": 1
}
```

- `selections`: My Plan's `flight`, `flights` (multi-city, with `leg_index`), `hotel`, `getting_around`, `activities`.
- `results`: a search summary, `{"flights": <flights section>, "hotels": <hotels section>, "itinerary": <itinerary section>}`. The lowest-priced flight (per leg on multi-city trips; a missing or 0 price sorts last) is used, and stays always count.
- `diet`: `mixed` (default), `meat_heavy`, `pescatarian`, `vegetarian` or `vegan`. `cabin`: `economy` (default), `premium_economy`, `business` or `first`. `rooms`: 1–20.

The answer:

```json
{
  "total_kg": 245.1, "per_person_kg": 122.5, "travellers": 2, "nights": 4,
  "diet": "mixed", "cabin": "economy",
  "categories": [{"key": "flights", "kg": 159.4, "share": 0.6504, "included": true}, …],
  "lines": [{"category": "flights", "kind": "flight_factor", "label": "Flight LHR–CDG (348 km)",
             "kg": 159.4, "method": "factor", "source": "desnz_2026",
             "params": {"route": "LHR–CDG", "km": 348, "cabin": "economy", …}}, …],
  "comparisons": {"car_km": 1477, "annual_budget_kg": 2000, "budget_share": 0.0613},
  "lower_carbon": [{"route": "LHR–CDG", "from": "LHR", "to": "CDG", "rail_km": 417, "legs": 1,
                    "flight_kg": 159.4, "rail_kg": 9.5, "saving_kg": 149.9, "factor": "rail_international"}],
  "sources": [{"id": "desnz_2026", "name": "…", "url": "…", "licence": "…", "attribution": "…"}, …],
  "assumptions": [{"code": "rooms_default", "text": "1 room(s): one per two travellers.", "params": {"rooms": 1}}, …],
  "attribution": ["Contains public sector information licensed under the Open Government Licence v3.0", …],
  "factors_version": "2026.1"
}
```

With crawler data, lines that used it also carry `crawler_source`, and the answer has `crawler_sources` (see [Crawler data](#crawler-data)).

Categories always come in the order `flights`, `stays`, `ground`, `food`, `activities`. `included` is false when nothing in the category was counted. Lines and assumptions carry an English `label` / `text` plus a stable `kind` / `code` and `params`, so clients can translate them (the web app does, in all 7 languages).

## Known limits

- Hotel factors are country averages: they don't vary with the hotel's class or size.
- TIM figures exclude non-CO₂ effects while the DESNZ fallback includes them.
- Meals are counted in full, not net of eating at home, and children count as adults.
- Local distances are straight lines between itinerary stops. Airport transfers aren't counted on their own.
- The train hint doesn't check timetables, and it can't see a sea crossing inside one country.
