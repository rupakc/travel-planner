# Phase 2 — Journey redesign (web) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the web app from "a search that produces a plan" into a companion for the whole trip. It gets a Trips hub with every saved plan as a trip in its phase (Dreaming → Planning → Ready → On the road → Memories), a phase-aware trip screen (prep checklist, Today, offline pack, expenses, journal and ratings, recap), the journey tabs (Trips / Explore / Alerts / Play / You), the shared 5-step onboarding, and the Phase 2 gamified touches of spec §5a. Every existing saved plan becomes a trip with no data loss.

**Architecture:** A trip is a saved plan. `plans` gains nullable `title`, `phase` (a manual override), `start_date`, `end_date` and `recap_completed_at`, and seven new tables hang off it (`trip_expenses`, `trip_journal`, `trip_ratings`, `trip_prep`, `trip_snapshots`, `trip_checkins`, `user_countries`). One wave-0 task freezes the schema and another freezes every backend seam: settings, router stubs, the ownership helper, game hooks and the prep/money/phrases stubs. A third freezes every frontend seam: the API module, the journey flag, routes, nav, stubs and the shared `journey` namespace. The Trips API is published in `docs/Trips-API.md` at the end of wave 0 for the iOS and Android apps. The phase is computed server-side from the dates by one pure function, mirrored in JS and pinned by shared golden cases. The offline pack is a small hand-written service worker plus IndexedDB, so it needs no new dependency and no CSP or Caddy change. The new UI stays hidden behind `features.journey` until the last task switches it on.

**Tech Stack:** FastAPI + SQLite (stdlib `sqlite3`, JSON1), pydantic v2; React 18 + react-router 6, i18next, Leaflet (existing), IndexedDB and Service Worker APIs (no new npm or pip dependency), vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md`: §3 journey tabs and phases, §3a trip data model, §5a gamification, §9 onboarding, §11 Phase 2 row. Style model: `docs/superpowers/plans/2026-11-11-phase1-accounts-game.md`. Folded-in follow-ups: `docs/superpowers/plans/2026-11-11-phase0-followups.md` and `2026-11-11-phase1-followups.md` (Tasks 29–34).

## Global Constraints

- **Two-way compatibility (CLAUDE.md).** The new backend keeps serving the previous SPA and the Android app in the field. `GET/POST /api/plans`, `GET/PUT/DELETE /api/plans/{id}`, the share routes and `GET /api/share/{token}` keep every request field and response key. New plan columns appear as extra keys, which old clients ignore. The new SPA works against the previous backend: when `/api/config` has no `features.trips`, the journey UI, the service worker and every trips call stay off, and the app is exactly today's.
- **Ship-alone merges.** The journey UI renders only when `features.journey` is true (`JOURNEY_UI_ENABLED`, default `false` until Task 42). It can also be turned on for one browser with `localStorage.tp_journey = "1"`, but only when `features.trips` is true. While the flag is off, `/`, `/chat`, `/nearby`, `/alerts`, `/preferences`, `/account` and `/admin` render as today.
- **Contract freeze.** The "API contract" section below is frozen when wave 0 merges. Changing it later needs a contract-change note in the PR and an update to `docs/Trips-API.md` in the same PR.
- **Additive schema only.** `ALTER TABLE … ADD COLUMN` and `CREATE TABLE IF NOT EXISTS`, nothing renamed or dropped. The date backfill of existing plans runs exactly once (marker `meta.trips_backfill_v1`).
- **Existing plans migrate.** Every row in `plans` is a trip. Its dates are its columns, else `search_data.departure_date`/`return_date`. `DELETE /api/plans/{id}` (old SPA) also deletes the trip's child rows.
- **Honesty rules stay.** Rates and prices in the pack, expenses and recap are labelled with their date and source ("rate from 12 Nov, approximate"). An estimate never awards points. The static-first data stays: the pack uses static emergency numbers when no AI snapshot exists, labelled `source: "static"`.
- **Game guardrails (§5a).** Awards come only from server-observed events (plan saved, prep complete, check-in, place visited, recap completed, traveller type set, stress-test score improved), never from telemetry or client claims. Each award has an idempotency key and a daily cap. There are no points for volume, `hide_game` hides every game element, and the game never gates a feature. Point values live in `backend/app/game/rules.json`.
- **i18n.** Every new user-visible string is in all 7 languages (`en es de fr hi zh bn`). Each frontend task owns **one namespace**, named in the task. The only edits to existing namespaces are the ones named in a task: `errors` (Task 4), `game` (Task 15), `onboarding` (Task 26, which adds keys and never renames any, because the mobile apps read them), and `chat.title` (Task 31). Use informal es/de and `vous` in fr. Never translate "Voyager". Dates, numbers and currency go through `i18n/format.js`.
- **Telemetry.** Phase 2 events are added once to the closed registry (Task 3). Props are enums, ints and bools only: never an amount, a journal text, a place name or a trip title.
- **Offline storage is per user.** IndexedDB records are keyed `"<user_id>:<trip_id>"`. Sign-out (and `session_revoked`) deletes that user's packs and outbox. The service worker never caches `/api/*`.
- **CSP and deploy.** Production CSP stays `script-src 'self'; worker-src 'self' blob:`. The service worker is `/sw.js` from `frontend/public/`, served by the existing `no-cache` SPA handle. No Caddyfile change, so a deploy never recreates Caddy.
- **Accessibility.** Every interactive element gets a `data-tid`. Animations (confetti, passport stamp, reveal) are CSS-only, and `prefers-reduced-motion: reduce` turns them off. Tap targets are at least 44 px on phones.
- **New primary buttons use `bg-teal-700 hover:bg-teal-800 text-white`** (5.47:1). Task 38 sweeps the old `bg-teal-600` buttons.
- Python 3.12, `ruff check backend/` clean; `cd frontend && npx eslint src/ --max-warnings 0`; `mkdocs build --strict`; `cd backend && python3 -m pytest -q`, `cd frontend && npm test` and `python3 -m pytest -q deploy/gcp/tests` keep passing.

## Review Focus

1. **Opening the app offline.** In airplane mode, a reload of `/trips/12/offline` must show the saved pack, not the login page. Today `AuthContext` drops the token on any `/auth/me` failure, a network error included. Expected: a network error keeps the token and the cached user and marks the app offline. A real `401` still signs out. The service worker serves the cached shell. Tests in Task 21 (`keeps the session when /auth/me fails offline`, `navigation falls back to the cached shell`).
2. **Day boundaries across time zones.** A traveller in Tokyo opens Today at 07:00 on day 1 while UTC is still the day before. They expect "Day 1", a working check-in and the trip in *On the road*. The client sends its local date (`today=`), and the server accepts it within ±1 day of the UTC date. Tests in Task 6 (golden case `tokyo_morning_day1`) and Task 14 (`test_checkin_accepts_client_day_ahead_of_utc`).
3. **Mixed versions and legacy plans.** The old SPA on the new backend must list, load, update and delete plans as before, including a Dreaming trip created by the new SPA (minimal `search_data`, empty `selections`). The new SPA on the old backend shows no journey UI and registers no service worker. Tests in Task 7 (`test_get_plans_keeps_legacy_keys`, `test_dreaming_trip_loads_in_old_drawer_shape`, `test_delete_plan_cascades`) and Task 4 (`old backend keeps the classic shell`).
4. **Offline writes sent twice.** An expense or journal entry added offline is retried after reconnecting, possibly from two tabs. Exactly one row must result. Every write carries a `client_id` with `UNIQUE(plan_id, client_id)`, and a repeat answers `200` with the existing row. The outbox flush is single-flight. Tests in Task 9 (`test_same_client_id_twice_one_row`), Task 10 (journal equivalent) and Task 21 (`concurrent flushes send each item once`).
5. **Odd dates and partial data.** Odd inputs must degrade to a sensible state with no crash: a plan with no dates, a `return_date` before `departure_date`, a multi-city plan with `destination_nights`, an itinerary whose slots lack coordinates, `selections` missing keys, or a trip of more than 365 days. Expected states: Dreaming, a single-day trip, the right city for each day, a recap with a `null` distance, and `422 trip_dates_invalid` on edits. Tests in Task 6 (golden cases), Task 13 (`test_no_coordinates_distance_null`) and Task 20 (`renders without itinerary`).

---

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

---

## Shared-file hotspots and how conflicts are avoided

| Hotspot | Rule |
|---|---|
| `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/api/routes/client_config.py` | Only Task 1. It registers every Phase 2 router (stub modules) and adds every setting. |
| `backend/app/db/trips_schema.py`, `trip_children.py`, `user_countries_db.py`, `trip_snapshot_db.py` | Only Task 2. |
| `backend/app/db/plans_db.py`, `backend/app/api/routes/plans.py`, `backend/app/services/account_data.py` | Only Task 7. |
| `backend/app/schemas/request.py` | Only Task 6 (extracts `allocate_city_days`). |
| `backend/app/game/rules.json`, `game/trip_hooks.py` (bodies), `api/routes/account.py`, `db/user_settings_db.py`, `frontend/src/i18n/locales/*/game.json` | Only Task 15. Task 1 creates `trip_hooks.py` as stubs. |
| `backend/app/services/trip_prep.py`, `trip_money.py`, `phrases.py` | Task 1 creates stubs with the final signatures; Tasks 8, 9 and 12 fill them in. |
| `backend/app/api/routes/stress_test.py` | Only Task 37. |
| `backend/app/telemetry/registry.py`, `docs/Telemetry.md` | Only Task 3. |
| `frontend/src/App.jsx`, `components/ui/NavBar.jsx`, `context/SearchDataContext.jsx`, `telemetry/routes.js`, `services/tripsApi.js` | Only Task 4. It adds every route, stub page and stub component, and each later task overwrites only its own stub. |
| `frontend/src/context/AuthContext.jsx`, `frontend/vite.config.js`, `frontend/public/sw.js` | Only Task 21. |
| `frontend/src/pages/ResultsPage.jsx` | Only Task 34. `ChatPage.jsx`: only Task 35. `NearbyPage.jsx`: only Task 36. `SearchPage.jsx`: only Task 29. `PlanViewModal.jsx`: only Task 17. |
| `frontend/index.html`, `pages/LoginPage.jsx`, `pages/SignupPage.jsx` | Only Task 31. `FeedbackWidget.jsx`, `account/AccountMenu.jsx`: only Task 32. `frontend/design/tokens.json`, `theme/tokens.*`, `ui/AttributionFooter.jsx`: only Task 30. `i18n/index.js`, `test/setup.js`: only Task 33. |
| The `bg-teal-600` sweep across existing files | Only Task 38, in wave 3, after every other UI task has merged. |
| Docs (`CLAUDE.md`, `Configuration.md`, `API-Reference.md`, `Deployment-GCP.md`, `Privacy.md`, `Feature-Parity.md`, `Frontend.md`, `Internationalization.md`, `Theming.md`, `Changelog.md`) | Only Task 39. Task 5 creates `docs/Trips-API.md` and is the only Phase 2 edit to `mkdocs.yml`. |

---

## Wave 0 — seams and contract

### Task 1: Backend seams (settings, router stubs, ownership, hooks, service stubs, config flags)

**Files:**
- Create: `backend/app/api/routes/{trips,trip_prep,trip_money,trip_journal,trip_offline,trip_today,trip_recap}.py` (each `router = APIRouter()`), `backend/app/core/trip_access.py`, `backend/app/game/trip_hooks.py`, `backend/app/services/trip_prep.py`, `backend/app/services/trip_money.py`, `backend/app/services/phrases.py`
- Modify: `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/api/routes/client_config.py`
- Test: `backend/tests/test_phase2_seams.py`, `backend/tests/test_client_config.py` (extend)

**Interfaces:**
- Consumes: Task 2 `create_trip_tables()` (wired in Step 4).
- Produces:
  - Settings: `journey_ui_enabled: bool = False`, `offline_pack_enabled: bool = True`, `ready_window_days: int = 14`, `trip_max_expenses: int = 2000`, `trip_max_journal: int = 500`, `trip_max_places: int = 1000`, `trip_snapshot_max_bytes: int = 262144`.
  - `owned_trip(plan_id: int, user: dict) -> dict`: the `plans_db.get_plan` dict when `plan["username"] == user["username"]`, else it raises `ApiError(404, "trip_not_found", "Trip not found")`.
  - `trip_hooks` (stubs that return `None`, or `(None, None)`): `on_plan_saved(user_id: str, plan_id: int) -> dict | None`, `on_trip_ready(user_id, plan_id) -> dict | None`, `on_smart_planner(user_id, plan_id, score: int) -> dict | None`, `on_place_visited(user_id, plan_id, place_key: str) -> dict | None`, `on_trip_checkin(user_id, plan_id, day: date, new_countries: list[str]) -> tuple[dict | None, dict | None]` (game, streak), `on_recap_complete(user_id, plan_id, new_countries: list[str]) -> dict | None`, `on_traveller_type(user_id, traveller_type: str) -> dict | None`.
  - Service stubs: `trip_prep.prep_summary(plan: dict, today: date) -> dict` returns `{"done": 0, "total": 0, "percent": 0, "complete": False}`; `trip_money.spend_summary(plan: dict) -> dict` returns `{"spent_usd": None, "by_category_usd": {}, "unconverted": [], "by_currency": {}}`; `phrases.phrases_for_country(code: str) -> dict | None` returns `None`.
  - `/config`: `features.trips: True`, `features.journey: settings.journey_ui_enabled`, `features.offline_pack: settings.offline_pack_enabled`.
  - `main.py` includes the seven routers with `prefix="/api"` and tag `trips`, and calls `create_trip_tables()` right after `create_account_tables()`.

- [ ] **Step 1: Write failing tests**:
  - `test_stub_routers_importable`: each module exposes `router`, and `GET /api/trips` answers 404 or 405 with no import error.
  - `test_owned_trip_404_for_other_user`.
  - `test_hooks_stubs_return_none`.
  - `test_config_features_trips`: `features.trips is True` and `features.journey is False` by default; with `JOURNEY_UI_ENABLED=true` → `True`; `OFFLINE_PACK_ENABLED=false` → `features.offline_pack is False`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_phase2_seams.py tests/test_client_config.py` → FAIL.
