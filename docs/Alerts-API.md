# Alerts API

> Frozen with Phase 3 wave 0. **Changes:** later changes are additive only (new fields, endpoints or error codes; nothing renamed, removed or re-typed). Every change needs a contract-change note in its PR and an update to this page in the same PR.

Price alerts 2.0 adds a **price story** for each watch, a **drop moment** on real drops, a **savings tally**, one-tap watches, suggestions, a weekly digest and delivery controls (quiet hours, caps, grouping). It is additive to `/api/fare-watches*`, `/api/price-watches*` and `/api/notifications*`, which keep their request fields, response keys and semantics.

## API contract

All paths are under `/api`, with JSON in and out. Every route needs `Authorization: Bearer <access_token>` and acts only on the caller's watches: another user's watch answers `404 watch_not_found`. Errors use the Phase 1 envelope `{"detail", "error_code"}`, and timestamps are ISO 8601 UTC with `Z`. `kind` is one of `flight | hotel | activity | trip`. `flight` means a `fare_watches` row, and the other kinds are `price_watches` rows.

### Discovery (additive)

`GET /config` gains `features.alerts_api: 2` (the routes below exist), `features.price_alerts_v2: bool` (`PRICE_ALERTS_V2_ENABLED`) and `features.live_prices: bool` (a SerpAPI key is configured).

### Shared objects

`Money`: `{"amount": 412.0, "currency": "USD"}`.

`PriceStory`:
```json
{"kind": "flight", "watch_id": 7, "currency": "USD", "mode": "below_target", "target": 380.0,
 "points": [{"at": "…Z", "price": 455.0}], "baseline": 455.0,
 "latest": {"at": "…Z", "price": 412.0}, "lowest": {"at": "…Z", "price": 398.0},
 "typical": {"low": 390.0, "high": 520.0, "source": "google"},
 "verdict": "good", "advice": {"code": "near_target", "params": {"gap": 32.0}},
 "checked_at": "…Z", "checked_days_ago": 0, "next_check_at": "…Z", "pending_first_check": false,
 "estimate": null, "caught": 57.0, "live_prices": true}
```

- `points`: observed prices only, oldest first, at most 90 (the newest).
- `typical`: for flights, Google's `google_typical_low/high` (`source: "google"`), and `null` when Google gave none. For other kinds, when there are at least 6 points, the nearest-rank p25 and p75 of the points (`source: "history"`), otherwise `null`. Nearest rank: sort the `n` prices, then `p25 = sorted[ceil(0.25 n) - 1]` and `p75 = sorted[ceil(0.75 n) - 1]`.
- `verdict`, for the latest price `p` and typical `[lo, hi]`: `p < lo` is `great`; `p <= lo + 0.25 (hi - lo)` is `good`; `p <= hi` is `typical`; otherwise `high`. It is `null` without `typical` or `latest`, and `null` when `checked_days_ago > 3` and `live_prices` is false. A stale no-key story still shows `typical`.
- `estimate`: `{"price", "source"}` for a frozen estimate (labelled "estimate"), else `null`. An estimate is never a point, never `latest`, and never changes the verdict.
- `caught`: the watch's saving as defined under Savings, or `null`.
- `advice.code`: the first rule that matches, in this order:

| # | Code (params) | Matches when |
|---|---|---|
| 1 | `pending` | there is no observed point yet (including a watch that holds only an estimate) |
| 2 | `checks_paused {days}` | `live_prices` is false and `checked_days_ago > 3`; `days` is `checked_days_ago` |
| 3 | `below_target {by}` | a target is set and latest <= target; `by` = target - latest |
| 4 | `near_target {gap}` | a target is set and latest - target <= the kind's step evaluated at the **target** (`price_rules`: flight and hotel max($15, 5 %), activity max(1, 5 %), trip max($25, 4 %)); `gap` = latest - target |
| 5 | `at_lowest` | latest == lowest and there are at least 3 points |
| 6 | `below_typical`, `within_typical`, `above_typical` | the verdict is great or good, typical, or high |
| 7 | `steady {days}` | at least 5 points and the last 5 are within 1 % of each other (`max - min <= 0.01 min`); `days` is the whole days from the 5th-newest point to the newest |
| 8 | `few_checks {n}` | otherwise; `n` is the number of points |

