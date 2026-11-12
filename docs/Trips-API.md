# Trips API

> Frozen with Phase 2 wave 0. **Changes:** later changes are additive only (new fields, endpoints or error codes; nothing renamed, removed or re-typed). Every change needs a contract-change note in its PR and an update to this page in the same PR.

## API contract (frozen at the end of wave 0)

All paths are under `/api`, with JSON in and out. Every route needs `Authorization: Bearer <access_token>` and acts only on the caller's own trips: anybody else's trip answers `404 trip_not_found`. Errors use the Phase 1 envelope `{"detail", "error_code", …}`, malformed bodies keep FastAPI's `422 {"detail": [...]}`, and timestamps are ISO 8601 UTC with `Z`. Days are `YYYY-MM-DD`.

**`today`**: every `GET` below and the check-in accept an optional client local date. The server uses it when it is within ±1 day of the server's UTC date, and otherwise uses the UTC date. Clients send the device's local date.

### Discovery (additive)

`GET /config` gains `features.trips: true` (the trips API exists), `features.journey: bool` (`JOURNEY_UI_ENABLED`) and `features.offline_pack: bool` (`OFFLINE_PACK_ENABLED`, default `true`). When `offline_pack` is false, clients unregister the service worker and delete every offline cache and pack.

### Phases

`phase` ∈ `dreaming | planning | ready | on_the_road | memories`. The effective phase, for start `s`, end `e` (`e` = `s` when missing), override `o`, today `t`, prep complete `p` and `READY_WINDOW_DAYS` = 14:

1. `o` set → `o`.
2. `s` missing → `dreaming`.
3. `t > e` → `memories`.
4. `s ≤ t ≤ e` → `on_the_road`.
5. `p` or `(s − t) ≤ 14` days → `ready`.
6. otherwise → `planning`.

`day_index` = `(t − s) + 1` while on the road, else `null`. `days_to_start` = `s − t` when `t < s`, else `null`. Golden cases live in `backend/tests/fixtures/journey/trip_phase_cases.json`, and every client must pass them.

### Shared objects

`Trip`:
```json
{"id": 12, "title": "Lisbon in spring", "destination": "Lisbon", "destinations": ["Lisbon", "Porto"],
 "origin": "NYC", "start_date": "2027-04-01", "end_date": "2027-04-08", "nights": 7,
 "phase": "planning", "phase_source": "auto", "days_to_start": 140, "day_index": null,
 "num_travelers": 2, "budget_usd": 3000, "countries": ["PT"],
 "prep": {"done": 3, "total": 9, "percent": 33, "complete": false},
 "has_itinerary": true, "recap_completed_at": null, "created_at": "…Z", "updated_at": "…Z"}
```
- `title` is `plans.title`, falling back to `plans.name`.
- `destinations` is `search_data.destinations`, else `[destination]`, else `[]`.
- `phase_source` is `auto|manual`. `nights` = `end − start` in days, or `null`.
- `countries` holds ISO alpha-2 codes, resolved locally (no network).
- `prep` comes from the prep rules below. For a Dreaming trip it is `{"done": 0, "total": 0, "percent": 0, "complete": false}`.

`GameDelta`: exactly as in `docs/Accounts-API.md`. It is `null` when the game is disabled.

`Place key`: `<kind>:<slug>`. `kind` ∈ `activity|place|food|hotel|event|tour|nearby|other`. `slug` = the name NFKD-normalised, combining marks removed, lower-cased, every run of non-`[a-z0-9]` replaced by `-`, trimmed of `-`, and cut to 60 characters (`"" → "x"`). The server accepts `^[a-z]+:[a-z0-9-]{1,60}$`. The vectors are in `backend/tests/fixtures/journey/place_key_cases.json` (for example `["activity", "Pastéis de Belém!"] → "activity:pasteis-de-belem"`).