- [ ] **Step 3: Implement** everything except the lifespan call.
- [ ] **Step 4: Rebase on Task 2**, add `create_trip_tables()` to the lifespan, and run the whole backend suite and `ruff check backend/` → PASS.
- [ ] **Step 5: Commit** `feat(trips): phase 2 backend seams — settings, router stubs, hooks, config flags`

### Task 2: Schema, one-time migration and shared row helpers

**Files:**
- Create: `backend/app/db/trips_schema.py`, `backend/app/db/trip_children.py`, `backend/app/db/user_countries_db.py`, `backend/app/db/trip_snapshot_db.py`
- Test: `backend/tests/test_trips_schema.py`

**Interfaces:**
- Produces:
  - `create_trip_tables() -> None`. It is idempotent.
    - It adds the `plans` columns that are missing: `title TEXT`, `phase TEXT`, `start_date TEXT`, `end_date TEXT` and `recap_completed_at TEXT`.
    - It creates these tables:
      - `trip_expenses(id INTEGER PK AUTOINCREMENT, plan_id INTEGER NOT NULL, client_id TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, category TEXT NOT NULL, note TEXT, spent_on TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(plan_id, client_id))`
      - `trip_journal(id INTEGER PK AUTOINCREMENT, plan_id INTEGER NOT NULL, client_id TEXT NOT NULL, day TEXT, body TEXT NOT NULL, mood TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(plan_id, client_id))`
      - `trip_ratings(plan_id INTEGER NOT NULL, place_key TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, visited INTEGER NOT NULL DEFAULT 0, stars INTEGER, note TEXT, day TEXT, lat REAL, lng REAL, visited_at TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(plan_id, place_key))`
      - `trip_prep(plan_id INTEGER NOT NULL, item_id TEXT NOT NULL, done_at TEXT, meta TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(plan_id, item_id))`
      - `trip_snapshots(plan_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)`
      - `trip_checkins(plan_id INTEGER NOT NULL, day TEXT NOT NULL, city TEXT, country_code TEXT, created_at TEXT NOT NULL, PRIMARY KEY(plan_id, day))`
      - `user_countries(user_id TEXT NOT NULL, country_code TEXT NOT NULL, first_plan_id INTEGER, source TEXT NOT NULL, visited_at TEXT NOT NULL, PRIMARY KEY(user_id, country_code))`
    - It adds an index on `plan_id` for `trip_expenses` and `trip_journal`.
    - Backfill: when `meta` has no `trips_backfill_v1`, it sets `start_date`/`end_date` from `json_extract(search_data, '$.departure_date' | '$.return_date')`, but only where the column is NULL, `json_valid(search_data)`, and the value matches `YYYY-MM-DD`. It then writes the marker. All of this runs in one transaction.
  - `TRIP_CHILD_TABLES: tuple[str, ...]` (the six `plan_id` tables) and `delete_trip_children(conn, plan_id: int) -> None`.
  - `add_countries(user_id: str, codes: list[str], plan_id: int, source: Literal["checkin","recap"]) -> list[str]`, which returns the newly added codes (`INSERT OR IGNORE`); `list_countries(user_id: str) -> list[dict]`.
  - `get_snapshot(plan_id: int) -> dict | None` (with `as_of`); `put_snapshot(plan_id: int, data: dict) -> str`, which merges into the stored object, so a key sent as `null` clears it, and returns `as_of`.

- [ ] **Step 1: Write failing tests**:
  - `test_create_twice_is_idempotent`.
  - `test_backfill_sets_dates_from_search_data`.
  - `test_backfill_runs_once`: clear a trip's dates, call `create_trip_tables()` again, and the dates stay `NULL`.
  - `test_bad_search_data_is_skipped` (`"not json"`, a missing date, `"2026-13-99x"`).
  - `test_get_plan_has_new_keys` (`plans_db.get_plan` returns `title`, `phase`, `start_date`, `end_date` and `recap_completed_at`).
  - `test_delete_children_removes_all_six`.
  - `test_add_countries_returns_only_new`.
  - `test_snapshot_merge_and_clear`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_trips_schema.py` → FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): additive trip schema with one-time date backfill`

### Task 3: Telemetry events for Phase 2

**Files:**
- Modify: `backend/app/telemetry/registry.py`, `docs/Telemetry.md` (a new "Journey" table with one row per event)
- Test: `backend/tests/test_telemetry_registry.py` (extend)

**Interfaces:**
- Produces these registry entries:
  - `trip_view{surface: enum:<hub|overview|prep|today|money|journal|recap|offline>, phase: enum:<dreaming|planning|ready|on_the_road|memories|none>}`
  - `trip_action{action: enum:<create|rename|dates|phase_override|phase_clear|delete|open_planner|plan_it|share_status>}`
  - `prep_toggle{item: enum:<visa|passport|bookings|insurance|documents|stress_test|sim|money|packing|emergency_card|checkin|offline_pack>, done: bool}`
  - `prep_complete{items: int}`
  - `today_action{action: enum:<checkin|next_up|directions|visited|status_share|nearby>}`
  - `offline_pack{action: enum:<save|refresh|open|remove>, result: enum:<ok|error|unsupported|quota>, kb: int}`
  - `outbox_flush{sent: int, failed: int, dropped: int}`
  - `expense_action{action: enum:<add|edit|delete>, category: enum:<flights|lodging|food|transport|activities|shopping|fees|other>, queued: bool}`
  - `journal_action{action: enum:<add|edit|delete>, queued: bool}`
  - `place_action{action: enum:<visited|unvisited|rate|unrate>, kind: enum:<activity|place|food|hotel|event|tour|nearby|other>, stars: int}`
  - `recap_action{action: enum:<view|complete|share|where_next>}`
  - `completeness_view{surface: enum:<drawer|trip>, percent: int}`
  - `onboarding_result{type: enum:<budget_backpacker|family|luxury|adventure|culture_foodie|business|relaxation|accessible>, secondary: int}`
  - `journey_shell{enabled: bool, source: enum:<config|override|off>}`