Golden cases: `backend/tests/fixtures/alerts/story_cases.json`, shared by every client (see Golden cases).

`Savings`:
```json
{"total_usd": 245.0, "by_currency": {"EUR": 12.0}, "drops_caught": 4, "targets_hit": 1,
 "watches_active": 6, "best": {"kind": "hotel", "watch_id": 3, "title": "…", "caught": 120.0, "currency": "USD"},
 "milestones": [50, 200, 1000], "next_milestone": 1000, "progress_pct": 24, "since": "…Z"}
```

- A watch's **caught** amount = `max(0, baseline - the lowest alerted observed price)`, taken from `alert_savings` rows. Repeat alerts on one watch count once, through their lowest price. Estimate rows (`observed: false`) are ignored everywhere. A watch is identified by `(kind, watch_id)`, so a flight 1 and a hotel 1 are two watches.
- Watches are summed: USD watches into `total_usd`, other currencies into `by_currency` (only amounts above 0, rounded to 2 decimals). Nothing is ever converted.
- `drops_caught` = the number of watches with `caught > 0`. `targets_hit` = the number of those with at least one `target_hit` alert.
- `best` = the watch with the largest `caught`, USD watches first (a non-USD watch is `best` only when no USD watch has a saving), ties to the lower `watch_id`; `null` when no watch has a saving.
- `next_milestone` = the smallest milestone strictly above `total_usd` (so a total of exactly 50 has passed 50), and `null` once $1,000 is reached. `progress_pct` = `floor(100 * total_usd / next_milestone)`, and 100 when `next_milestone` is `null`.
- Deleted watches still count. `since` is the first counted row's time, `null` with none. `watches_active` is the count of the caller's active watches, from the watch stores, not from the rows.
- Wording: always "caught a drop of $X", never "you saved" (the app cannot know whether the user booked).

Golden cases: `savings_cases.json`.

`AlertPrefs`:
```json
{"digest_weekly": false, "digest_push": false, "digest_day": 1, "instant": "all",
 "quiet_hours": {"enabled": true, "start": "22:00", "end": "07:00"},
 "daily_cap": {"flight": 3, "hotel": 3, "activity": 3, "trip": 3}, "group_window_min": 15,
 "timezone": "Asia/Kolkata", "quiet_hours_active": true}
```

- `digest_weekly` is the opt-in for the weekly digest (in-app and email). `digest_push` (bool, default `false`) additionally sends the digest as a push; it has no effect while `digest_weekly` is false.
- `digest_day` is an ISO weekday (1 = Monday).
- `instant` is `all` or `targets_only`. With `targets_only`, only target hits push or email, and everything else waits for the digest.
- Caps run from 1 to 10 and `group_window_min` from 0 to 120. `start` and `end` are `HH:MM`.
- `timezone` is read-only here, a mirror of the account setting (`null` when unset). Without a usable timezone, quiet hours are not applied, and `quiet_hours_active` is `false`. It is also `false` when quiet hours are disabled (`enabled: false`, or `start == end`).