### Trips

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /trips` | query `today?` | `{"trips": [Trip], "pinned_id": 12 \| null, "today": "2026-11-12"}`. Sorted by phase (on_the_road, ready, planning, dreaming, memories), then `start_date` (memories: newest first), then `updated_at` desc. At most 200 | — |
| `POST /trips` | `{"title": 1..80, "destination"?: ≤120, "start_date"?, "end_date"?}` | `201 Trip`. Creates a `plans` row: `name = title`, `search_data = {"destination": d}` (or `{}`), `selections = {}` | `422 trip_dates_invalid`, `422 trip_title_invalid` |
| `GET /trips/{id}` | query `today?` | `Trip` | `404 trip_not_found` |
| `PATCH /trips/{id}` | any subset of `{"title", "start_date", "end_date", "phase"}`. A `null` date clears it, and `"phase": null` clears the override | `Trip` | `422 trip_dates_invalid` (end < start, span > 365 days, or a year outside 2000–2100), `422 trip_phase_invalid`, `422 trip_title_invalid`, `404` |
| `DELETE /trips/{id}` | — | `204`. Deletes the plan and every child row (the same as `DELETE /plans/{id}`) | `404` |
| `GET /trips/stats` | — | `{"countries": [{"code": "PT", "name": "Portugal", "first_trip_id": 12, "visited_at": "…Z", "source": "checkin"\|"recap"}], "continents": ["EU"], "bucket_goal": 30 \| null, "trips_by_phase": {"dreaming": 1, …}}` | — |

`pinned_id` is the on-the-road trip with the earliest start, else the trip with the smallest `days_to_start`, else the memories trip with an `end_date` in the last 14 days and no `recap_completed_at`, else `null`. The `POST /plans` handler stores `start_date`/`end_date` from `search_data`, so plans saved by any client become dated trips.

### Prep checklist

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /trips/{id}/prep` | query `today?` | `{"items": [PrepItem], "done", "total", "percent", "complete"}` | `404` |
| `PUT /trips/{id}/prep/{item_id}` | `{"done": bool}` | the same object plus `"item": PrepItem, "game": GameDelta \| null` | `404 prep_item_unknown`, `409 prep_item_auto` (`offline_pack`), `409 prep_item_na` |

`PrepItem`: `{"id", "status": "todo"|"done"|"na", "auto": bool, "due": "YYYY-MM-DD"|null, "overdue": bool, "facts": {…}}`. `total` counts the items that are not `na`, `percent` = `floor(100 × done / total)` (0 when `total` is 0), and `complete` = `total > 0 and done == total`. Items, in order, with `due` relative to the start (`null` without a start):

| id | `na` when | due | facts |
|---|---|---|---|
| `visa` | the visa row says `visa-free` | start − (visa lead days, or 21) | `visa_type`, `max_stay_days`, `processing_time`, `official_url`, `source` (`ai` from the snapshot, else `static`, else `null`) |
| `passport` | — | start − 30 | — |
| `bookings` | — | start − 30 | `flight: bool`, `hotel: bool` (selected in the plan) |
| `insurance` | — | start − 14 | — |
| `documents` | — | start − 7 | — |
| `stress_test` | no itinerary | start − 7 | `score: int \| null` (the last score, Task 37) |
| `sim` | — | start − 3 | `plan_name \| null` |
| `money` | — | start − 3 | `currency \| null` (the local currency code) |
| `packing` | — | start − 1 | `items: int` |
| `emergency_card` | — | start − 1 | — |
| `checkin` | no flight selected | start − 1 | — |
| `offline_pack` (auto) | — | start − 1 | `saved_at \| null` |

Visa lead days: none for visa-free. Otherwise take the largest number in `processing_time`: weeks × 7, business days × 1.4 rounded up, days as is. Add 7 days of buffer. When there is no number, use 21. When `complete` first becomes true, the trip's `trip_ready` award is made (once per trip).