- [ ] **Step 1: Write failing tests**: `clean_event` drops an unknown prop on `expense_action` (e.g. `amount`); every new event is in `EVENTS`; `test_every_event_documented` passes.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(telemetry): phase 2 journey events`

### Task 4: Frontend seams (trips API, journey flag, routes, nav, stubs, shared namespace)

**Files:**
- Create:
  - `frontend/src/services/tripsApi.js`, `frontend/src/hooks/useJourney.js`, `frontend/src/journey/paths.js`, `frontend/src/utils/placeKey.js`
  - `frontend/src/components/ui/BottomTabs.jsx`
  - `frontend/src/i18n/locales/<lang>/journey.json` (7 files)
- Create, as stubs that render `null`, one per later task:
  - pages: `pages/TripsPage.jsx` (T16), `pages/TripPage.jsx` (T17), `pages/PlayPage.jsx` and `pages/YouPage.jsx` (T28), `pages/OnboardingPage.jsx` (T26)
  - in `components/trips/`: `TripOverview.jsx` (T17), `CompletenessMeter.jsx` (T18), `PrepChecklist.jsx` (T19), `TodayView.jsx` (T20), `OfflinePack.jsx` (T22), `ExpenseLog.jsx` (T23), `Journal.jsx` (T24), `Recap.jsx` (T25), `JourneyTour.jsx` (T27)
  - `components/onboarding/OnboardingGate.jsx` (T26), `components/offline/OfflineBanner.jsx` (T21), `components/I18nRouteGate.jsx` (T33; the stub renders `children`)
- Modify:
  - `frontend/src/App.jsx`: `/onboarding` is a full-screen route inside `RequireAuth`. When the journey is on, Layout routes `/` → TripsPage, `/explore` → the always-mounted SearchTab (shown while `path === '/explore'`), `/trips/:id` and `/trips/:id/:tab` → TripPage, `/play` and `/you`. It mounts `<OnboardingGate/>`, `<OfflineBanner/>` and wraps the routed content in `<I18nRouteGate pathname>`. `KNOWN_PATHS` becomes a matcher that accepts `/trips/<digits>(/<tab>)?`.
  - `frontend/src/components/ui/NavBar.jsx`: when the journey is on, the tabs are Trips `/`, Explore `/explore`, Alerts `/alerts`, Play `/play` (hidden when `hide_game`) and You `/you`, plus Admin for admins, with `data-tour="nav-<tab>"`. Inactive tab text is `text-slate-500`. On phones (< 640 px) `<BottomTabs/>` replaces the hamburger.
  - `frontend/src/context/SearchDataContext.jsx`: `pendingPlan`, `setPendingPlan(plan)` and `clearPendingPlan()`.
  - `frontend/src/telemetry/routes.js`: static `/explore`, `/play`, `/you`, `/onboarding`; dynamic `/trips/:id` and `/trips/:id/:tab`.
  - `frontend/src/i18n/locales/<lang>/errors.json`: every Phase 2 `error_code` in the contract.
- Test: `frontend/src/services/tripsApi.test.js`, `frontend/src/hooks/useJourney.test.js`, `frontend/src/utils/placeKey.test.js`, `frontend/src/App.journey.test.jsx`, `frontend/src/components/ui/NavBar.test.jsx` (extend)

**Interfaces:**
- Consumes: the API contract; Phase 1 `toApiError`, `useClientConfig`, `useAccountSettings`.
- Produces:
  - `tripsApi.js`. Every function takes `token` first, resolves with `data` and rejects with `toApiError(...)`. A network failure rejects with `code: 'network'`. Every GET sends `today=localToday()`.
    - `listTrips`, `getTrip(id)`, `createTrip(body)`, `patchTrip(id, changes)`, `deleteTrip(id)`, `getTripStats`
    - `getPrep(id)`, `setPrepItem(id, itemId, done)`, `putSnapshot(id, snapshot)`, `getOfflinePack(id)`
    - `listExpenses(id)`, `addExpense(id, body)`, `updateExpense(id, eid, changes)`, `deleteExpense(id, eid)`
    - `listJournal(id)`, `addJournal(id, body)`, `updateJournal(id, eid, changes)`, `deleteJournal(id, eid)`
    - `listPlaces(id)`, `putPlace(id, placeKey, body)`, `deletePlace(id, placeKey)`
    - `checkIn(id, day)`, `listCheckins(id)`, `getRecap(id)`, `completeRecap(id)`
  - `useJourney() -> {enabled: boolean, tripsApi: boolean, offlinePack: boolean, loaded: boolean}`. `enabled` = `tripsApi && (features.journey || localStorage.tp_journey === '1') && localStorage.tp_journey !== '0'`. It emits `journey_shell` once per page load.
  - `tripPath(id, tab?) -> string`; `TRIP_TABS = ['overview','prep','today','money','journal','recap','offline']`.
  - `placeKey(kind: string, name: string) -> string`, per the contract slug rule.
  - The `journey` namespace:
    - `tabs.{trips,explore,alerts,play,you}`
    - `phases.{dreaming,planning,ready,on_the_road,memories}`
    - `tripTabs.<tab>`
    - `countdown_one`/`countdown_other` ("in {{count}} day(s)")
    - `dayOf` ("Day {{day}} of {{count}}"), `dayIn` ("Day {{day}} in {{city}}")
    - `saved.openTrip`, `saved.savedToTrips`
    - `load.failed`, `load.retry`, `offlineCopy` ("Saved for offline")

- [ ] **Step 1: Write failing tests**:
  - `useJourney`:
    - `/config` without `features.trips` → `enabled false` even with `tp_journey=1` (**old backend keeps the classic shell**);
    - `features.journey true` → `enabled`;
    - `tp_journey=0` → off.
  - `App.journey.test.jsx`:
    - flag off → `/` renders SearchPage and `/trips/3` redirects to `/`;
    - flag on → `/` renders TripsPage, `/trips/3/today` renders TripPage, `/trips/abc` redirects to `/`.
  - `placeKey`: every case in `backend/tests/fixtures/journey/place_key_cases.json` (created here, at least 12 cases including accents, CJK → `"x"` fallback, a 100-character name, and punctuation runs).
  - `tripsApi` sends `today` and maps a 404 with `trip_not_found`.
  - `routeTemplate('/trips/12/today') === '/trips/:id/:tab'`.
  - NavBar shows five journey tabs when enabled and hides Play when `hide_game`.
- [ ] **Step 2: Run** `cd frontend && npm test -- src/services src/hooks src/utils/placeKey src/App.journey src/components/ui` → FAIL.
- [ ] **Step 3: Implement.** Translate `journey` and the new `errors` keys into all 7 languages.
- [ ] **Step 4: Run** `npm test`, eslint and `npm run build` → PASS (with the flag off, every existing test is unchanged).
- [ ] **Step 5: Commit** `feat(journey): frontend seams — trips API, journey flag, routes, nav, stubs`

### Task 5: Publish the Trips API contract

**Files:**
- Create: `docs/Trips-API.md`. It holds the "API contract" section of this plan verbatim, plus a "Client notes" section:
  - the phase function and the fixture path;
  - `today` handling;
  - offline writes with `client_id` and an outbox;
  - the snapshot is sent after plan saves;
  - the place-key slug with the fixture;
  - feature detection through `features.trips` / `features.journey`;
  - mobile tab mapping (Trips/Explore/Alerts/Play/You);
  - the game ids to translate.
- Modify: `mkdocs.yml` (nav: Internals → "Trips API", after "Accounts API")
- [ ] **Step 1:** Write the page. **Step 2:** `mkdocs build --strict` → PASS.
- [ ] **Step 3: Commit** `docs: frozen Phase 2 trips API contract for mobile clients`

### Task 6: Trip time and place helpers (backend, JS mirror, golden cases)

**Files:**
- Create: `backend/app/services/trip_phase.py`, `backend/app/services/trip_geo.py`, `backend/app/data/continents.json` (ISO alpha-2 → `AF|AN|AS|EU|NA|OC|SA` for every code in `countries.csv`; the source is noted in `backend/app/db/data/README.md`), `backend/tests/fixtures/journey/trip_phase_cases.json`, `frontend/src/utils/tripPhase.js`
- Modify: `backend/app/schemas/request.py` (extract `allocate_city_days(n: int, total_days: int, destination_nights: list[int | None] | None) -> list[int]` to module level; `_allocate_days` delegates to it, with no behaviour change), `backend/app/db/data/README.md`
- Test: `backend/tests/test_trip_phase.py`, `backend/tests/test_trip_geo.py`, `frontend/src/utils/tripPhase.test.js` (reads the fixture through `node:fs`)

**Interfaces:**
- Produces:
  - Python:
    - `trip_dates(plan: dict) -> tuple[date | None, date | None]`: the columns, else `search_data`. An end before the start becomes the start.
    - `effective_phase(start, end, override, today, prep_complete, ready_window_days=14) -> str`
    - `days_to_start(start, today) -> int | None`, `day_index(start, end, today) -> int | None`
    - `resolve_today(client_today: str | None, now: datetime | None = None) -> date`
  - `trip_geo`:
    - `trip_cities(search_data: dict) -> list[str]`
    - `city_for_day(search_data: dict, start: date, end: date | None, day_index: int) -> str | None` (uses `allocate_city_days`; past the last stay → the last city)
    - `country_of(place: str) -> str | None` (`resolve_place`, `lru_cache(2048)`)
    - `trip_countries(search_data: dict) -> list[str]` (ordered and unique)
    - `continent_of(code: str) -> str | None`
  - JS: `effectivePhase({start, end, override, today, prepComplete, readyWindowDays = 14}) -> string`, `dayIndex(start, end, today) -> number | null`, `daysToStart(start, today) -> number | null`, `localToday(now = new Date()) -> 'YYYY-MM-DD'` (local calendar date).
  - The fixture is a list of `{"name", "start", "end", "override", "today", "prep_complete", "phase", "day_index", "days_to_start"}` with at least 20 cases. Required names: `no_dates_dreaming`, `end_before_start_single_day`, `day_before_start_ready_window`, `fifteen_days_out_planning`, `prep_complete_far_out_ready`, `first_day_on_the_road`, `last_day_on_the_road`, `day_after_end_memories`, `override_wins`, `tokyo_morning_day1` (client today one day ahead of UTC), `no_end_date`.

- [ ] **Step 1: Write failing tests**:
  - Python and JS both iterate the fixture and assert `phase`, `day_index` and `days_to_start`.
  - `resolve_today("2026-11-13", now=2026-11-12T22:00Z)` → 13th; `"2026-11-20"` → the UTC date; `"junk"` → the UTC date.
  - `city_for_day` for Lisbon/Porto with `destination_nights [3, 2]` → days 1–3 Lisbon, days 4–5 Porto, day 9 Porto.
  - `country_of("Lisbon") == "PT"`, `continent_of("PT") == "EU"`, and every `countries.csv` code has a continent.
  - `test_city_stays_unchanged` (the existing multi-city tests still pass).
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_trip_phase.py tests/test_trip_geo.py` and `cd frontend && npm test -- src/utils/tripPhase` → FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** both, plus the whole backend suite → PASS.
- [ ] **Step 5: Commit** `feat(trips): phase function, trip geography and shared golden cases`

## Wave 1 — backend modules

### Task 7: Trips core API (+ plans compatibility, account export and delete)

**Files:**
- Create: `backend/app/db/trips_db.py`, `backend/app/services/trips.py`
- Modify: `backend/app/api/routes/trips.py`, `backend/app/db/plans_db.py` (`save_plan` stores `start_date`/`end_date` from `search_data`; `delete_plan` calls `delete_trip_children` in the same connection), `backend/app/api/routes/plans.py` (after `create_plan`, calls `trip_hooks.on_plan_saved`; the response keys are unchanged), `backend/app/services/account_data.py` (adds `user_countries` to `USER_TABLES`; adds the six child tables to `CHILD_TABLES` with `plan_id IN (SELECT id FROM plans WHERE username = (SELECT username FROM users WHERE id = ?))`; the export gains `"trips": {"<plan_id>": {"expenses", "journal", "places", "prep", "checkins", "snapshot"}}` and `"countries"`)
- Test: `backend/tests/test_trips_api.py`, `backend/tests/test_plans.py` (unchanged, must pass), `backend/tests/test_account_data.py` (extend: `test_every_user_table_is_covered` also requires every table with a `plan_id` column to be in `CHILD_TABLES`)

**Interfaces:**
- Consumes: Task 1 `owned_trip`, `prep_summary`, hooks; Task 2 helpers; Task 6 `trip_dates`, `effective_phase`, `resolve_today`, `trip_countries`.
- Produces: `trip_view(plan: dict, *, today: date, prep: dict) -> dict` (the contract `Trip`), `pick_pinned(trips: list[dict]) -> int | None`, `trips_db.set_trip_fields(plan_id: int, **fields) -> None`, `trips_db.create_trip(username, title, destination, start, end) -> int`. The routes follow the contract (Trips table).

- [ ] **Step 1: Write failing tests**:
  - `test_legacy_plan_becomes_trip` (a plan saved through `POST /plans` with dates → `GET /trips` shows `planning` with those dates);
  - `test_get_plans_keeps_legacy_keys`;
  - `test_dreaming_trip_loads_in_old_drawer_shape` (`GET /plans` returns the created trip with `search_data == {"destination": "Kyoto"}` and `selections == {}`);
  - `test_delete_plan_cascades` (through `DELETE /plans/{id}` and through `DELETE /trips/{id}`);
  - `test_patch_phase_override_and_clear`;
  - `test_dates_invalid` (end < start, a 366-day span, the year 1999 → `422 trip_dates_invalid`);
  - `test_other_users_trip_404`;
  - `test_pinned_prefers_on_the_road`;
  - `test_today_param_shifts_phase`;
  - `test_stats_countries_and_goal`;
  - `test_plan_saved_hook_called_once_per_plan`;
  - `test_account_delete_removes_trip_rows`;
  - `test_export_includes_trips`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_trips_api.py tests/test_account_data.py` → FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(trips): trips API over saved plans`

### Task 8: Prep checklist API

**Files:**
- Create: `backend/app/db/trip_prep_db.py`
- Modify: `backend/app/services/trip_prep.py` (fill it in), `backend/app/api/routes/trip_prep.py`
- Test: `backend/tests/test_trip_prep.py`

**Interfaces:**
- Consumes: Task 2 `get_snapshot`; `static_results.find_visa_row(nationality, destination)`, `get_static_forex` currency resolution (`_resolve_dest_currency` through a new public wrapper in `trip_prep`, not by editing `static_results.py`); Task 6 `trip_dates`; Task 1 `on_trip_ready`.
- Produces:
  - `visa_lead_days(processing_time: str | None, visa_type: str | None) -> int | None`
  - `build_items(plan: dict, snapshot: dict | None, state: dict[str, dict], today: date) -> list[dict]` (pure)
  - `prep_summary(plan: dict, today: date) -> dict`
  - `trip_prep_db.get_state(plan_id) -> dict[str, dict]`, `set_done(plan_id, item_id, done: bool) -> None`, `set_meta(plan_id, item_id, meta: dict) -> None`, `get_meta(plan_id, item_id) -> dict | None`
  - The routes follow the contract (Prep table).