### Routes

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /alerts/summary` | none | `Savings` | none |
| `GET /alerts/watches/{kind}/{id}/story` | none | `PriceStory` | `404 watch_not_found`, `422 kind_invalid` |
| `POST /alerts/watches/{kind}/{id}/advice` | none | `{"tip": "…", "source": "ai", "generated_at": "…Z", "cached": bool}`. Uses the pricing-advisor agent with the stored history (no SerpAPI) and is cached 24 h per watch. The `light_ai` bucket and the AI gate apply | `422 advice_unsupported` (not `flight`), `503 ai_limit`, `404` |
| `POST /alerts/quick-watch` | `{"kind", "title": 1..120, "subtitle"?: <=160, "spec": {…}, "plan_id"?: int, "surface": "results"\|"chat"\|"trip"\|"suggest"}`. A flight `spec` holds the `POST /fare-watches` trip fields. The other kinds hold their `POST /price-watches` `spec` | `201 {"kind", "watch": Watch, "existing": false}`. The watch is pending: `alert_mode: any_drop`, email off, no live look, first check queued. A match of an existing active watch answers `200` with `"existing": true` | `503 live_prices_off`, `409 watch_limit` (the shared active limit, with the existing message), `422 spec_invalid` |
| `GET /alerts/suggestions?plan_id=` | none | `{"suggestions": [{"kind", "title", "subtitle", "spec", "reason": "selected_in_plan"\|"trip_total"\|"departure_soon", "already_watching": bool}], "live_prices": bool}`, at most 5, built locally | `404 trip_not_found` |
| `GET /alerts/preferences` | none | `AlertPrefs` | none |
| `PUT /alerts/preferences` | any subset of the writable `AlertPrefs` keys (everything except `timezone` and `quiet_hours_active`) | `AlertPrefs` | `422 alert_prefs_invalid` |
| `GET /alerts/digest/unsubscribe?token=` and `POST` | none | HTML page (the same pattern as the watch unsubscribe pages); sets `digest_weekly=false` | none |

**Watch objects (additive).** Every watch from `/fare-watches*` and `/price-watches*` gains `pending_first_check: bool`. A pending watch has `last_price: null`.

**Notifications (additive).**

- A drop notification's `data` gains `drop: {"from", "to", "amount", "pct", "currency", "target_hit": bool, "observed": true}` and `game: GameDelta | null`.
- The new kind `price_digest` has the usual `title` and `body` plus `data.digest: {"week": "2026-W46", "watches": [{"kind", "watch_id", "title", "latest", "change_7d", "lowest", "checked_at"}], "savings": Savings}`.
- A grouped push carries `data.group_count` (a string).

`GameDelta` is exactly as in [Accounts API](Accounts-API.md).

### Delivery rules (push and email only)

The in-app notification row is always written. For each new notification, in order:

1. `expired` and `error` notes are delivered as today.
2. `instant = targets_only` and not `target_hit`: no push or email.
3. The category's sent count today (the user's local day) >= `daily_cap[kind]`: no push or email.
4. Local time in quiet hours (`[start, end)`, wrapping midnight; `start == end` means disabled; skipped without a timezone): due at the next local `end`.
5. Otherwise due now. If a push for this user went out less than `group_window_min` ago, the item is held until that window ends and is sent then as **one** push covering every item held for that user ("3 prices dropped").

Email keeps the per-watch `email_enabled` opt-in and follows rules 1 to 4, never grouping.

**Quiet-hours details (rule 4).** The local time of day is `HH:MM` in the user's `timezone`. A window with `start < end` holds when `start <= t < end`. A window with `start > end` wraps midnight and holds when `t >= start` or `t < end`. The end is exclusive: at exactly `end` the item is due now. The due time is the next wall-clock `end` in the local zone, converted to UTC, so a DST change between now and then is honoured (7:00 after a spring-forward night is one hour earlier in UTC than the night before). An unknown timezone name is treated like no timezone.

Golden cases: `quiet_hours_cases.json`.

## Golden cases

`backend/tests/fixtures/alerts/{story_cases,savings_cases,quiet_hours_cases}.json`. Each file is a list of `{"name", "input", "expected"}` with unique names. Every backend implementation and every client must pass them.

- **`story_cases.json`**: `input` is `{"kind", "currency", "target", "points": [{"days_ago", "price"}] (oldest first), "google_typical": [lo, hi] | null, "live_prices", "checked_days_ago": int | null, "pending_first_check", "estimate"}`. `expected` is `{"typical", "verdict", "advice": {"code", "params"}, "lowest", "latest"}` (`lowest` and `latest` are prices, or `null` without points). Numbers compare by value (`2` equals `2.0`).
- **`savings_cases.json`**: `input` is `{"rows": [{"kind", "watch_id", "title", "currency", "baseline", "alerted_price", "notification_id", "at", "target_hit", "observed", "watch_deleted"}], "watches_active"}`. `expected` is the full `Savings` object.
- **`quiet_hours_cases.json`**: `input` is `{"now_utc", "timezone": string | null, "quiet_hours": {"enabled", "start", "end"}}`. `expected` is `{"deliver": "now" | "held", "due_utc"}`; `due_utc` equals `now_utc` when `deliver` is `now`.

## Client notes

- **Feature detection.** Read `features.alerts_api` from `GET /config`. Without it (an older backend) render today's Alerts page and no v2 control. v2 controls show when `features.price_alerts_v2` is true, or `features.alerts_api === 2` and the browser has `localStorage.tp_alerts2 = "1"`. Never assume a route exists without the flag.
- **No live prices.** When `features.live_prices` is false there is no one-tap watch button and no suggestions sheet (`quick-watch` answers `503 live_prices_off`). Stories, savings and the digest still work from stored data.
- **"Checked N days ago".** Every price is shown with its age from `checked_days_ago` (and `checked_at`). Never present a stale price as current. With `advice.code = checks_paused`, say live checks are paused. Never say "great price now".
- **Codes to translate.** `advice.code` (with `params`), `verdict`, `suggestions[].reason`, and the error codes `watch_not_found`, `kind_invalid`, `advice_unsupported`, `ai_limit`, `live_prices_off`, `watch_limit`, `spec_invalid`, `trip_not_found` and `alert_prefs_invalid`. The server sends codes and numbers, never English advice text. Format amounts, dates and "N days ago" with the locale.
- **No live calls from clients.** Clients never call SerpAPI or any price source. Every number comes from these routes.
- **Estimates and currencies.** An `estimate` is labelled "estimate" and never counts as a price, a saving or XP. Never convert currencies: show `total_usd` and list `by_currency` separately.
- **Old data.** Pending watches (`last_price: null`), `price_digest` notifications and drop `data` with extra keys must not break a client that does not know them.

## Fake SerpAPI (tests, dev, E2E)

The real SerpAPI is never used in tests, dev or E2E (the Free Plan has 250 searches a month). `backend/scripts/fake_serpapi.py` serves `/search.json` from `backend/tests/fixtures/serpapi/`, routed by `engine`:

| `engine` | Fixture |
|---|---|
| `google_flights` | `flights/outbound.json`, or `flights/return_leg.json` when `departure_token` is given |
| `google_hotels` | `hotels/city_search_lisbon.json`, or `hotels/property_details_browns.json` when `property_token` is given |
| `google` | `activities/gyg_belem_tower_recheck.json` |

```bash
cd backend
python -m scripts.fake_serpapi --port 8765 [--drop-after N]
curl http://127.0.0.1:8765/__calls        # {"total": 3, "by_engine": {"google_flights": 3}}
```

With `--drop-after N`, every search after the first N serves prices 12 % lower (so an end-to-end run sees a real drop). To run the backend against it, use the launcher, which patches `serp_flights.SERP_URL`, `serp_flights._SERP_URL`, `hotel_prices.SERP_URL` and `activity_prices.SERP_URL` before importing `app.main`:

```bash
SERPAPI_KEY=fake FAKE_SERPAPI_URL=http://127.0.0.1:8765/search.json \
  python -m scripts.run_with_fake_serpapi --port 8001
```

The key is a dummy. The fake never reads, stores or logs the query.