### Snapshot and offline pack

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `PUT /trips/{id}/snapshot` | `{"emergency_card"?, "forex"?, "visa"?, "packing_list"?, "weather"?}`: each an object or `null`; other keys ignored | `204`. Stores the merged object with `as_of` = server time | `413 snapshot_too_large` (> 262144 bytes as JSON), `422 snapshot_invalid` |
| `GET /trips/{id}/offline-pack` | query `today?` | `OfflinePack` with `Cache-Control: no-store`. Marks prep `offline_pack` done (Task 37) | `404` |

Clients send the snapshot after every plan save or update made while the results are on screen. Values are the section results as streamed, without `verification`.

`OfflinePack`:
```json
{"version": 1, "trip_id": 12, "generated_at": "…Z", "title": "…", "start_date": "…", "end_date": "…",
 "destinations": [{"city": "Lisbon", "country_code": "PT", "country_name": "Portugal"}],
 "emergency": {"source": "ai"|"static"|null, "as_of": "…Z"|null,
   "cities": [{"city": "Lisbon", "emergency_numbers": {…}, "embassy": {…}|null, "hospitals": [], "local_phrases": []}]},
 "phrases": {"language": "pt", "language_name": "Português", "items": [{"id": "help", "text": "Socorro!", "romanized": null}]} | null,
 "address_card": {"hotel_name": "…", "area": "…"|null, "city": "Lisbon",
   "take_me_to": {"text": "…", "romanized": null}|null} | null,
 "currency": {"local": "EUR", "home": "USD", "rate": 0.92, "as_of": "…Z", "source": "snapshot"} | {"local": "EUR", "home": "USD", "rate": null, "as_of": null, "source": null} | null,
 "selections": {"itinerary", "itinerary_layout", "itinerary_edits", "itinerary_notes", "itinerary_slots", "hotel", "flight", "sim", "packing_list"},
 "checkins": ["2027-04-01"]}
```
- `rate` is local units per 1 home unit.
- `home` is `USD` unless the snapshot's forex has a rate from the traveller's home currency.
- `phrase` ids: `help`, `call_police`, `need_doctor`, `take_me_to`, `thank_you`, `how_much`, `where_toilet`, `dont_understand`.
- `phrases` is `null` for English-speaking countries.

### Expenses

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /trips/{id}/expenses` | — | `{"expenses": [Expense], "totals": {"by_currency": {"EUR": "123.40"}, "usd_estimate": "140.20" \| null, "by_category_usd": {"food": "40.00"}, "unconverted": ["GBP"]}, "rate": {"local": "EUR", "usd_to_local": 0.92, "as_of": "…Z"} \| null}` | `404` |
| `POST /trips/{id}/expenses` | `{"client_id": uuid, "amount": "12.50", "currency": "EUR", "category", "note"?: ≤140, "spent_on": day}` | `201 Expense`, or `200 Expense` (the existing row) when `client_id` was already used on this trip | `422 amount_invalid`, `422 currency_invalid`, `422 category_invalid`, `422 note_too_long`, `409 expense_limit` (2000 per trip) |
| `PATCH /trips/{id}/expenses/{eid}` | a subset of `amount`, `currency`, `category`, `note`, `spent_on` | `Expense` | the above, `404 expense_not_found` |
| `DELETE /trips/{id}/expenses/{eid}` | — | `204` | `404 expense_not_found` |

`Expense`: `{"id", "client_id", "amount": "12.50", "currency": "EUR", "category", "note", "spent_on", "created_at", "updated_at"}`. `category` ∈ `flights|lodging|food|transport|activities|shopping|fees|other`. Amounts are decimal strings stored as integer minor units, with the currency's exponent: 0 for `JPY KRW VND CLP ISK UGX XAF XOF`, 3 for `BHD KWD OMR JOD TND`, else 2. The rules are `0 < amount ≤ 1,000,000` and no more decimals than the exponent allows. USD estimates use only USD rows and rows in the snapshot's local currency (`amount / usd_to_local`). Every other currency is listed in `unconverted`.

### Journal and places (ratings, visits)

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /trips/{id}/journal` | — | `{"entries": [Entry]}`, sorted by `day` (nulls last), then `created_at` | `404` |
| `POST /trips/{id}/journal` | `{"client_id": uuid, "body": 1..4000, "day"?, "mood"?: "great"\|"good"\|"ok"\|"tough"}` | `201 Entry`, or `200` on a repeated `client_id` | `422 journal_empty`, `422 journal_too_long`, `422 mood_invalid`, `409 journal_limit` (500) |
| `PATCH /trips/{id}/journal/{eid}` | a subset of `body`, `day`, `mood` | `Entry` | the above, `404 entry_not_found` |
| `DELETE /trips/{id}/journal/{eid}` | — | `204` | `404 entry_not_found` |
| `GET /trips/{id}/places` | — | `{"places": [TripPlace]}` | `404` |
| `PUT /trips/{id}/places/{place_key}` | `{"name": 1..120, "kind", "visited"?: bool, "stars"?: 1..5 \| null, "note"?: ≤500, "day"?, "lat"?, "lng"?}` (upsert; omitted fields are kept) | `{"place": TripPlace, "game": GameDelta \| null}`. `game` is set when `visited` first becomes true | `422 place_key_invalid`, `422 stars_invalid`, `422 note_too_long`, `409 places_limit` (1000) |
| `DELETE /trips/{id}/places/{place_key}` | — | `204` | `404 place_not_found` |