- [ ] **Step 1: Write failing tests**:
  - `test_visa_free_is_na`;
  - `test_visa_lead_days`: `"5-10 business days"` → 21; `"2 weeks"` → 21; `"3-4 weeks"` → 35; `"N/A (visa-free)"` with type `visa-free` → `None`; `"varies"` → 21;
  - `test_due_dates_relative_to_start`;
  - `test_overdue_flag`;
  - `test_checkin_na_without_flight`;
  - `test_stress_test_na_without_itinerary`;
  - `test_dreaming_trip_has_no_due`;
  - `test_offline_pack_put_is_409`;
  - `test_complete_awards_once` (tick all → `game` is set; untick and tick again → no second award; the hook is called with the plan id);
  - `test_snapshot_visa_preferred_over_static`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): prep checklist built from plan, static tables and snapshot`

### Task 9: Expenses API

**Files:**
- Create: `backend/app/db/trip_expenses_db.py`
- Modify: `backend/app/services/trip_money.py` (fill it in), `backend/app/api/routes/trip_money.py`
- Test: `backend/tests/test_trip_money.py`

**Interfaces:**
- Consumes: Task 2 `get_snapshot`; Task 1 `owned_trip`.
- Produces:
  - `currency_exponent(code: str) -> int`, `parse_amount(amount: str, currency: str) -> int` (raises `ValueError`), `format_amount(minor: int, currency: str) -> str`
  - `usd_rate(snapshot: dict | None) -> dict | None` (`{"local", "usd_to_local", "as_of"}` from `forex.exchange_rates`, using the entry with `from_currency == "USD"`, a matching `to_currency` and a numeric `rate > 0`)
  - `spend_summary(plan: dict) -> dict` (keys as in the stub)
  - `expenses_db.add(plan_id, client_id, …) -> tuple[dict, bool]` (row, created), `update`, `delete`, `list_for(plan_id)`
  - The routes follow the contract.

- [ ] **Step 1: Write failing tests**:
  - `test_same_client_id_twice_one_row` (the second POST → 200, same id);
  - `test_jpy_has_no_decimals` (`"1200"` ok, `"12.5"` → `amount_invalid`);
  - `test_kwd_three_decimals`;
  - `test_amount_zero_or_negative_invalid`;
  - `test_currency_must_be_iso`;
  - `test_totals_exact_decimal` (0.10 + 0.20 EUR → `"0.30"`);
  - `test_usd_estimate_from_snapshot_rate` (92.00 EUR at 0.92 → `"100.00"`);
  - `test_unknown_currency_listed_unconverted`;
  - `test_expense_limit` (with the setting at 2 → 409 on the 3rd);
  - `test_other_users_expense_404`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): idempotent expense log with honest USD estimates`

### Task 10: Journal and places API

**Files:**
- Create: `backend/app/db/trip_journal_db.py` (journal and `trip_ratings`)
- Modify: `backend/app/api/routes/trip_journal.py`
- Test: `backend/tests/test_trip_journal.py`

**Interfaces:**
- Consumes: Task 1 `owned_trip`, `on_place_visited`.
- Produces: `journal_db.add_entry(plan_id, client_id, body, day, mood) -> tuple[dict, bool]`, `update_entry`, `delete_entry`, `list_entries(plan_id)`; `upsert_place(plan_id, place_key, fields: dict) -> tuple[dict, bool]` (row, newly visited), `delete_place`, `list_places(plan_id)`. The routes follow the contract. `body` is NFC-normalised and stripped, and control characters other than `\n` are removed.

- [ ] **Step 1: Write failing tests**:
  - journal: `test_same_client_id_twice_one_row`; `test_body_limits` (empty → `journal_empty`; 4001 characters → `journal_too_long`; exactly 4000 ok); `test_mood_enum`; `test_sorted_by_day_nulls_last`.
  - places: `test_place_key_format` (`"Activity:x"` → 422 `place_key_invalid`); `test_stars_bounds` (0 and 6 → `stars_invalid`; `null` clears); `test_upsert_keeps_omitted_fields`; `test_visited_awards_once_per_place`.
  - `test_limits`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): journal entries, place ratings and visits`

### Task 11: Snapshot and offline pack API

**Files:**
- Create: `backend/app/services/offline_pack.py`
- Modify: `backend/app/api/routes/trip_offline.py`
- Test: `backend/tests/test_offline_pack.py`

**Interfaces:**
- Consumes: Task 2 snapshot helpers; Task 6 `trip_cities`, `country_of`, `trip_dates`; `static_results.get_static_emergency_numbers(city)`; `places_db.country_display_name(code)`; Task 1 `phrases_for_country` (the stub returns `None` until Task 12); Task 9 `usd_rate` (rebase if Task 9 has not merged: import inside the function).
- Produces:
  - `build_pack(plan: dict, snapshot: dict | None, checkins: list[str], today: date) -> dict` (the contract `OfflinePack`).
  - Emergency data: the snapshot's `emergency_card` (flat or `cities`) with `source: "ai"` and the snapshot `as_of`. Otherwise the static numbers per city with `source: "static"`. Otherwise `null`.
  - `address_card`: from `selections.hotel` (`name`, `location` → `area`) with the destination's `take_me_to` phrase. `null` without a hotel.
  - Routes: `PUT /trips/{id}/snapshot` (size checked on the canonical `json.dumps`) and `GET /trips/{id}/offline-pack`.

- [ ] **Step 1: Write failing tests**:
  - `test_pack_static_without_snapshot`;
  - `test_pack_prefers_ai_snapshot_with_as_of`;
  - `test_multi_city_has_one_entry_per_city`;
  - `test_currency_rate_null_without_snapshot`;
  - `test_no_store_header`;
  - `test_snapshot_too_large_413`;
  - `test_snapshot_non_object_422`;
  - `test_snapshot_strips_unknown_keys`;
  - `test_pack_has_no_personal_search_fields` (no `nationality`, `existing_visas`, `residence_permits` or `accessibility_needs` anywhere in the pack);
  - `test_other_users_pack_404`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): trip snapshot and offline pack`

### Task 12: Travel phrases data

**Files:**
- Create: `backend/app/data/travel_phrases.json`
- Modify: `backend/app/services/phrases.py` (fill it in), `backend/app/db/data/README.md` (provenance: "model-drafted, second-model checked; native review pending")
- Test: `backend/tests/test_phrases.py`

**Interfaces:**
- Produces:
  - `travel_phrases.json` v1: `{"version": 1, "phrase_ids": [the 8 contract ids], "languages": {"<bcp47>": {"name": "<endonym>", "script": "Latn|Cyrl|Arab|…", "phrases": {"<id>": {"text", "romanized": str | null}}}}, "countries": {"<ISO2>": "<bcp47>" | null}}`.
  - Languages: ar bn cs da de el es fi fr he hi hr hu id is it ja km ko ms nl no pl pt ro ru sv sw th tl tr uk vi zh.
  - Countries: every code in `countries.csv`. Countries where English is the main language map to `null`, and countries whose main language is outside the list map to `null`.
  - `phrases_for_country(code: str) -> dict | None`, which returns `{"language", "language_name", "items": [{"id", "text", "romanized"}]}` in `phrase_ids` order.

- [ ] **Step 1: Write failing tests**:
  - every language has all 8 ids with non-empty `text`;
  - every non-`Latn` script has a non-empty `romanized`;
  - every country maps to a known language or `null`;
  - `phrases_for_country("JP")["language"] == "ja"`; `phrases_for_country("GB") is None`; `phrases_for_country("BR")["language"] == "pt"`; `phrases_for_country("zz") is None`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Draft** the file: one drafting pass, then a second model pass per language that checks meaning and register (polite, short, shown to a stranger). Fix what it flags.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): offline travel phrases for 34 languages`

### Task 13: Recap API

**Files:**
- Create: `backend/app/services/trip_recap.py`
- Modify: `backend/app/api/routes/trip_recap.py`
- Test: `backend/tests/test_trip_recap.py`

**Interfaces:**
- Consumes: Task 10 `list_places` and journal count (rebase if needed: import inside the function); Task 9 `spend_summary`; Task 2 `add_countries`, `list_countries`; Task 6 helpers; Task 1 `on_recap_complete`.
- Produces: `build_recap(plan: dict, *, places: list[dict], journal_count: int, checkin_days: int, spend: dict, user_country_codes: set[str], today: date) -> dict` (pure; `new` = the trip's countries not in `user_country_codes`, or those first added by this plan) and `haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float`. The routes follow the contract. `complete` sets `recap_completed_at`, calls `add_countries(..., source="recap")` and passes the newly added codes to the hook.

- [ ] **Step 1: Write failing tests**:
  - `test_not_ready_before_end` (409, and also with no dates);
  - `test_complete_twice_same_completed_at`;
  - `test_new_countries_only_first_time` (a second trip to PT → `new_countries == []`);
  - `test_distance_two_points` (38.7000,−9.1400 → 38.7090,−9.1400 ≈ 1.0 km ± 0.05);
  - `test_no_coordinates_distance_null`;
  - `test_route_capped_500`;
  - `test_avg_stars_ignores_null`;
  - `test_spend_passthrough`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): trip recap and completion`

### Task 14: Check-in API

**Files:**
- Create: `backend/app/db/trip_checkins_db.py`
- Modify: `backend/app/api/routes/trip_today.py`
- Test: `backend/tests/test_trip_checkin.py`

**Interfaces:**
- Consumes: Task 6 `resolve_today`, `trip_dates`, `day_index`, `city_for_day`, `country_of`; Task 2 `add_countries`; Task 1 `on_trip_checkin`.
- Produces: `checkins_db.add(plan_id, day, city, country_code) -> bool` (created) and `list_days(plan_id) -> list[str]`. The routes follow the contract. A repeat check-in reads the stored city and country and calls no hook.

- [ ] **Step 1: Write failing tests**:
  - `test_checkin_out_of_trip_409`;
  - `test_checkin_day_too_far_422` (2 days from the UTC date);
  - `test_checkin_accepts_client_day_ahead_of_utc`;
  - `test_checkin_idempotent`;
  - `test_multi_city_day_city` (Lisbon 3 / Porto 2 → day 4 is Porto);
  - `test_new_country_once_per_user`;
  - `test_hook_receives_new_countries`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(trips): daily trip check-in`

### Task 15: Game rules and Phase 2 hooks (+ traveller type, bucket goal)

**Files:**
- Modify: `backend/app/game/rules.json` (the contract rules, badges and the `trip_checkin` streak), `backend/app/game/trip_hooks.py` (bodies), `backend/app/api/routes/account.py` (`put_account_onboarding`: when `traveller_type` is set, call `on_traveller_type` and merge its delta into `game`), `backend/app/db/user_settings_db.py` (`bucket_list_goal`), `frontend/src/i18n/locales/<lang>/game.json` (`rules.<id>`, `badges.<id>.name|desc` for every new id, in 7 languages)
- Test: `backend/tests/test_trip_hooks.py`, `backend/tests/test_game_engine.py` (extend), `backend/tests/test_account_api.py` (extend)

**Interfaces:**
- Consumes: Phase 1 `engine.award`, `engine.touch_streak`; Task 6 `continent_of`; Task 2 `list_countries`.
- Produces:
  - Hook bodies per the contract's idempotency keys. `on_trip_checkin` awards `trip_checkin`, `touch_streak(user_id, "trip_checkin", day)`, one `country_visited` per new country, and one `continent_visited` per continent that the new countries add (computed against `list_countries` before the insert).
  - `merge_deltas(*deltas: dict | None) -> dict | None`: summed `awards`, concatenated `badges`, the last `xp`, and a `level_up` from the first `from` to the last `to`.
  - Every hook catches its own errors, logs them and returns an empty delta, so a game failure never breaks a trip route.
  - `Settings.bucket_list_goal: int | None` (`ge=1, le=250`).

- [ ] **Step 1: Write failing tests**:
  - `test_rules_file_validates`;
  - `test_catalog_lists_new_badges`;
  - `test_plan_saved_cap_3_per_day`;
  - `test_checkin_awards_country_and_continent_once`;
  - `test_streak_kind_trip_checkin`;
  - `test_traveller_type_awarded_once_via_onboarding`;
  - `test_hook_failure_returns_empty_delta`;
  - `test_bucket_goal_bounds` (0 → 422, 30 ok, `null` ok);
  - `test_game_disabled_hooks_return_none`;
  - the catalogue parity test covers the `game` additions.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** the backend suite and `cd frontend && npm test -- src/i18n` → PASS.
- [ ] **Step 5: Commit** `feat(game): phase 2 journey rules, badges and hooks`

## Wave 1 — frontend modules (API mocked)

Each UI task: works in light and dark mode at 360 px and 1280 px, adds `data-tid` on every control, emits its Task 3 events through `telemetry/client.emit` (fire-and-forget), and renders nothing when `useJourney().enabled` is false.

### Task 16: Trips hub (namespace `trips`)

**Files:**
- Create: `frontend/src/components/trips/{TripCard,NextTripPanel,CreateTripDialog,BucketRing}.jsx`, `frontend/src/i18n/locales/<lang>/trips.json`
- Modify: `frontend/src/pages/TripsPage.jsx`
- Test: `frontend/src/pages/TripsPage.test.jsx`

**Interfaces:**
- Consumes: Task 4 `listTrips`, `createTrip`, `getPrep`, `getTripStats`, `tripPath`; Phase 1 `useAccountSettings` (`hide_game`, `bucket_list_goal`).
- Produces:
  - The pinned trip comes first in `NextTripPanel`, with a "what now" line per phase: Dreaming "Pick dates" / "Plan it"; Planning "{{percent}} % planned"; Ready "Next: {{item}} by {{date}}" (the first `todo` item from `getPrep`); On the road "Day {{day}} in {{city}}" + Open Today; Memories "Relive your trip" + Open recap.
  - Sections follow phase order.
  - Empty state: "Plan a trip" (→ `/explore`) and "Save an idea" (→ `CreateTripDialog`: title, optional destination).
  - `BucketRing` shows `countries.length / bucket_goal` (hidden when `hide_game` or without a goal).
  - Emits `trip_view{surface:'hub'}` and `trip_action{action:'create'}`.
- [ ] **Step 1: Write failing tests**:
  - cards grouped in phase order;
  - the pinned on-the-road trip shows "Day 3 in Lisbon";
  - creating a Dreaming trip adds a card under Dreaming;
  - `getPrep` is called only for the pinned trip;
  - a network failure shows Retry;
  - the bucket ring is hidden with `hide_game`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): trips hub with phase groups and next-trip panel`

### Task 17: Trip screen and overview (namespace `trip`)

**Files:**
- Create: `frontend/src/components/trips/{TripHeader,TripTabs,PhaseMenu,TripDatesDialog}.jsx`, `frontend/src/journey/tripTabs.js`, `frontend/src/i18n/locales/<lang>/trip.json`
- Modify: `frontend/src/pages/TripPage.jsx`, `frontend/src/components/trips/TripOverview.jsx`, `frontend/src/components/PlanViewModal.jsx` (a new `inline = false` prop renders the body without the backdrop, the close button or focus trapping; the existing callers are unchanged)
- Test: `frontend/src/pages/TripPage.test.jsx`, `frontend/src/journey/tripTabs.test.js`, `frontend/src/components/PlanViewModal.test.jsx` (new: the `inline` render)

**Interfaces:**
- Consumes: Task 4 `getTrip`, `patchTrip`, `deleteTrip`, `setPendingPlan`, `setPendingSearchData`, `showResults`; Task 21 `useOfflinePack(userId, tripId)` and `useOnline()` (rebase if they have not merged: guard with optional chaining); the tab components (stubs).
- Produces:
  - `tabsFor(phase: string) -> {tabs: string[], default: string}`:

    | phase | tabs (in order) | default |
    |---|---|---|
    | dreaming | overview | overview |
    | planning | overview, prep, money, offline | overview |
    | ready | prep, overview, offline, money | prep |
    | on_the_road | today, offline, money, journal, overview | today |
    | memories | recap, journal, money, overview | recap |

    Any tab in `TRIP_TABS` stays reachable by URL.
  - `TripHeader`: title (rename inline), dates, countdown or "Day n of N", phase chip with `PhaseMenu` (override, or "Follow my dates").
  - `TripOverview`: `<CompletenessMeter surface="trip">` in Planning, then `PlanViewModal inline`, then "Open in planner" (`setPendingPlan(plan)`, `setPendingSearchData(plan.search_data)`, `showResults()`, then navigate to `/explore`). A Dreaming trip with no search instead shows "Plan it" (navigate to `/explore` with `state.prefill = {destination}`).
  - When offline (`getTrip` rejects with `network`), the header comes from the pack and only `today` and `offline` are enabled.
- [ ] **Step 1: Write failing tests**:
  - the `tabsFor` table;
  - `/trips/3` in on_the_road opens Today;
  - a PhaseMenu override calls `patchTrip({phase})`, and "Follow my dates" calls `{phase: null}`;
  - "Open in planner" sets the pending plan and search;
  - offline with a pack → header from the pack and only the offline/today tabs;
  - the `PlanViewModal inline` render has no dialog role.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): phase-aware trip screen and overview`

### Task 18: Plan completeness meter (namespace `completeness`)

**Files:**
- Create: `frontend/src/utils/planCompleteness.js`, `frontend/src/i18n/locales/<lang>/completeness.json`
- Modify: `frontend/src/components/trips/CompletenessMeter.jsx`
- Test: `frontend/src/utils/planCompleteness.test.js`, `frontend/src/components/trips/CompletenessMeter.test.jsx`

**Interfaces:**
- Produces: `planCompleteness(selections, searchData, {visaChecked}) -> {percent: number, parts: [{id: 'flights'|'stay'|'days'|'visa'|'packing', done: boolean, fraction: number}]}`. Each part weighs 20.
  - flights: `selections.flight` or `selections.flights.length`;
  - stay: `selections.hotel`;
  - days: the share of itinerary days with at least 1 slot out of the trip's nights (≥ 1);
  - visa: the `visaChecked` flag;
  - packing: a non-empty `selections.packing_list`.
  - `percent` = `round(sum(20 × fraction))`.
- `CompletenessMeter({selections, searchData, visaChecked, surface})`: a ring with the five parts as a checklist. It emits `completeness_view` once per mount.
- [ ] **Step 1: Write failing tests**: empty → 0; everything → 100; 3 of 7 days filled → the days fraction is 3/7; missing `selections` keys don't throw; hidden with the journey off.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): plan completeness meter`

### Task 19: Prep checklist UI (namespace `prep`)

**Files:**
- Create: `frontend/src/components/trips/TripReadyBar.jsx`, `frontend/src/i18n/locales/<lang>/prep.json` (`items.<id>.title|body`, facts copy such as "{{visaType}}, apply by {{date}}", overdue, "Saved automatically when you save the offline pack")
- Modify: `frontend/src/components/trips/PrepChecklist.jsx`
- Test: `frontend/src/components/trips/PrepChecklist.test.jsx`

**Interfaces:**
- Consumes: Task 4 `getPrep`, `setPrepItem`; Phase 1 `announceGame`.
- Produces:
  - `PrepChecklist({trip, token})`: items in contract order; `na` items in a collapsed "Not needed" group; overdue items in amber; auto items without a checkbox; an optimistic toggle rolled back on error.
  - `TripReadyBar`: "Trip ready {{percent}} %". At 100 % it plays a CSS confetti burst (none under reduced motion) and the "Ready to go" state.
  - A server `game` delta goes to `announceGame`. Emits `prep_toggle` and `prep_complete`.
- [ ] **Step 1: Write failing tests**:
  - visa `na` is under "Not needed";
  - a toggle rolls back on a 500;
  - reaching complete shows "Ready to go" and calls `announceGame` with the delta;
  - reduced motion renders no `.confetti` element;
  - `offline_pack` has no checkbox.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): prep checklist quest with trip-ready bar`

### Task 20: Today view (namespace `today`)

**Files:**
- Create: `frontend/src/components/trips/{NextUpCard,PassportStamp}.jsx`, `frontend/src/utils/today.js`, `frontend/src/utils/mapsLinks.js`, `frontend/src/i18n/locales/<lang>/today.json`
- Modify: `frontend/src/components/trips/TodayView.jsx`
- Test: `frontend/src/utils/today.test.js`, `frontend/src/utils/mapsLinks.test.js`, `frontend/src/components/trips/TodayView.test.jsx`

**Interfaces:**
- Consumes: `arrangeItinerary`, `scheduleDays`, `timeRange` (existing); Task 4 `checkIn`, `listCheckins`, `putPlace`, `placeKey`; Task 6 `dayIndex`, `localToday`; Task 21 `useOfflinePack`, `useOnline`, `outbox.enqueue`; Phase 1 `announceGame`.
- Produces:
  - `todaySlots(arrangedDays, dayIndex) -> slot[]`; `nextUp(scheduledSlots, now: Date) -> slot | null` (the first slot whose derived end is after `now`).
  - `directionsUrl({lat, lng, name}, {apple: boolean}) -> string`: Apple `https://maps.apple.com/?daddr=<lat>,<lng>&dirflg=w`, Google `https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>&travelmode=walking`. Without coordinates, use the name as the `q`/`destination` (URL-encoded). `apple` is true on iOS/iPadOS user agents.
  - `TodayView({trip, token})`: day header "Day n in City", a "Check in for today" button (shows the streak afterwards; `new_country` plays the `PassportStamp`), `NextUpCard`, the day's slots with derived times, Directions, and "I went here" (`putPlace` with visited, which goes through the outbox when offline), a "Share status" button (`navigator.share({text: 'Day 3 in Lisbon'})`, else copy), and "Near me" (→ `/nearby`).
  - Offline, the itinerary comes from the pack. Before or after the trip it shows "Today starts on {{date}}".