`Entry`: `{"id", "client_id", "day", "body", "mood", "created_at", "updated_at"}`. `TripPlace`: `{"place_key", "name", "kind", "visited", "stars", "note", "day", "lat", "lng", "visited_at", "updated_at"}`.

### Today

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `POST /trips/{id}/checkin` | `{"day": "YYYY-MM-DD"}` | `200 {"day", "day_index", "city", "country_code", "new_country": bool, "streak": {"current", "longest", "last_day", "freezes"} \| null, "game": GameDelta \| null}`. A second call for the same day returns the same data with an empty delta | `409 checkin_out_of_trip` (day outside `[start, end]`), `422 checkin_day_invalid` (more than 1 day from the server's UTC date) |
| `GET /trips/{id}/checkins` | — | `{"days": ["2027-04-01"], "streak": … \| null}` | `404` |

The city for day *n* follows the multi-city allocation of `TravelSearchRequest.city_stays` (`destination_nights` honoured), else `destination`.

### Recap

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /trips/{id}/recap` | query `today?` | `Recap` | `404` |
| `POST /trips/{id}/recap/complete` | query `today?` | `{"completed_at", "new_countries": ["PT"], "game": GameDelta \| null}`. Idempotent: a repeat returns the first `completed_at`, `new_countries: []` and an empty delta | `409 recap_not_ready` (today ≤ end date, or no dates) |

`Recap`:
```json
{"trip_id": 12, "title": "…", "start_date": "…", "end_date": "…", "days": 8, "nights": 7, "planned_days": 7,
 "places": [TripPlace], "visited_count": 9, "rated_count": 7, "avg_stars": 4.3,
 "route": [[38.70, -9.14]], "distance_km": 41.2,
 "countries": [{"code": "PT", "name": "Portugal", "new": true}], "continents": ["EU"],
 "spend": {"budget_usd": 3000, "plan_cost_usd": null, "spent_usd": "2140.50", "by_category_usd": {…}, "unconverted": ["GBP"]},
 "journal_count": 5, "checkin_days": 6, "completed_at": null, "can_complete": true}
```
- `route` holds the visited places with coordinates, ordered by `day` then `visited_at` (at most 500 points).
- `distance_km` is the haversine sum along `route`, to one decimal, or `null` with fewer than two points. Clients that have the itinerary may draw the *planned* route when `route` is empty.
- `new` means the country was added to `user_countries` by this trip.
- `plan_cost_usd` is `null` on the server (clients compute it with `computePlanCost`).

### Game (additive rules and badges)

These are new rule ids in `GET /game/catalog`. Clients translate them as `game:rules.<id>` and `game:badges.<id>.name|desc`.

| rule | points | daily cap | idempotency key |
|---|---|---|---|
| `traveller_type` | 25 | 1 | once per user |
| `plan_saved` | 10 | 3 | `plan_saved:<plan_id>` |
| `trip_ready` | 50 | 2 | `trip_ready:<plan_id>` |
| `smart_planner` | 15 | 3 | `smart_planner:<plan_id>:<score>` |
| `trip_checkin` | 10 | 1 | `trip_checkin:<plan_id>:<day>` |
| `place_visited` | 5 | 10 | `place_visited:<plan_id>:<place_key>` |
| `country_visited` | 25 | 5 | `country_visited:<user_id>:<code>` |
| `continent_visited` | 50 | 3 | `continent_visited:<user_id>:<continent>` |
| `recap_complete` | 100 | 2 | `recap_complete:<plan_id>` |

Badges (`id` (rule, target, tier, icon)):
- `traveller` (traveller_type, 1, bronze, compass)
- `first_trip` (plan_saved, 1, bronze, map)
- `trip_ready` (trip_ready, 1, bronze, circle-check) and `ready_regular` (trip_ready, 5, silver, badge-check)
- `smart_planner` (smart_planner, 3, bronze, brain)
- `on_the_road` (trip_checkin, 3, bronze, calendar-check) and `road_warrior` (trip_checkin, 14, silver, calendar-range)
- `local_explorer` (place_visited, 10, bronze, map-pin) and `local_legend` (place_visited, 50, silver, map-pinned)
- `countries_3` (country_visited, 3, bronze, stamp), `countries_10` (country_visited, 10, silver, globe) and `countries_30` (country_visited, 30, gold, earth)
- `continents_3` (continent_visited, 3, silver, earth) and `continents_6` (continent_visited, 6, gold, globe-2)
- `storyteller` (recap_complete, 1, bronze, book-open) and `memory_keeper` (recap_complete, 5, silver, library)

New streak kind `trip_checkin` (`freeze_per_week: 1`). `Settings` gains `bucket_list_goal: int 1..250 | null` (default `null`). `PUT /account/onboarding` with `traveller_type` awards `traveller_type` once.

### Stress test (additive)

`POST /stress-test` accepts an optional `plan_id`. When the caller is signed in and owns the plan, the server stores the returned score as the prep `stress_test` fact and marks that item done. When the score is higher than the previous one, it awards `smart_planner`. The response is unchanged.

## Client notes

Guidance for the web, iOS and Android clients. It adds no API surface.

- **Feature detection.** Call `GET /config` at start-up. Show no trips UI and make no trips call unless `features.trips` is true. The journey UI (Trips hub, phases, Today, recap) also needs `features.journey`. When `features.offline_pack` is false, unregister the service worker (web), delete every offline cache and pack, hide the offline tab and save actions, and never register the service worker again; the server then answers `GET /trips/{id}/offline-pack` with `404 offline_pack_disabled`. A backend without `features.trips` is the previous backend: behave exactly as before.
- **Phase function.** Every client implements the phase rules from "Phases" and must pass the golden cases in `backend/tests/fixtures/journey/trip_phase_cases.json`. The server value in `Trip.phase` is authoritative when online. Offline, recompute it from the cached dates and the device's local date.
- **Trip dates.** Trip dates are normalised: a stored end before the start is returned as the start, so clients can apply the phase function to the Trip's dates as given.
- **`today`.** Send the device's local date (`YYYY-MM-DD`) as `today=` on every `GET` that accepts it, and use the `today` echoed by `GET /trips` for the hub. For check-in, send the local date as `day`. The server accepts it within +-1 day of its UTC date, so a traveller in Tokyo on the morning of day 1 still gets "Day 1".
- **Offline writes.** Create every expense and journal entry with a fresh UUID `client_id` and queue it in a per-user outbox when offline. Flush the outbox single-flight (one flush at a time, per user). Resending is safe: a repeated `client_id` answers `200` with the existing row, so exactly one row results. Delete a user's packs and outbox on sign-out.
- **Snapshot.** After every plan save or update made while results are on screen, send `PUT /trips/{id}/snapshot` with the section results as streamed (without `verification`). It feeds the offline pack and the prep facts.
- **Place keys.** Build `place_key` as `<kind>:<slug>` with the slug rule in "Shared objects". Test your slug function against `backend/tests/fixtures/journey/place_key_cases.json`; for example `["activity", "Pastéis de Belém!"]` gives `activity:pasteis-de-belem`. Additive rule (names with non-ASCII letters or digits, such as CJK, Devanagari, Bengali, Arabic, `ø`, `ß`): after the slug is built, cut it to 51 characters, trim `-` (empty becomes `x`) and append `-` plus 8 lowercase hex digits, the FNV-1a 32-bit hash (offset `0x811c9dc5`, prime `0x01000193`) of the UTF-8 bytes of the NFC-normalised name with outer whitespace trimmed. Distinct non-Latin names then get distinct keys, and the key still matches `^[a-z]+:[a-z0-9-]{1,60}$`. Pure ASCII names are unchanged. The fixture file carries the vectors. Native clients must adopt this before shipping Trips for non-Latin names.
- **Home screen.** Show the Trips hub as the start screen when the signed-in user has at least one trip, otherwise Explore (search). Signed-out users see Explore. Both stay reachable from the tabs.
- **Mobile tabs.** Trips (hub and trip detail), Explore (search, chat and Near me), Alerts (fare and price watches), Play (game and bucket list), You (account, preferences, settings).
- **Game ids to translate.** Translate each rule id in the "Game" table as `game:rules.<id>` and each badge as `game:badges.<id>.name` and `game:badges.<id>.desc`. The ids: rules `traveller_type`, `plan_saved`, `trip_ready`, `smart_planner`, `trip_checkin`, `place_visited`, `country_visited`, `continent_visited`, `recap_complete`; badges `traveller`, `first_trip`, `trip_ready`, `ready_regular`, `smart_planner`, `on_the_road`, `road_warrior`, `local_explorer`, `local_legend`, `countries_3`, `countries_10`, `countries_30`, `continents_3`, `continents_6`, `storyteller`, `memory_keeper`. Hide every game element when `hide_game` is set.

### Implementation notes (additive)

Field-level `422` codes the backend emits beyond the tables above. Clients should show a generic message for any `422 *_invalid` code they do not know.

| Route | Extra code | When |
|---|---|---|
| `POST /trips/{id}/expenses`, `PATCH .../expenses/{eid}` | `422 spent_on_invalid` | `spent_on` is not a `YYYY-MM-DD` day |
| `POST /trips/{id}/expenses`, `POST /trips/{id}/journal` | `422 client_id_invalid` | `client_id` is missing or not a UUID |
| `POST /trips/{id}/journal`, `PATCH .../journal/{eid}` | `422 day_invalid` | `day` is not a `YYYY-MM-DD` day |
| `PUT /trips/{id}/places/{place_key}` | `422 name_invalid` | `name` is not 1 to 120 characters |
| `PUT /trips/{id}/places/{place_key}` | `422 kind_invalid` | `kind` is not one of the place kinds |
| `PUT /trips/{id}/places/{place_key}` | `422 visited_invalid` | `visited` is not a boolean |

`TripPlace.visited_at` is a never-cleared first-visit marker: it is set the first time `visited` becomes true and stays when `visited` is later set back to false. Clients read `visited` for the current state and use `visited_at` only for ordering and "first visited".