- [ ] **Step 1: Write failing tests**:
  - `nextUp` at 13:05 picks the afternoon slot;
  - Google and Apple URLs, and the name-only fallback;
  - check-in shows the streak and the stamp when `new_country` (none under reduced motion);
  - **renders without itinerary**;
  - offline "I went here" enqueues the request;
  - day 0 / after the end shows the start-date message.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): Today view with next-up, check-in and directions`

### Task 21: Offline infrastructure (namespace `offline`)

**Decision:** a hand-written service worker plus IndexedDB, with no Workbox and no new dependency.
- `/sw.js` is same-origin, so `script-src 'self'` and `worker-src 'self'` already allow it.
- The existing Caddy SPA handle serves it with `Cache-Control: no-cache`.
- The worker caches only the app shell and the hashed `/assets/*`. Pack data lives in IndexedDB.
- Navigations go network-first, so a deploy shows up whenever the user is online.
- It is registered only when the user saves a pack (never at app start), and `features.offline_pack: false` unregisters it everywhere.

**Files:**
- Create: `frontend/public/sw.js`, `frontend/vite/swAssets.js`, `frontend/src/offline/{registerSW,packStore,outbox,idb}.js`, `frontend/src/offline/useOfflinePack.js`, `frontend/src/offline/useOnline.js`, `frontend/src/i18n/locales/<lang>/offline.json`, `deploy/gcp/tests/test_caddyfile_spa.py`
- Modify: `frontend/vite.config.js` (adds `swAssetsPlugin({version: appVersion})`), `frontend/src/context/AuthContext.jsx`, `frontend/src/components/offline/OfflineBanner.jsx`
- Test: `frontend/src/offline/sw.test.js` (loads `public/sw.js` into a `node:vm` context with fake `self`, `caches` and `fetch`), `frontend/src/offline/{packStore,outbox,registerSW}.test.js` (`fake-indexeddb` is **not** added; `idb.js` falls back to an in-memory map that the tests use), `frontend/vite/swAssets.test.js`, `frontend/src/context/AuthContext.offline.test.jsx`

**Interfaces:**
- Produces:
  - `swAssetsPlugin({version}) -> VitePlugin`. It emits `sw-assets.json` = `{"version", "shell": ["/", "/index.html", "/theme-init.js", "/favicon.svg", "/manifest.webmanifest"], "assets": ["/assets/…"]}`. The list holds every emitted `.js`/`.css` chunk and every locale chunk, with no `.map` files and no file over 2 MB.
  - `sw.js`:
    - On the `precache` message, it fetches `/sw-assets.json` (`no-store`), caches every URL into `voyager-shell-<version>`, deletes the other `voyager-shell-*` caches and replies `{ok, bytes}`.
    - Navigation requests: network first; on failure, the cached `/index.html`.
    - `/assets/*`: cache first, then network.
    - Everything else, `/api/*` included, is not intercepted.
    - The `purge` message deletes every `voyager-*` cache.
  - `registerSW.js`: `ensureServiceWorker() -> Promise<ServiceWorkerRegistration | null>` (null when unsupported, not a secure context, or `import.meta.env.DEV`), `precacheShell() -> Promise<{ok: boolean, kb: number}>` and `disableOffline() -> Promise<void>` (purge plus unregister).
  - `packStore.js`: `savePack(userId, pack)`, `getPack(userId, tripId)`, `listPacks(userId)`, `deletePack(userId, tripId)`, `clearUser(userId)`, `storageMode() -> 'idb' | 'memory'`.
  - `outbox.js`:
    - `enqueue(userId, {method, path, body, key})` (a repeated `key` replaces the entry);
    - `flush(token, userId, fetchImpl = fetch) -> Promise<{sent, failed, dropped}>`: single-flight; 2xx and 409 are sent; other 4xx except 408/429 are dropped; 5xx and network errors are kept;
    - `pending(userId) -> Promise<number>`;
    - `startAutoFlush(getToken, getUserId) -> stop` (on `online` and every 60 s while items are queued). It emits `outbox_flush`.
  - `useOnline() -> boolean`; `useOfflinePack(userId, tripId) -> {pack, savedAt, loading}`.
  - `AuthContext`:
    - When `/auth/me` *rejects* (a network error), it keeps the token, restores the user from `tp_user_cache` (`{id, username, display_name, is_admin}`, written on every successful load) and exposes `offline: true`. It revalidates on `online`. HTTP 401/403 behave as today.
    - `logout()` and `session_revoked` call `clearUser(user.id)` and `outbox` clearing for that user, and remove `tp_user_cache`.
    - When `/config` says `features.offline_pack === false`, it calls `disableOffline()` once.
  - `OfflineBanner`: "You're offline. Saved trips still work." Plus "{{count}} changes waiting to sync" from `pending`.
  - `test_caddyfile_spa.py`: the CSP contains `script-src 'self'` and `worker-src 'self' blob:`; `/sw.js` does not match the `@asset` immutable matcher; the SPA handle sets `Cache-Control "no-cache"`.

- [ ] **Step 1: Write failing tests**:
  - **navigation falls back to the cached shell**; `/api/trips` is not intercepted; `/assets/a.js` is served from the cache; `precache` deletes the old version caches;
  - the plugin lists the chunks and skips maps;
  - **keeps the session when /auth/me fails offline**; a 401 still signs out; logout clears that user's packs and outbox but not another user's;
  - **concurrent flushes send each item once**; a 5xx is kept, a 400 is dropped, a 409 counts as sent;
  - `offline_pack false` → `disableOffline` is called;
  - the Caddyfile test.
- [ ] **Step 2: Run** `cd frontend && npm test -- src/offline vite src/context` and `python3 -m pytest -q deploy/gcp/tests/test_caddyfile_spa.py` → FAIL.
- [ ] **Step 3: Implement**; translate. **Step 4: Run** both, plus `npm run build` (`dist/sw.js` and `dist/sw-assets.json` exist) → PASS.
- [ ] **Step 5: Commit** `feat(offline): service worker shell, IndexedDB packs, outbox and offline-safe session`

### Task 22: Offline pack UI (namespace `offlinePack`)

**Files:**
- Create: `frontend/src/components/trips/{AddressCard,CurrencyConverter,PhraseList,EmergencyNumbers}.jsx`, `frontend/src/utils/converter.js`, `frontend/src/i18n/locales/<lang>/offlinePack.json`
- Modify: `frontend/src/components/trips/OfflinePack.jsx`
- Test: `frontend/src/utils/converter.test.js`, `frontend/src/components/trips/OfflinePack.test.jsx`

**Interfaces:**
- Consumes: Task 4 `getOfflinePack`; Task 21 `savePack`, `getPack`, `deletePack`, `ensureServiceWorker`, `precacheShell`, `useOnline`.
- Produces:
  - `convert(amount: number, rate: number, direction: 'toLocal' | 'toHome') -> number` and `roundFor(currency, value)`.
  - `OfflinePack({trip, token})`:
    - Save / Refresh / Remove, with "Saved {{when}}" and the size. The save order is: fetch the pack → `savePack` → `ensureServiceWorker` → `precacheShell` → `navigator.storage?.persist?.()`.
    - Without a service worker it still saves the data and says "Works while this tab stays open".
    - Emergency numbers as large `tel:` links, with the source label ("From our reference list" or "Checked {{date}}").
    - `PhraseList` with romanized text and a full-screen "Show" view.
    - `AddressCard` in large type with "Please take me to:" in the local script.
    - `CurrencyConverter` with "Rate from {{date}}, approximate". When `rate` is `null` it says so, with no converter.
  - Emits `offline_pack`.
- [ ] **Step 1: Write failing tests**:
  - convert both ways, and JPY rounding to whole yen;
  - Save calls the steps in order and shows "Saved";
  - unsupported service worker → the data is still saved plus the tab note;
  - offline renders from the store;
  - `rate null` → no converter;
  - Remove deletes it.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): offline pack — emergency, phrases, address card, converter`

### Task 23: Expenses UI (namespace `expenses`)

**Files:**
- Create: `frontend/src/components/trips/ExpenseForm.jsx`, `frontend/src/utils/money.js`, `frontend/src/i18n/locales/<lang>/expenses.json`
- Modify: `frontend/src/components/trips/ExpenseLog.jsx`
- Test: `frontend/src/utils/money.test.js`, `frontend/src/components/trips/ExpenseLog.test.jsx`

**Interfaces:**
- Consumes: Task 4 `listExpenses`, `addExpense`, `updateExpense`, `deleteExpense`; Task 21 `outbox`, `useOnline`.
- Produces:
  - `currencyExponent(code) -> number` (the contract table) and `toAmountString(input: string, currency) -> string | null` (accepts a locale comma decimal, and returns `null` when invalid).
  - `ExpenseLog({trip, token})`: a quick-add form (amount, currency defaulting to the pack's local currency or USD, category chips, an optional note, the day defaulting to today), a list grouped by day, totals per currency, and a "≈ {{usd}} of {{budget}} budget" bar labelled as an estimate. Edit and delete are supported.
  - Offline, or on a network error, an entry gets a `crypto.randomUUID()` `client_id`, is enqueued, and shows "Waiting to sync".
  - Emits `expense_action`.
- [ ] **Step 1: Write failing tests**:
  - `"12,50"` in de → `"12.50"`; JPY `"12.5"` → `null`;
  - an add while offline queues one item with a `client_id` and shows "Waiting to sync";
  - the budget bar uses `usd_estimate`;
  - unconverted currencies are listed.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): offline-friendly expense log`

### Task 24: Journal and place ratings UI (namespace `journal`)

**Files:**
- Create: `frontend/src/components/trips/{JournalEntryForm,RatingStars,PlaceRatingsList}.jsx`, `frontend/src/i18n/locales/<lang>/journal.json`
- Modify: `frontend/src/components/trips/Journal.jsx`
- Test: `frontend/src/components/trips/Journal.test.jsx`, `frontend/src/components/trips/RatingStars.test.jsx`

**Interfaces:**
- Consumes: Task 4 journal and places calls, `placeKey`; Task 21 `outbox`; `arrangeItinerary` (for the places to rate).
- Produces:
  - `Journal({trip, token})`: entries by day, a mood picker, and a counter at 4000 characters. Offline writes are queued.
  - `PlaceRatingsList`: the itinerary places plus the visited ones, each with `RatingStars`.
  - `RatingStars({value, onChange})`: a radio group with arrow keys, labelled "{{n}} of 5 stars".
  - Emits `journal_action` and `place_action` (no text and no names).
- [ ] **Step 1: Write failing tests**:
  - the counter blocks at 4001 characters;
  - an offline add queues the request;
  - the arrow keys change the rating;
  - rating a place calls `putPlace` with the `placeKey`;
  - `place_action` carries no name.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): journal and place ratings`

### Task 25: Recap UI (namespace `recap`)

**Files:**
- Create: `frontend/src/components/trips/{RecapMap,CountryReveal,RecapStats,WhereNext}.jsx`, `frontend/src/utils/recapRoute.js`, `frontend/src/i18n/locales/<lang>/recap.json`
- Modify: `frontend/src/components/trips/Recap.jsx`
- Test: `frontend/src/utils/recapRoute.test.js`, `frontend/src/components/trips/Recap.test.jsx`

**Interfaces:**
- Consumes: Task 4 `getRecap`, `completeRecap`; `discoverDestinations` (api.js); `computePlanCost`; `arrangeItinerary`, `scheduleDays`; Phase 1 `announceGame`; existing `POST /plans/{id}/share`.
- Produces:
  - `plannedRoute(arrangedDays) -> {points: [lat, lng][], km: number | null}`. It is used when `recap.route` is empty, and labelled "Planned route".
  - `Recap({trip, token})`:
    - stats (days, places, distance, countries, journal entries, average stars);
    - spend versus budget (`spent_usd` against `budget_usd` and the client `plan_cost_usd`, labelled as estimates; unconverted currencies listed);
    - `RecapMap` (Leaflet, lazy-loaded, polyline);
    - "Finish recap" when `can_complete` → `completeRecap` → `announceGame` + `CountryReveal` (a stamp per new country; reduced motion → a static list);
    - "Share" (creates or reuses the share link, then `navigator.share({title, text: '7 days in Lisbon · 23 places', url})`, else copy);
    - `WhereNext`, which calls `discoverDestinations` only when tapped, with the trip's interests and budget, filters out the current destination and shows the 5 suggestions linking to `/explore`.
    - Before the trip ends: "Your recap appears after {{date}}".
  - Emits `recap_action`.
- [ ] **Step 1: Write failing tests**:
  - `plannedRoute` skips slots without coordinates and returns `km: null` with one point;
  - Finish → reveal and `announceGame`; a repeat shows no reveal;
  - Where next fires no request until tapped;
  - Share falls back to copy;
  - the not-ready message.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): trip recap with route, countries and where-next`

### Task 26: Shared onboarding (namespace `onboarding`, adds web keys only)

**Files:**
- Create: `frontend/src/components/onboarding/{QuizStep,TravellerTypeResult,HomePassportStep,NotificationsStep,FirstTripStep,OnboardingProgress}.jsx`, `frontend/src/utils/travellerQuiz.js`, `frontend/src/utils/quizPreferences.js`
- Modify: `frontend/src/pages/OnboardingPage.jsx`, `frontend/src/components/onboarding/OnboardingGate.jsx`, `frontend/src/i18n/locales/<lang>/onboarding.json` (adds `web.*`: airport and passport labels, "Not you? Change answers", "Saving…", "Continue without syncing", "Your browser blocks notifications", "Allow notifications", resume copy; no existing key changes)
- Test: `frontend/src/utils/travellerQuiz.test.js`, `frontend/src/utils/quizPreferences.test.js`, `frontend/src/pages/OnboardingPage.test.jsx`

**Interfaces:**
- Consumes:
  - the question/weight table and the rules in Android `docs/Onboarding-and-Traveller-Types.md` (`rupakc/travel-planner-android`; copy the classifier cases from `DefaultTravellerClassifierTest` and the merge cases from the `PreferencesMapping` tests);
  - Phase 1 `getAccount`, `putOnboarding`, `announceGame`;
  - `GET/PUT /api/preferences` (existing);
  - `AirportSearch`, `NationalitySearch`.
- Produces:
  - `QUESTIONS` (6, with Android's ids, choice kinds and weights) and `classify(answers: Record<string, string[]>) -> {primary: TravellerType, secondary: TravellerType[]}`. The rules are tie order, secondary at ≥ 60 %, ACCESSIBLE appended, and CULTURE_FOODIE when nothing scored.
  - `mergeQuizAnswers(prefs, answers) -> prefs` (the Android merge rules) and `quizPace(answers) -> string | null`.
  - `OnboardingPage`, in 5 steps with the `onboarding:*` keys and order:
    1. welcome;
    2. how you travel (6 question pages, then the result);
    3. home airport + passport;
    4. notifications: `Notification.requestPermission()` only after "Allow"; skipped when unsupported;
    5. first trip (→ `/explore`) or explore (→ `/`).
  - Each step sends `putOnboarding({step, done: false})` fire-and-forget, and the page resumes from `onboarding.step`. Answers stay in `localStorage.tp_quiz_<user_id>`.
  - Finish: `PUT /api/preferences` (read-modify-write; on failure, Retry or "Continue without syncing"), then `putOnboarding({step: 5, done: true, traveller_type: primary.toLowerCase()})` → `announceGame`. Skip: `{step, done: true, skipped: true}`.
  - Emits `onboarding_step` and `onboarding_result`.
  - `OnboardingGate`: when the journey is on, signed in, `getAccount().onboarding.done === false`, the path is not `/onboarding` and `sessionStorage.tp_onboarding_seen` is unset, it navigates to `/onboarding` once. A 404 or error from `/account` does nothing.
- [ ] **Step 1: Write failing tests**:
  - every Android classifier case;
  - the merge cases (the default party is replaced, a custom party is kept, infants have a minimum of 1, `num_travelers` is clamped to 1–20);
  - resume at step 3;
  - Skip sends `skipped: true`;
  - the notification permission is requested only after Allow;
  - the gate redirects once and never on a 404.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate the new keys. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(onboarding): shared 5-step onboarding with traveller type on web`

### Task 27: Journey coach marks (namespace `coach`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/coach.json`
- Modify: `frontend/src/components/trips/JourneyTour.jsx`
- Test: `frontend/src/components/trips/JourneyTour.test.jsx`

**Interfaces:**
- Consumes: the existing `OnboardingTour` and `useFirstRunTour({username, visible, eligible, delayMs})` (no `token`, so the tour never reports onboarding); the `data-tour` anchors from Task 4 (`nav-trips`, `nav-explore`, `nav-alerts`, `nav-play`, `nav-you`) plus `trips-create` (Task 16).
- Produces: `JourneyTour({username, visible, onboardingDone})`, which opens once after onboarding is done and is replayable from You ("Show me around").
- [ ] **Step 1: Write failing tests**: it doesn't open before onboarding is done; it opens once; a missing anchor's step is skipped.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): coach marks for the journey tabs`

### Task 28: Play and You tabs (namespace `playYou`)

**Files:**
- Create: `frontend/src/components/play/{CountriesVisited,BucketGoalEditor}.jsx`, `frontend/src/i18n/locales/<lang>/playYou.json`
- Modify: `frontend/src/pages/PlayPage.jsx`, `frontend/src/pages/YouPage.jsx`
- Test: `frontend/src/pages/PlayPage.test.jsx`, `frontend/src/pages/YouPage.test.jsx`

**Interfaces:**
- Consumes: Phase 1 `GameSection`, `patchSettings`, `useAccountSettings`; Task 4 `getTripStats`; the existing `AccountPage` sections; Task 27 replay.
- Produces:
  - `PlayPage`: `GameSection`, the trip check-in streak, `CountriesVisited` (flag emoji from the ISO code, the name via `Intl.DisplayNames`, continents) and `BucketGoalEditor` (1–250 → `patchSettings({bucket_list_goal})`). With `hide_game` it shows a single note linking to Settings.
  - `YouPage`: the `AccountPage` sections, then links to Preferences, Alerts and "Show me around".
- [ ] **Step 1: Write failing tests**: countries render with their names; the goal editor saves; `hide_game` shows only the note; You links to `/preferences`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): Play and You tabs`

### Task 29: Explore entry and mode tabs on phones (namespace `explore`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/explore.json`
- Modify: `frontend/src/pages/SearchPage.jsx`
- Test: `frontend/src/pages/SearchPage.explore.test.jsx`

**Interfaces:**
- Consumes: Task 4 `useJourney`.
- Produces:
  - With the journey on, an "Explore" header and the mode row Search / Surprise me / Compare / From a link / Chat (→ `/chat`) / Near me (→ `/nearby`).
  - `location.state.prefill.destination` prefills the destination.
  - The Phase 1 search tour is not started (Task 27 replaces it).
  - Follow-up fix in both flag states: the mode tabs never wrap. The row is `overflow-x-auto whitespace-nowrap snap-x` with no `flex-wrap`, and the active tab is scrolled into view.
- [ ] **Step 1: Write failing tests**:
  - the mode container has `overflow-x-auto` and no `flex-wrap` (in `de` and `bn`);
  - with the journey on, the Chat chip navigates to `/chat`;
  - the prefill sets the destination;
  - the search tour stays closed with the journey on.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): Explore entry; mode tabs scroll instead of wrapping`

### Task 30: Dark contrast of muted text (follow-up)

**Files:**
- Modify: `frontend/design/tokens.json` (dark `gray-400`, `slate-400` and `slate-500`), `frontend/src/theme/tokens.css` (regenerated with `node frontend/scripts/build-tokens.mjs`), `frontend/src/theme/tokens.test.js`, `frontend/src/components/ui/AttributionFooter.jsx` (`text-gray-400` → `text-gray-500`)

**Interfaces:**
- Produces: the dark `gray-400` and `slate-400` reach ≥ 4.5:1 on dark `white` (cards) and `gray-50` (page). White on `teal-700` reaches ≥ 4.5 in both modes (this pins Task 38). Light-mode values are unchanged.
- [ ] **Step 1: Write failing tests**: those three contrast pairs, and `the generated CSS equals the committed tokens.css`.
- [ ] **Step 2: Run** `cd frontend && npm test -- src/theme` → FAIL.
- [ ] **Step 3: Implement**, then regenerate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `fix(theme): readable muted text in dark mode`

### Task 31: "Voyager" naming and web manifest (follow-up)

**Files:**
- Create: `frontend/public/manifest.webmanifest` (`name` "Voyager", `short_name` "Voyager", `start_url` "/", `display` "standalone", `background_color`/`theme_color` from the light tokens, `icons` `[{src: "/favicon.svg", sizes: "any", type: "image/svg+xml"}]`)
- Modify: `frontend/index.html` (`<title>Voyager — plan, travel, remember</title>`, `<link rel="manifest" href="/manifest.webmanifest">`), `frontend/src/pages/LoginPage.jsx` and `SignupPage.jsx` (the `<h1>` reads "Voyager"), `frontend/src/i18n/locales/<lang>/chat.json` (`title` → "Voyager Chat" in 7 languages)
- Test: `frontend/src/branding.test.js`

**Interfaces:**
- Produces: no "Travel Planner" in `frontend/src` or `index.html`, except the iCalendar `PRODID` in `utils/planExport.js` (kept for calendar stability).
- [ ] **Step 1: Write failing tests**: a grep-style test over `src/**` and `index.html`, with the allow-list; the manifest parses with `name === 'Voyager'`; the LoginPage heading.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `fix(brand): Voyager everywhere, web manifest`

### Task 32: Feedback pill in dark mode and on phones (follow-up)

**Files:**
- Modify: `frontend/src/components/FeedbackWidget.jsx`, `frontend/src/components/account/AccountMenu.jsx`
- Test: `frontend/src/components/FeedbackWidget.test.jsx`

**Interfaces:**
- Produces:
  - The pill is `bg-teal-700 hover:bg-teal-800 text-white` (dark-safe).
  - On phones (< 640 px) the floating pill is hidden.
  - AccountMenu gains a "Feedback" item (reusing the existing `misc:feedback.trigger` key) that dispatches `window` event `voyager:open-feedback`, which `FeedbackWidget` listens for.
  - On ≥ 640 px the pill stays bottom-left, with `bottom-20` when `BottomTabs` is present.
- [ ] **Step 1: Write failing tests**: the event opens the panel; the pill has `hidden sm:flex`; it has no `slate-700` class.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `fix(ui): feedback pill readable in dark and out of the way on phones`

### Task 33: Lazy English namespaces (follow-up, performance)

**Files:**
- Create: `frontend/src/i18n/routeNamespaces.js`
- Modify: `frontend/src/i18n/index.js`, `frontend/src/components/I18nRouteGate.jsx`, `frontend/src/test/setup.js` (calls `initI18n({bundleAll: true})`, so tests stay synchronous)
- Test: `frontend/src/i18n/routeNamespaces.test.js`, `frontend/src/components/I18nRouteGate.test.jsx`, `frontend/src/i18n/index.test.js` (extend)

**Interfaces:**
- Produces:
  - `EAGER_NS = ['common', 'errors', 'auth', 'journey', 'offline', 'misc']` stays in the main bundle. Every other `en` namespace becomes a lazy chunk through the existing `lazyBackend`.
  - `namespacesFor(pathname) -> string[]` (for example `/trips/:id/today` → `['trip', 'today', 'prep', 'completeness', 'offlinePack', 'expenses', 'journal', 'recap', 'game']`).
  - `I18nRouteGate({pathname, children})` calls `i18n.loadNamespaces(namespacesFor(pathname))`. It renders a neutral skeleton until they load, and renders anyway after 3 s or on failure.
  - `initI18n({bundleAll})` keeps the eager glob for tests.
- [ ] **Step 1: Write failing tests**:
  - every namespace is in `EAGER_NS` or returned by `namespacesFor` for at least one known path;
  - the gate shows the skeleton, then its children;
  - a rejected chunk still renders its children;
  - `NAMESPACES` is unchanged.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Record the entry chunk's gzip size before and after (`npm run build`) in the PR description.
- [ ] **Step 4: Run** `npm test` and `npm run build` → PASS.
- [ ] **Step 5: Commit** `perf(i18n): lazy-load English namespaces per route`

## Wave 2 — integration

### Task 34: Results page integration (+ dark top bar)

**Files:**
- Create: `frontend/src/utils/tripSnapshot.js`
- Modify: `frontend/src/pages/ResultsPage.jsx`
- Test: `frontend/src/utils/tripSnapshot.test.js`, `frontend/src/pages/ResultsPage.trips.test.jsx`

**Interfaces:**
- Consumes: Task 4 `putSnapshot`, `tripPath`, `useJourney`, `pendingPlan`, `clearPendingPlan`, `journey:saved.*`; Task 18 `CompletenessMeter`.
- Produces:
  - `snapshotFromResults(results) -> {emergency_card, forex, visa, packing_list, weather}`. Each value is the section's data when it has no `error`; `verification` is removed; otherwise `null`.
  - `MyPlanDrawer`:
    - `<CompletenessMeter surface="drawer" visaChecked={visa loaded without error}>` under the plan name.
    - After a successful save or update, `putSnapshot` runs fire-and-forget, and any rejection is ignored (the old backend 404s).
    - With the journey on, the save message gains a link "Open trip", to `tripPath(id)` (the id from the POST response, or `loadedPlanId`).
  - `ResultsPage`: when `pendingPlan` is set and the current search was started from its `search_data`, it calls `handleLoadPlan(pendingPlan)` once, then `clearPendingPlan()`.
  - The stress-test re-check payload gains `plan_id: loadedPlanId` when set (the old backend ignores it).
  - Follow-up: the top bar and the drawer header use `bg-gradient-to-r from-teal-700 to-teal-800` instead of `from-slate-500 to-slate-600`.
- [ ] **Step 1: Write failing tests**:
  - `snapshotFromResults` drops error sections and `verification`;
  - a save calls `putSnapshot` with the new id;
  - a `putSnapshot` rejection shows no error;
  - "Open trip" shows only with the journey on;
  - a pending plan loads once;
  - the re-check payload includes `plan_id`;
  - the top bar has no `slate-500` class.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `npm test` → PASS.
- [ ] **Step 5: Commit** `feat(journey): results page saves trips with snapshot and completeness`

### Task 35: Chat page integration

**Files:**
- Modify: `frontend/src/pages/ChatPage.jsx`
- Test: `frontend/src/pages/ChatPage.trips.test.jsx`

**Interfaces:**
- Consumes: Task 34 `snapshotFromResults` (from `utils/tripSnapshot.js`); Task 4 `putSnapshot`, `tripPath`, `useJourney`; Task 18 `CompletenessMeter`.
- Produces: the chat plan drawer's save and update send `putSnapshot` built from the chat's section results (`section_result` data), skipped when there are none. They show "Open trip" with the journey on, and the drawer shows `CompletenessMeter`.
- [ ] **Step 1: Write failing tests**: a save with section results sends the snapshot; a save without them sends none; "Open trip" appears only with the journey on.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): chat plans save as trips`

### Task 36: Near me "I'm here" during a trip (namespace `nearbyTrip`)

**Files:**
- Create: `frontend/src/i18n/locales/<lang>/nearbyTrip.json`
- Modify: `frontend/src/pages/NearbyPage.jsx`
- Test: `frontend/src/pages/NearbyPage.trip.test.jsx`

**Interfaces:**
- Consumes: Task 4 `listTrips`, `putPlace`, `placeKey`; Phase 1 `announceGame`.
- Produces: when the pinned trip is `on_the_road`, each result gets "I'm here" → `putPlace(tripId, placeKey('nearby', name), {name, kind: 'nearby', visited: true, lat, lng, day: localToday()})` → `announceGame`, and the button becomes "Visited". Without such a trip, or with the journey off, nothing changes. It emits `today_action{action:'visited'}`.
- [ ] **Step 1: Write failing tests**: the button appears only with an on-the-road trip; a tap sends the visit with coordinates; journey off → no `listTrips` call.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; translate. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(journey): mark Near me places visited during a trip`

### Task 37: Backend joins (stress-test smart planner, offline-pack tick)

**Files:**
- Modify: `backend/app/api/routes/stress_test.py` (an optional `plan_id: int | None` on `StressTestRequest`, plus `get_optional_user`), `backend/app/api/routes/trip_offline.py` (a successful `GET offline-pack` → `trip_prep_db.set_done(plan_id, "offline_pack", True)`, then the `trip_ready` check through `prep_summary` and `on_trip_ready`; the response is unchanged)
- Test: `backend/tests/test_stress_test_plan.py`, `backend/tests/test_offline_pack.py` (extend)

**Interfaces:**
- Consumes: Task 8 `trip_prep_db.get_meta/set_meta/set_done`, `prep_summary`; Task 1 `owned_trip`, `on_smart_planner`, `on_trip_ready`.
- Produces:
  - After the agent returns, when `plan_id` is set and the caller owns the plan, the server reads the score from the result (`overall_score`, else `score`, an int from 0 to 100). It stores `{"score"}` as the `stress_test` meta, marks the item done, and calls `on_smart_planner` when the score is higher than the previous one.
  - Every failure in this block is logged and swallowed, so the response is exactly the agent's.
- [ ] **Step 1: Write failing tests** (stub the agent):
  - an improved score calls the hook once, and an equal score doesn't;
  - another user's `plan_id` is ignored;
  - anonymous → no write;
  - the response body is unchanged;
  - the pack GET ticks `offline_pack`, and completing the list through it awards `trip_ready`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(trips): stress-test progress and offline-pack prep tick`

## Wave 3 — sweep, docs, review, switch on

### Task 38: Primary buttons to teal-700 (follow-up sweep)

**Files:** every file under `frontend/src` with a `bg-teal-600` primary button (25 files at the time of writing; `grep -rl "bg-teal-600" frontend/src`).
- [ ] **Step 1:** Replace `bg-teal-600` with `bg-teal-700` and `hover:bg-teal-700` with `hover:bg-teal-800` on elements whose classes also contain `text-white`. Leave tinted chips, borders and rings alone. A test, `frontend/src/theme/primaryButtons.test.js`, fails when any `.jsx` file has `bg-teal-600` together with `text-white` in one className.
- [ ] **Step 2: Run** `npm test`, eslint and `npm run build` → PASS. Take before and after screenshots of Search, Results and Account in both themes.
- [ ] **Step 3: Commit** `fix(theme): primary buttons on teal-700 for AA contrast`

### Task 39: Docs and CLAUDE.md sync

**Files:**
- Modify:
  - `CLAUDE.md`: the table count and list, with the 7 new tables added to whatever the count is when this task runs; the router count and list, with the 7 new trip routers added; the Trips/journey paragraph (phases, prep, offline pack, expenses, journal, recap, flag); the new settings; the project layout (`components/trips`, `offline/`, `public/sw.js`).
  - `docs/Configuration.md`: every Task 1 setting.
  - `docs/API-Reference.md`: the trips endpoints, linking `Trips-API.md`.
  - `docs/Deployment-GCP.md`: an "Offline pack" section: the service worker is `/sw.js`; the kill switch is `OFFLINE_PACK_ENABLED=false`, which unregisters clients on their next load; `JOURNEY_UI_ENABLED`.
  - `docs/Privacy.md`: trip data, expenses and journal stored on the server, ratings and visits, countries visited, offline packs in the browser (cleared on sign-out), no location history.
  - `docs/Feature-Parity.md`: journey rows, Web ✅, Android ⏳ 8, iOS ⏳ 7.
  - `docs/Frontend.md`: the new pages and folders.
  - `docs/Internationalization.md`: the new namespaces; English is lazy per route.
  - `docs/Theming.md`: teal-700 primary.
  - `docs/Changelog.md`.
- [ ] **Step 1:** Write. **Step 2:** `mkdocs build --strict` → PASS. **Step 3: Commit** `docs: journey, trips, offline pack`

### Task 40: Translation review

**Files:** `frontend/src/i18n/locales/{es,de,fr,hi,zh,bn}/{journey,errors,trips,trip,completeness,prep,today,offline,offlinePack,expenses,journal,recap,onboarding,coach,playYou,explore,nearbyTrip,game,chat}.json`, `backend/app/data/travel_phrases.json`
- [ ] **Step 1:** Run one fresh reviewer per UI language. Each reads `en` alongside, then fixes meaning, register and length: buttons over 1.6× the English length are shortened, and phase names must fit a chip at 360 px. Run a separate phrases reviewer per script family that checks that every phrase is polite and right for showing to a stranger.
- [ ] **Step 2:** `npm test` and `python3 -m pytest -q backend/tests/test_phrases.py` → PASS. **Step 3: Commit** `fix(i18n): phase 2 translation review`

### Task 41: Browser end-to-end, mixed versions and review passes

- [ ] **Step 1:** With the `verify` skill, run locally with `tp_journey=1` and walk through this list:
  1. Onboarding → the traveller-type badge.
  2. Explore search → save the plan → "Open trip" → the trip in Planning with completeness.
  3. Set the dates to tomorrow → Ready, then prep tick-through → confetti and the `trip_ready` badge.
  4. Save the offline pack, then, in Chrome DevTools offline mode, reload `/trips/<id>/offline` → the pack renders while signed in.
  5. Log an expense offline → back online → one row.
  6. Set the dates to cover today → Today → check-in (stamp, streak) → "I went here".
  7. Set the dates to the past → Recap → Finish (countries reveal, XP).
  8. Sign out → IndexedDB is empty.

  Take screenshots in light, dark and `de`/`bn` at 375 px and 1280 px.
- [ ] **Step 2:** Mixed versions:
  - the SPA from `origin/main` against the new backend: plans list, load, update, delete and share all work, including a Dreaming trip;
  - the new SPA against the `origin/main` backend: the classic shell, no `/sw.js` registration, no console errors.
- [ ] **Step 3:** Run three review passes on the combined diff: spec compliance (this plan + spec §3/§3a/§5a/§9), correctness and security (`/code-review high`, focused on the Review Focus list, ownership checks on every trip route, and IndexedDB clearing), and UX/visual (the screenshots). Fix what they find, then re-run every suite.
- [ ] **Step 4:** Write the deferred minors to `docs/superpowers/plans/2026-11-12-phase2-followups.md`.

### Task 42: Switch on the journey UI

**Files:**
- Modify: `backend/app/core/config.py` (`journey_ui_enabled: bool = True`), `backend/tests/test_client_config.py` (the default is now `True`), `docs/Configuration.md` (the default), `docs/Changelog.md`
- [ ] **Step 1:** Change the default, and update the test to expect `features.journey is True` by default and `False` with `JOURNEY_UI_ENABLED=false`.
- [ ] **Step 2: Run** the backend suite and `mkdocs build --strict` → PASS.
- [ ] **Step 3: Commit** `feat(journey): turn on the journey UI by default`. The owner can still turn it off with `JOURNEY_UI_ENABLED=false` in `app.env`, with no rebuild.

## Execution waves

Each wave starts when the previous one has merged to main. Inside a wave every task runs in its own worktree in parallel, because the tasks own disjoint files (see the hotspot table).

| Wave | Tasks (parallel) | Count | Gate |
|---|---|---|---|
| **0 — seams and contract** | 1 backend seams · 2 schema + migration · 3 telemetry · 4 frontend seams · 5 contract doc · 6 phase/geo helpers + golden cases | 6 | Task 1's last step rebases on Task 2. When wave 0 merges, the contract is frozen and the iOS/Android teams start against `docs/Trips-API.md` |
| **1 — modules** | backend: 7 trips core · 8 prep · 9 expenses · 10 journal + places · 11 offline pack · 12 phrases · 13 recap · 14 check-in · 15 game rules + hooks; frontend: 16 hub · 17 trip screen · 18 completeness · 19 prep UI · 20 Today · 21 offline infra · 22 pack UI · 23 expenses UI · 24 journal UI · 25 recap UI · 26 onboarding · 27 coach marks · 28 Play/You · 29 Explore + tabs; follow-ups: 30 dark contrast · 31 naming · 32 feedback pill · 33 lazy English | 27 | Backend tasks need only wave 0, through the stubs. Tasks 11 and 13 import Task 9/10 helpers inside functions, so their merge order doesn't matter. Frontend tasks need only Task 4, with the API mocked. Tasks 17, 20, 22, 23 and 24 import Task 21's offline modules: merge 21 first inside the wave, or guard the imports per the task |
| **2 — integration** | 34 Results · 35 Chat · 36 Near me · 37 backend joins | 4 | 34 needs 18; 35 needs 34's `tripSnapshot.js` (start it once 34's util is pushed, or merge 34 first); 37 needs 8 and 11 |
| **3 — finish** | 38 teal sweep → then 39 docs ∥ 40 translation review (one agent per language) → 41 E2E + reviews → 42 switch on | 5 (+6 reviewers) | 38 runs alone first (it touches 25 files). 42 merges only after 41 is green |

Merge cadence: a PR per task, or one per wave. Each PR is green and deployable on its own. The wave 1 backend routes have no UI pointing at them, the UI is invisible until `features.journey` is on, and the service worker registers only when a user saves a pack, which they can't do until the journey UI is visible. Task 42 is a one-line config change that the owner can revert in `app.env`.

## Deferred (later phases)

- Scratch-map *visual* (country polygons) and the head-to-head quizzes: Phase 5. Phase 2 shows the visited countries as a list in Play.
- Saving or remixing ideas from the community feed (the Dreaming touch): Phase 5.
- Share cards for the recap and status (1080×1920 / 1200×630 images, OG pages): Phase 4. Phase 2 shares a link and text.
- Price-alert gamified touches: Phase 3.
- Push notifications for trip phases (T-30 visa, T-7 packing, morning brief): Phase 6.
- Region badges for UNESCO sites seen and cuisines tried, which need data we don't have.
- Local-script hotel addresses (shown only when a source provides them).
- Android and iOS clients of this contract: Phases 8 and 7.
