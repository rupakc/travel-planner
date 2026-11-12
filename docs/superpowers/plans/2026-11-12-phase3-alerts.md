# Phase 3 — Price alerts 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make price alerts a delight. Each watch gets a **price story**: an interactive chart, the lowest price seen, a typical range, a target slider and a plain-language verdict. A real drop becomes a **drop moment**: an animated card, a "you're saving $X" counter and XP. A **savings tally** with milestones and a shareable "I saved $X" card sums all watches. Watching gets smarter: **one-tap watch** on every card, **suggestions** when a plan is saved, an opt-in **weekly digest**, quiet hours, per-category caps and grouped pushes. Every honesty rule stays.

**Architecture:** Everything is additive to the existing fare-watch and price-watch services. One flag-gated seam in each `_notify` passes new notifications through `services/alert_pipeline.py`, which enriches `data` with drop facts, records savings, awards Deal-hunter XP and hands push and email to a delivery layer (quiet hours, caps, grouping, outbox loop). New read models (story, savings, suggestions) are pure functions over the stored rows and history, so they need **no SerpAPI call** and work in production, where there is no key. One-tap watches are created **pending** (no live look). The scheduler makes their first look, in priority order (nearest departure, closest to target), with adaptive intervals. New routes live under `/api/alerts/*`. They are frozen in `docs/Alerts-API.md` at the end of wave 0 for the iOS and Android apps. The UI stays hidden behind `features.price_alerts_v2` until the last task.

**Tech Stack:** FastAPI + SQLite (stdlib `sqlite3`), pydantic v2, `zoneinfo`; React 18, i18next, inline SVG charts, Canvas 2D for the share card, the Web Share API (no new npm or pip dependency), vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md`: §6 price alerts, §5a "Price alerts" row (Deal hunter, $50/$200/$1,000 milestones, target-hit celebration, estimates never award), §2a budget (250 SerpAPI searches a month, prioritised watches, adaptive intervals, "checked N days ago"; one-tap watch and suggestions never fire a live search), §8 telemetry, §11 Phase 3 row. Style model: `docs/superpowers/plans/2026-11-12-phase2-journey.md` and `docs/Trips-API.md`. `2026-11-12-phase2-followups.md` has no Phase 3-tagged item; its line "Price-alert gamified touches: Phase 3" (Phase 2 Deferred) is Task 5.

## Global Constraints

- **Two-way compatibility (CLAUDE.md).** Every existing route keeps its request fields, response keys and semantics: `/api/fare-watches*`, `/api/price-watches*`, `/api/notifications*` and the unsubscribe pages. New watch keys (`pending_first_check`) and new notification `data` keys (`drop`, `game`, `digest`) are extra keys that old clients ignore. A pending watch has `last_price: null`, which the old SPA already renders as "Getting price…". The new SPA works against the previous backend: with no `features.alerts_api` in `/config` it renders today's Alerts page and no v2 control.
- **Ship-alone merges.** The backend v2 behaviour (pipeline, delivery, digest loop, adaptive scheduling) runs only when `PRICE_ALERTS_V2_ENABLED=true` (`settings.price_alerts_v2_enabled`, default `false` until Task 22). With the flag off, `_notify`, email, push and `next_check` behave byte-for-byte as today. The `/api/alerts/*` read routes always exist. The web UI renders when `features.price_alerts_v2` is true, or for one browser with `localStorage.tp_alerts2 = "1"` when `features.alerts_api === 2`.
- **No SerpAPI in production.** `features.live_prices` = `bool(settings.serpapi_key)`. Without a key: the story, savings, digest and suggestions work from stored data. Every price shows "checked N days ago". One-tap watch and the suggestions sheet are hidden. `POST /alerts/quick-watch` answers `503 live_prices_off`. Nothing in the v2 code path may call SerpAPI except the scheduler's existing check functions. Tests, dev and E2E use the fake SerpAPI (Task 3), never the real key.
- **Honesty rules stay.** Estimates are labelled and frozen, and they never alert, never count toward savings and never award XP. A "saving" is always the drop between two **observed** prices, worded "caught a drop of $X", never "you saved" without "if you book now". Currencies are never converted: the USD tally counts only USD watches, and other currencies are listed separately.
- **Anti-spam.** The existing `evaluate()` rules are unchanged: one alert per check, separate own-dates and nearby-dates references, a repeat needs a further step unless a rebound re-armed it, never on the baseline, and the 24 h cooldown. Quiet hours, per-category daily caps and grouping apply only to **push and email**. The in-app notification row is always written.
- **Additive schema only.** `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE … ADD COLUMN`, nothing renamed or dropped. The new tables join the GCS user-table backup set.
- **Game guardrails (§5a).** Awards come only from server-observed alerts with observed prices. Each award has an idempotency key and a daily cap, and point values live in `game/rules.json`. `hide_game` hides every Deal-hunter element, and the game never gates a feature.
- **i18n.** Every new user-visible string is in all 7 languages (`en es de fr hi zh bn`). Each frontend task owns **one namespace**, named in its heading. The only edits to existing namespaces: `game` (Task 5) and `alerts` (Task 17, which adds keys and renames none). Use informal es/de and `vous` in fr, and never translate "Voyager". Amounts, dates and "N days ago" go through `i18n/format.js`. Advice and verdicts travel as **codes plus params**, never as English text, and clients translate them. Push, email and digest text stays English, as today, until Phase 6 adds server-side localisation.
- **Telemetry.** The Phase 3 events go into the closed registry once (Task 1). Props are enums, ints and bools only, never an amount, a price, a title or a place.
- **Motion and accessibility.** Animations (the drop card's count-up, the falling-price motif, confetti on a target hit, chart transitions) are CSS-only or `requestAnimationFrame`, and `prefers-reduced-motion: reduce` shows the final state at once. The chart is keyboard-scrubbable (←/→ between points, with an `aria-live` readout). Every interactive element has a `data-tid`, tap targets are ≥ 44 px, and primary buttons are `bg-teal-700 hover:bg-teal-800 text-white`.
- Python 3.12, `ruff check backend/` clean, `cd frontend && npx eslint src/ --max-warnings 0`, `mkdocs build --strict`. `cd backend && python3 -m pytest -q` and `cd frontend && npm test` keep passing.

## Review Focus

1. **No key, stale data.** In production, with no `SERPAPI_KEY`, a watch last checked 9 days ago must show its story, the "checked 9 days ago" label and the advice `checks_paused`, never "great price now". No one-tap button and no suggestions sheet appear, and the digest loop doesn't crash. Tests: Task 4 `test_story_without_key_says_paused`, Task 7 `test_quick_watch_503_without_key`, Task 10 `test_digest_skipped_when_no_looks_this_week`, Task 14 `hidden when live_prices is false`.
2. **Estimates and currencies leak into savings.** A trip watch with frozen estimate parts, a hotel watch that holds only an estimate, and a EUR activity drop. Expected: the estimate contributes nothing, and EUR shows under `by_currency`, not in `total_usd`. Tests: Task 5 `test_estimate_never_counts_or_awards`, `test_eur_drop_not_in_usd_total`.
3. **Quiet hours at the edges.** A drop at 23:30 in Asia/Kolkata (quiet 22:00–07:00) is pushed at 07:00 local. A New York watch on the spring-forward night does the same. With no timezone, delivery is immediate. A quiet window with start = end is treated as disabled. Golden cases in Task 3 (`quiet_hours_cases.json`), run by Task 6 `test_quiet_hours_golden`.
4. **Mixed versions.** The old SPA and the Android app on the new backend list pending watches (null prices), `price_digest` notifications and drops with extra `data` keys without error. The new SPA on the old backend shows the classic Alerts page. Tests: Task 7 `test_pending_watch_keeps_legacy_shape`, Task 10 `test_digest_notification_has_legacy_fields`, Task 2 `old backend keeps the classic alerts page`.
5. **Doubles and races.** A double tap on one-tap creates one watch. A retried `_notify` writes one savings row and one award. Two flush passes send a grouped push once. A restart mid-Monday sends the digest once. Tests: Task 7 `test_quick_watch_twice_returns_existing`, Task 5 `test_record_idempotent_per_notification`, Task 6 `test_flush_claims_each_item_once`, Task 10 `test_digest_once_per_week_across_restart`.

---

## API contract (frozen at the end of wave 0; published as `docs/Alerts-API.md`)

All paths are under `/api`, with JSON in and out. Every route needs `Authorization: Bearer <access_token>` and acts only on the caller's watches: another user's watch answers `404 watch_not_found`. Errors use the Phase 1 envelope `{"detail", "error_code"}`, and timestamps are ISO 8601 UTC with `Z`. `kind` ∈ `flight | hotel | activity | trip`. `flight` means a `fare_watches` row, and the other kinds are `price_watches` rows.

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
- `typical`: for flights, Google's `google_typical_low/high` (`source: "google"`). For other kinds, when there are ≥ 6 points, the nearest-rank p25/p75 of the points (`source: "history"`). Otherwise `null`.
- `verdict`, for the latest price `p` and typical `[lo, hi]`: `p < lo` → `great`; `p ≤ lo + 0.25 (hi − lo)` → `good`; `p ≤ hi` → `typical`; else `high`. It is `null` without `typical` or `latest`, and `null` when `checked_days_ago > 3` and `live_prices` is false.
- `estimate`: `{"price", "source"}` for a frozen estimate (labelled "estimate"), else `null`.
- `caught`: the watch's saving as defined under Savings, or `null`.
- `advice.code`: the first rule that matches, in this order:
  1. `pending` — there is no look yet.
  2. `checks_paused {days}` — `live_prices` is false and `checked_days_ago > 3`.
  3. `below_target {by}` — latest ≤ target.
  4. `near_target {gap}` — latest − target ≤ the kind's step (`price_rules`).
  5. `at_lowest` — latest == lowest and ≥ 3 points.
  6. `below_typical`, `within_typical` or `above_typical` — the verdict is great/good, typical or high.
  7. `steady {days}` — the last 5 points are within 1 % of each other.
  8. `few_checks {n}` — otherwise.

Golden cases: `backend/tests/fixtures/alerts/story_cases.json`, shared by every client.

`Savings`:
```json
{"total_usd": 245.0, "by_currency": {"EUR": 12.0}, "drops_caught": 4, "targets_hit": 1,
 "watches_active": 6, "best": {"kind": "hotel", "watch_id": 3, "title": "…", "caught": 120.0, "currency": "USD"},
 "milestones": [50, 200, 1000], "next_milestone": 1000, "progress_pct": 24, "since": "…Z"}
```
A watch's **caught** amount = `max(0, baseline − the lowest alerted observed price)`, taken from `alert_savings` rows. Watches are summed: USD watches into `total_usd`, other currencies into `by_currency`. Nothing is ever converted. `progress_pct` = `floor(100 × total_usd / next_milestone)`, and `next_milestone` is `null` once $1,000 is passed. Deleted watches still count, and `since` is the first row's time. Golden cases: `savings_cases.json`.

`AlertPrefs`:
```json
{"digest_weekly": false, "digest_day": 1, "instant": "all",
 "quiet_hours": {"enabled": true, "start": "22:00", "end": "07:00"},
 "daily_cap": {"flight": 3, "hotel": 3, "activity": 3, "trip": 3}, "group_window_min": 15,
 "timezone": "Asia/Kolkata"}
```
- `digest_day` is an ISO weekday (1 = Monday).
- `instant` is `all` or `targets_only`. With `targets_only`, only target hits push or email, and everything else waits for the digest.
- Caps run from 1 to 10 and `group_window_min` from 0 to 120.
- `timezone` is read-only here, a mirror of the account setting. Without it, quiet hours are not applied (the response says so with `"quiet_hours_active": false`).

### Routes

| Method, path | Request | Success | Errors |
|---|---|---|---|
| `GET /alerts/summary` | — | `Savings` | — |
| `GET /alerts/watches/{kind}/{id}/story` | — | `PriceStory` | `404 watch_not_found`, `422 kind_invalid` |
| `POST /alerts/watches/{kind}/{id}/advice` | — | `{"tip": "…", "source": "ai", "generated_at": "…Z", "cached": bool}`. Uses the pricing-advisor agent with the stored history (no SerpAPI) and is cached 24 h per watch. `light_ai` bucket and the AI gate apply | `422 advice_unsupported` (not `flight`), `503 ai_limit`, `404` |
| `POST /alerts/quick-watch` | `{"kind", "title": 1..120, "subtitle"?: ≤160, "spec": {…}, "plan_id"?: int, "surface": "results"\|"chat"\|"trip"\|"suggest"}`. A flight `spec` holds the `POST /fare-watches` trip fields. The other kinds hold their `POST /price-watches` `spec` | `201 {"kind", "watch": Watch, "existing": false}`. The watch is pending: `alert_mode: any_drop`, email off, no live look, first check queued. A match of an existing active watch answers `200` with `"existing": true` | `503 live_prices_off`, `409 watch_limit` (the shared active limit, with the existing message), `422 spec_invalid` |
| `GET /alerts/suggestions?plan_id=` | — | `{"suggestions": [{"kind", "title", "subtitle", "spec", "reason": "selected_in_plan"\|"trip_total"\|"departure_soon", "already_watching": bool}], "live_prices": bool}`, at most 5, built locally | `404 trip_not_found` |
| `GET /alerts/preferences` | — | `AlertPrefs` | — |
| `PUT /alerts/preferences` | any subset of the writable `AlertPrefs` keys | `AlertPrefs` | `422 alert_prefs_invalid` |
| `GET /alerts/digest/unsubscribe?token=` / `POST` | — | HTML page (the same pattern as the watch unsubscribe pages); sets `digest_weekly=false` | — |

**Watch objects (additive).** Every watch from `/fare-watches*` and `/price-watches*` gains `pending_first_check: bool`.

**Notifications (additive).**
- A drop notification's `data` gains `drop: {"from", "to", "amount", "pct", "currency", "target_hit": bool, "observed": true}` and `game: GameDelta | null`.
- The new kind `price_digest` has the usual `title`/`body` plus `data.digest: {"week": "2026-W46", "watches": [{"kind", "watch_id", "title", "latest", "change_7d", "lowest", "checked_at"}], "savings": Savings}`.
- A grouped push carries `data.group_count` (a string).

`GameDelta` is exactly as in `docs/Accounts-API.md`.

### Delivery rules (push and email only)

For each new notification, in order:
1. `expired` and `error` notes are delivered as today.
2. `instant = targets_only` and not `target_hit` → no push or email.
3. The category's sent count today (the user's local day) ≥ `daily_cap[kind]` → no push or email.
4. Local time in quiet hours (`[start, end)`, wrapping midnight; start = end means disabled; skipped without a timezone) → due at the next local `end`.
5. Otherwise due now. If a push for this user went out less than `group_window_min` ago, the item is held until that window ends and is sent then as **one** push covering every item held for that user ("3 prices dropped").

Email keeps the per-watch `email_enabled` opt-in and follows rules 1–4, never grouping.

---

## Shared-file hotspots

| Hotspot | Rule |
|---|---|
| `core/config.py`, `main.py`, `api/routes/client_config.py`, `telemetry/registry.py`, `docs/Telemetry.md`, `db/alerts_db.py` (schema) | Only Task 1. |
| `services/fare_watch.py`, `services/price_watch.py` | Task 1 (the `_notify` and email seams), Task 7 (pending create and first look), Task 8 (scheduling). They are in different waves. |
| `db/fare_watch_db.py`, `db/price_watch_db.py` | Task 7 (`pending_first_check`, match) and Task 8 (`due_watch_ids` ordering). They are in different waves. |
| `services/alert_email.py` | Task 6 (delivery calls) and Task 10 (the digest template). They are in different waves. |
| `game/rules.json`, `game/alert_hooks.py` (bodies), `locales/*/game.json` | Only Task 5. |
| `services/alert_{story,moments,delivery,digest,suggest,schedule,pipeline}.py`, `api/routes/alerts.py` | Task 1 creates stubs with the final signatures. Each later task fills only its own. |
| `frontend/src/services/alertsApi.js`, `hooks/useAlertsV2.js`, `i18n/index.js`, `i18n/routeNamespaces.js`, `App.jsx`, `AlertsPage.jsx` (slots), `WatchCard.jsx` (slot) | Only Task 2. |
| `frontend/src/context/AlertsContext.jsx` | Only Task 12. |
| `ResultsPage.jsx`, `ChatPage.jsx`, `TripPage.jsx`, `PlanViewModal.jsx` | Only Task 18. |
| Docs (`CLAUDE.md`, `API-Reference.md`, `Configuration.md`, `Privacy.md`, `Feature-Parity.md`, `Frontend.md`, `Changelog.md`) | Only Task 19. Task 3 creates `docs/Alerts-API.md` and makes the only `mkdocs.yml` edit. |

---

## Wave 0 — seams and contract

### Task 1: Backend seams (settings, schema, pipeline seam, stubs, config, telemetry)

**Files:**
- Create: `backend/app/db/alerts_db.py`, `backend/app/api/routes/alerts.py`, `backend/app/services/alert_{pipeline,story,moments,delivery,digest,suggest,schedule}.py`, `backend/app/game/alert_hooks.py`
- Modify: `core/config.py`, `main.py`, `api/routes/client_config.py`, `services/fare_watch.py` (`_notify`, the email call near line 579), `services/price_watch.py` (`_notify`, the email call near line 679), `telemetry/registry.py`, `docs/Telemetry.md`, `db/vm_backup.py` (user tables list)
- Test: `backend/tests/test_alerts_seams.py`, `backend/tests/test_client_config.py` (extend), `backend/tests/test_telemetry_registry.py` (extend)

**Interfaces:**
- Produces:
  - Settings: `price_alerts_v2_enabled: bool = False`, `alert_digest_hour_local: int = 9`, `alert_flush_interval_s: int = 60`, `alert_advice_ttl_hours: int = 24`.
  - `create_alert_tables() -> None` (idempotent), creating:
    - `alert_prefs(user_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)`.
    - `alert_savings(id, user_id, watch_kind, watch_id, notification_id INTEGER NOT NULL UNIQUE, from_price REAL, to_price REAL, baseline REAL, currency TEXT, target_hit INTEGER, created_at)`.
    - `alert_outbox(id, user_id, notification_id, channel TEXT CHECK(channel IN ('push','email')), watch_kind, due_at TEXT, sent_at TEXT, dropped_reason TEXT, UNIQUE(notification_id, channel))`.
    - `alert_digests(user_id, week TEXT, status TEXT, sent_at, PRIMARY KEY(user_id, week))`.
    - `alert_advice(watch_kind, watch_id, tip TEXT, generated_at, PRIMARY KEY(watch_kind, watch_id))`.
  - Row helpers in `alerts_db`: `get_prefs(user_id) -> dict`, `put_prefs(user_id, data) -> dict`, `insert_saving(row: dict) -> bool`, `savings_rows(user_id) -> list[dict]`, `enqueue(user_id, notification_id, channel, watch_kind, due_at) -> bool`, `claim_due(now, limit) -> list[dict]` (marks `sent_at` atomically with `UPDATE … WHERE sent_at IS NULL`), `mark_dropped(id, reason)`, `sent_today(user_id, kind, day_start_utc, channel) -> int`, `digest_claim(user_id, week) -> bool`, `get_advice / put_advice`.
  - `alert_pipeline.enabled() -> bool`. `enrich(watch: dict, watch_kind: str, note: dict) -> dict` (stub: returns `note`). `after_insert(watch, watch_kind, row: dict, now) -> bool` (stub: `False`). Returning `True` means "v2 took over push and email".
  - Service stubs with their final signatures (bodies `raise NotImplementedError` or return empty values): `alert_story.build_story(kind, watch, history, *, live_prices, now) -> dict`; `alert_moments.drop_facts(watch_kind, watch, note) -> dict | None`, `alert_moments.record(watch_kind, watch, row) -> None`, `alert_moments.summary(user_id) -> dict`; `alert_delivery.plan(note_row, watch_kind, prefs, tz, counts, last_push_at, now) -> Decision`, `alert_delivery.dispatch(watch, watch_kind, row, now) -> None`, `alert_delivery.flush(now) -> int`, `alert_delivery.start_loop() -> asyncio.Task | None`, `alert_delivery.stop_loop(task)`; `alert_digest.run_due(now) -> int`; `alert_suggest.suggestions(plan, user) -> list[dict]`; `alert_schedule.priority(watch_kind, watch, today) -> tuple`, `alert_schedule.next_interval(watch_kind, watch, today) -> timedelta`
  - `alert_hooks.on_drop(user_id, watch_kind, watch_id, notification_id, facts: dict) -> dict | None` and `on_savings(user_id, total_usd: float) -> dict | None`, both stubs returning `None`.
  - `/config` gains `features.alerts_api: 2`, `features.price_alerts_v2` and `features.live_prices`.
  - `main.py` includes `alerts.router` (`prefix="/api"`, tag `alerts`), calls `create_alert_tables()` after `create_price_watch_tables()`, and starts/stops `alert_delivery.start_loop()` (which returns `None` when the flag is off).
  - Telemetry events (closed registry, props exactly as below; `_KIND = enum(flight,hotel,activity,trip)`): `alert_story_view {kind, verdict: enum(great,good,typical,high,none)}`; `alert_target_set {kind, from_story: bool}`; `alert_advice {kind, outcome: enum(ok,cached,error)}`; `alert_drop_seen {kind, target_hit: bool, via: enum(in_app,push,email)}`; `alert_quick_watch {kind, action: enum(add,undo,exists,blocked), surface: enum(results,chat,trip,suggest)}`; `alert_suggest {action: enum(shown,accepted,dismissed), count: int}`; `alert_savings_share {target: enum(native,download,copy)}`; `alert_prefs_change {field: enum(digest,quiet_hours,instant,cap,group)}`; `alert_digest_open {via: enum(in_app,email_link)}`

- [ ] **Step 1: Write failing tests**: `test_alert_tables_idempotent` (runs twice and asserts the columns of each table); `test_flag_off_notify_unchanged`: with the flag off, the `notifications` row and the `push.notify` and email calls are identical to today's (spy); `test_flag_on_calls_pipeline`: `enrich` runs before the insert, and when `after_insert` returns `True`, `push.notify` and the email `deliver` are not called; `test_config_alert_features`: `alerts_api == 2`; `price_alerts_v2 is False` by default; `live_prices is False` without a key and `True` with one; `test_registry_phase3_events`: each event accepts its props and drops a string `amount` prop.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alerts_seams.py tests/test_client_config.py tests/test_telemetry_registry.py` → FAIL.
- [ ] **Step 3: Implement.** In `_notify`: `if alert_pipeline.enabled(): note = alert_pipeline.enrich(watch, kind, note)`, then insert, then `if alert_pipeline.enabled() and alert_pipeline.after_insert(…): return row`. The email call site skips `deliver` when `row["data"].get("_v2")` is set. `after_insert` sets `_v2` by updating the row's data.
- [ ] **Step 4: Run** the whole backend suite and `ruff check backend/` → PASS.
- [ ] **Step 5: Commit** `feat(alerts): phase 3 backend seams — flag, tables, pipeline seam, stubs, telemetry`

### Task 2: Frontend seams (API module, flag hook, stubs, namespaces, slots)

**Files:**
- Create: `frontend/src/services/alertsApi.js`, `frontend/src/hooks/useAlertsV2.js`, `frontend/src/components/alerts2/{PriceStory,DropMoment,SavingsTally,SavingsShareCard,QuickWatchButton,WatchSuggestions,AlertPrefsPanel,AlertsV2Header,WatchCardExtras}.jsx` (each renders `null`), `frontend/src/utils/alertStory.js` (stub exports), `frontend/src/i18n/locales/{en,es,de,fr,hi,zh,bn}/{priceStory,dropMoment,savings,quickWatch,watchSuggest,alertPrefs,alertsHub}.json` (`{}`)
- Modify: `i18n/index.js`, `i18n/routeNamespaces.js` (`/alerts` loads the seven namespaces), `App.jsx` (mounts `<DropMoment/>` under the flag), `pages/AlertsPage.jsx` (`<AlertsV2Header/>` above the list when on), `components/alerts/WatchCard.jsx` (`<WatchCardExtras watch={watch}/>` slot when on)
- Test: `frontend/src/services/alertsApi.test.js`, `frontend/src/hooks/useAlertsV2.test.js`, `frontend/src/pages/AlertsPage.v2seams.test.jsx`

**Interfaces:**
- Produces:
  - `alertsApi`: `getSavings(token)`, `getStory(token, kind, id)`, `requestAdvice(token, kind, id)`, `quickWatch(token, body)`, `getSuggestions(token, planId)`, `getAlertPrefs(token)` and `putAlertPrefs(token, patch)`, each returning `.data`.
  - `useAlertsV2() -> {on: bool, livePrices: bool, source: 'config'|'override'|'off'}`, which mirrors `hooks/useJourney.js`.
  - `utils/alertStory.js` stubs: `verdictFor(price, typical)`, `adviceFor(story)`, `countAtOrBelow(points, target)`, `checkedDaysAgo(iso, now)`.
  - Component props:
    - `PriceStory {kind, watchId, onTargetChange}`
    - `DropMoment {}`
    - `SavingsTally {compact?: bool}`
    - `SavingsShareCard {savings, onClose}`
    - `QuickWatchButton {kind, title, subtitle, spec, planId?, surface}`
    - `WatchSuggestions {planId, onDone}`
    - `AlertPrefsPanel {onClose}`
    - `AlertsV2Header {}`
    - `WatchCardExtras {watch}`

- [ ] **Step 1: Write failing tests**: `alertsApi` paths and verbs (as in `priceWatchApi.test.js`). `useAlertsV2` turns on by config, by override only with `alerts_api === 2`, and is off on an old backend. `old backend keeps the classic alerts page`: no `AlertsV2Header` without `features.alerts_api`. .
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/services/alertsApi.test.js src/hooks/useAlertsV2.test.js src/pages/AlertsPage.v2seams.test.jsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): phase 3 frontend seams — api, flag, stubs, namespaces, slots`

### Task 3: Contract doc, golden cases and fake SerpAPI

**Files:**
- Create: `docs/Alerts-API.md` (the contract above, plus the client notes: feature detection, codes to translate, "checked N days ago", no live calls from clients), `backend/tests/fixtures/alerts/{story_cases,savings_cases,quiet_hours_cases}.json`, `backend/tests/fixtures/serpapi/flights/*.json`, `backend/scripts/fake_serpapi.py`, `backend/tests/test_fake_serpapi.py`
- Modify: `mkdocs.yml` (nav, after Trips API)

**Interfaces:**
- Produces:
  - The golden files. Each one is a list of `{"name", "input", "expected"}`: `story_cases.json`: ≥ 14 cases, one per advice code and verdict, including `no_key_stale_9_days`, `pending`, `hotel_history_typical_6_points` and `estimate_only`.; `savings_cases.json`: ≥ 6 cases, including `repeat_alerts_same_watch_counts_once`, `eur_separate`, `estimate_excluded` and `deleted_watch_counts`.; `quiet_hours_cases.json`: ≥ 8 cases, including `kolkata_2330_held_to_0700`, `ny_spring_forward`, `no_timezone_immediate`, `start_equals_end_disabled` and `wraps_midnight_0630_held`.
  - `fake_serpapi.py`: `python -m scripts.fake_serpapi --port 8765` serves `/search.json`. It routes by `engine` (`google_flights`, `google_hotels`, `google`) to the fixture dirs and keeps a request counter at `/__calls`. Its `--drop-after N` mode serves a price 12 % lower after N calls, so E2E sees a real drop. The doc shows how to point the backend at it, as in the memory note: patch `serp_flights.SERP_URL`, `serp_flights._SERP_URL`, `hotel_prices.SERP_URL` and `activity_prices.SERP_URL` before importing `app.main`, using a launcher `backend/scripts/run_with_fake_serpapi.py`.

- [ ] **Step 1: Write failing test** `test_fake_serpapi.py`: the fake answers each engine from the fixtures, counts calls, and lowers the price after `--drop-after`. Every golden file parses and has unique names.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_fake_serpapi.py` → FAIL.
- [ ] **Step 3: Implement** with stdlib `http.server` (no new dependency). Write the doc.
- [ ] **Step 4: Run** the test and `mkdocs build --strict` → PASS.
- [ ] **Step 5: Commit** `docs(alerts): freeze Alerts API v2, golden cases, fake SerpAPI`

---

## Wave 1 — backend core

### Task 4: Price story and advisor tip

**Files:**
- Modify: `services/alert_story.py`, `api/routes/alerts.py` (story and advice routes)
- Test: `backend/tests/test_alert_story.py`, `backend/tests/test_alerts_story_api.py`

**Interfaces:**
- Consumes: `fare_watch_db.get_watch/get_history`, `price_watch_db.get_watch/get_history`, `price_rules` steps through `price_watch.step_for(source)` (flights use `FARE_STEP`), and `PricingAdvisorAgent.run(request, avg_price=…)`.
- Produces: `build_story(kind, watch, history, *, live_prices: bool, now: datetime) -> dict` (`PriceStory`), `typical_from_points(prices: list[float]) -> dict | None`, `verdict(price, typical) -> str | None` and `advice(story_inputs) -> dict`. The routes `GET /alerts/watches/{kind}/{id}/story` and `POST …/advice`.

- [ ] **Step 1: Write failing tests**: `test_story_golden`: every case in `story_cases.json`; `test_story_without_key_says_paused` (9 days old, no key → `checks_paused {days: 9}`, `verdict` null); `test_points_capped_at_90_oldest_first`; `test_estimate_story_has_no_verdict`; `test_story_404_other_user`; `test_story_makes_no_network_call` (httpx is patched to raise); `test_advice_flight_cached_24h` (the second call has `cached: true`, and the agent is called once); `test_advice_hotel_422`; `test_advice_spend_cap_503`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alert_story.py tests/test_alerts_story_api.py` → FAIL.
- [ ] **Step 3: Implement.** The advisor prompt uses the stored `latest`/`lowest`/`typical` as `avg_price`. Store the tip in `alert_advice`, and pass the user's locale through `locale_kw`.
- [ ] **Step 4: Run** → PASS, then the whole suite.
- [ ] **Step 5: Commit** `feat(alerts): price story read model and cached advisor tip`

### Task 5: Drop moment facts, savings ledger and Deal hunter (namespace `game` additions)

**Files:**
- Modify: `services/alert_moments.py`, `services/alert_pipeline.py` (`enrich`; `after_insert` records savings and calls `alert_delivery.dispatch`), `game/alert_hooks.py`, `game/rules.json`, `api/routes/alerts.py` (summary), `frontend/src/i18n/locales/*/game.json` (badge names and descriptions)
- Test: `backend/tests/test_alert_moments.py`, `backend/tests/test_alert_game.py`

**Interfaces:**
- Consumes: Task 1's `alerts_db` helpers and `game.engine.award`.
- Produces:
  - `drop_facts(watch_kind, watch, note) -> dict | None`. It returns `None` unless the note is a drop or target kind (`fare_target`, `fare_drop`, `fare_low_level`, `fare_cheaper_date` and the price-watch drop and target kinds) with an observed price. `from` = the reference the note used, `to` = the alerted price, `pct` is rounded to 1 decimal place, and `target_hit` = the note kind is a target kind.
  - `record(watch_kind, watch, row) -> None`: one `alert_savings` row per notification, idempotent.
  - `summary(user_id) -> dict` (`Savings`).
  - `GET /alerts/summary`.
  - Rules: `deal_drop` {15 pts, cap 5}, key `deal_drop:{kind}:{notification_id}`; `deal_target` {30, cap 3}; `deal_saved_50` {50, once}, `deal_saved_200` {100, once}, `deal_saved_1000` {250, once}
  - Badges: `deal_hunter` (`deal_drop` ×1 bronze, icon `trending-down`), `deal_hunter_silver` (×5), `deal_hunter_gold` (×20); `bullseye` (`deal_target` ×1, `target`); `saver_50`, `saver_200`, `saver_1000` (`piggy-bank`)
  - `on_drop` returns the merged `GameDelta`, which `enrich`'s caller stores in `data.game` after the insert (the pipeline updates the row's data).

- [ ] **Step 1: Write failing tests**: `test_savings_golden` (`savings_cases.json`); `test_record_idempotent_per_notification`; `test_estimate_never_counts_or_awards`: a trip watch whose moving part is an estimate, and a hotel that holds only an estimate → no row, no award; `test_eur_drop_not_in_usd_total`; `test_expired_and_error_notes_have_no_drop`; `test_target_hit_awards_bullseye_once`; `test_crossing_200_awards_saver_50_and_200` (the jump from $40 to $230); `test_hide_game_still_records_savings`; `test_summary_progress_pct`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alert_moments.py tests/test_alert_game.py` → FAIL.
- [ ] **Step 3: Implement.** Write the 7-language `game.json` strings (badge names short, at most 1.6× the English length).
- [ ] **Step 4: Run** → PASS, plus `cd frontend && npx vitest run src/i18n` (catalogue parity).
- [ ] **Step 5: Commit** `feat(alerts): drop facts, savings tally and Deal hunter game rules`

### Task 6: Delivery: quiet hours, category caps, grouping, preferences API

**Files:**
- Modify: `services/alert_delivery.py`, `api/routes/alerts.py` (preferences), `services/alert_email.py` (a `deliver_one(watch_kind, watch, row)` used by the flush; existing functions unchanged)
- Test: `backend/tests/test_alert_delivery.py`, `backend/tests/test_alerts_prefs_api.py`

**Interfaces:**
- Consumes: `user_settings_db.get_settings(user_id)["timezone"]`, `push.send_to_user`, `alert_email.deliver/deliver_price`.
- Produces:
  - `Decision = {channels: list[str], due_at: datetime | None, reason: "now"|"quiet"|"group"|"cap"|"targets_only"|"legacy"}`.
  - `plan(…) -> Decision`: a pure function of the delivery rules.
  - `dispatch(watch, watch_kind, row, now)`: enqueues each channel with its due time, or records `dropped_reason`.
  - `flush(now) -> int`: claims due items. Push items for one user that are due together are coalesced into one `send_to_user` call (title "N prices dropped", `data.group_count`). Returns the number sent.
  - `start_loop()`: every `alert_flush_interval_s`, only when the flag is on.
  - `DEFAULT_PREFS` matches the contract. `validate_prefs(patch) -> dict` raises `ApiError(422, "alert_prefs_invalid")`.

- [ ] **Step 1: Write failing tests**: `test_quiet_hours_golden` (`quiet_hours_cases.json`); `test_cap_per_category_local_day`: the 4th hotel push today is dropped with `cap`, and a flight push still goes; `test_targets_only_holds_non_target`; `test_group_window_coalesces_three_into_one_push`; `test_flush_claims_each_item_once` (two concurrent `flush` calls); `test_in_app_row_always_written`; `test_email_respects_quiet_hours_never_grouped`; `test_expired_note_legacy_path`; `test_prefs_put_partial_and_422`; `test_prefs_timezone_mirrored_read_only`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alert_delivery.py tests/test_alerts_prefs_api.py` → FAIL.
- [ ] **Step 3: Implement** with `zoneinfo`. Compute "next local end" through a local-time → UTC conversion, so DST is handled. Outbox items left over when the loop is stopped stay due, and the next start sends them.
- [ ] **Step 4: Run** → PASS, then the whole suite.
- [ ] **Step 5: Commit** `feat(alerts): quiet hours, category caps, grouped push and alert preferences`

---

## Wave 2 — backend watching

### Task 7: One-tap quick watch (pending first look)

**Files:**
- Modify: `api/routes/alerts.py` (quick-watch), `services/fare_watch.py` (create pending; first look sets the baseline), `services/price_watch.py` (`record_pending(source, spec, user, title, subtitle, plan_id) -> dict`; the first check of a pending watch calls `source.create(spec, user, api_key)` and fills the row, and a `NoLivePrice` result goes to the existing unavailable path with the estimate frozen), `db/fare_watch_db.py`, `db/price_watch_db.py` (the `pending_first_check` column, `INTEGER NOT NULL DEFAULT 0`), `api/routes/fare_watches.py` and `price_watches.py` (serialise the new key)
- Test: `backend/tests/test_quick_watch.py`

**Interfaces:**
- Consumes: the existing match logic (`/fare-watches/match`, `/price-watches/match`, `match_key`), `price_watch.limit_reached`, and the source `parse_spec` validators.
- Produces:
  - `POST /alerts/quick-watch` as specified.
  - A pending row has `next_check_at = now` and `pending_first_check = 1`, and it is cleared on the first successful or unavailable look.
  - The first look **never alerts** (it is the baseline: `check_count` 0).

- [ ] **Step 1: Write failing tests**: `test_quick_watch_makes_no_serpapi_call` (the fake counter stays at 0); `test_quick_watch_503_without_key`; `test_quick_watch_twice_returns_existing`; `test_quick_watch_counts_toward_limit_409`; `test_pending_watch_keeps_legacy_shape`: `GET /fare-watches` and `/price-watches` have every old key, with `last_price` null; `test_first_check_sets_baseline_no_alert` (against the fake); `test_pending_hotel_unavailable_freezes_estimate`; `test_bad_spec_422`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_quick_watch.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the whole suite (the existing fare and price watch tests must stay green).
- [ ] **Step 5: Commit** `feat(alerts): one-tap quick watch with a queued first look`

### Task 9: Watch suggestions on plan save

**Files:**
- Modify: `services/alert_suggest.py`, `api/routes/alerts.py` (suggestions)
- Test: `backend/tests/test_alert_suggest.py`

**Interfaces:**
- Consumes: `core/trip_access.owned_trip`, the plan's `search_data` and `selections`, and the match helpers.
- Produces: `suggestions(plan, user) -> list[dict]`, in this order:
  1. The flight (single-city plans with an origin and dates; reason `departure_soon` when ≤ 45 days to go, else `selected_in_plan`).
  2. The selected hotels (≤ 2).
  3. Selected activities that have a GetYourGuide or Viator link (≤ 2).
  4. `trip` when there are ≥ 2 priceable parts (`trip_total`).

  The list is capped at 5. `already_watching` is set from the matches. The specs are exactly what `quick-watch` accepts.

- [ ] **Step 1: Write failing tests**: `test_suggest_order_and_cap`; `test_multi_city_has_no_flight`; `test_already_watching_flagged`; `test_suggest_specs_accepted_by_quick_watch` (round trip against the fake); `test_suggest_no_network`; `test_suggest_404_other_user`; `test_empty_selections_returns_flight_only`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alert_suggest.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(alerts): watch suggestions for a saved plan`

### Task 10: Weekly digest

**Files:**
- Modify: `services/alert_digest.py`, `services/alert_email.py` (`build_digest_message(user, digest) -> EmailMessage`, text + HTML, with the existing `sparkline()`), `services/alert_delivery.py` (the loop also calls `alert_digest.run_due` every 5 min), `api/routes/alerts.py` (digest unsubscribe)
- Test: `backend/tests/test_alert_digest.py`

**Interfaces:**
- Consumes: `alerts_db.digest_claim`, `alert_moments.summary`, `alert_story.build_story`, and `alert_email.unsubscribe_token(user-scoped id, purpose="digest")`.
- Produces: `run_due(now) -> int`. A user is due once `digest_weekly` is on, it is `digest_day` at or after `alert_digest_hour_local` local time (UTC without a timezone), and no row exists for that ISO week. The digest writes the `price_digest` notification, and sends an email when SMTP is available and the email is verified. It is **skipped** (`status = "skipped"`) when no watch had a look in the last 7 days and no drop happened.

- [ ] **Step 1: Write failing tests**: `test_digest_due_monday_9_local`; `test_digest_once_per_week_across_restart`; `test_digest_skipped_when_no_looks_this_week`; `test_digest_notification_has_legacy_fields` (`kind`, `title`, `body`, `data`, `read_at`); `test_digest_email_has_unsubscribe_and_no_estimate_as_price`; `test_digest_unsubscribe_turns_off`; `test_digest_off_by_default`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alert_digest.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the whole suite.
- [ ] **Step 5: Commit** `feat(alerts): opt-in weekly price digest`

---

## Wave 3 — scheduling and first UI

### Task 8: Smarter checking (priority and adaptive intervals)

**Files:**
- Modify: `services/alert_schedule.py`, `services/fare_watch.py` (`next_check` gains `watch_kind`/`watch` keyword arguments and uses `alert_schedule.next_interval` when the flag is on; `run_due` orders by priority), `services/price_watch.py` (the same at its `next_check` call sites and in its `run_due`), `db/fare_watch_db.py` and `db/price_watch_db.py` (`due_watch_ids(now, limit, *, candidates=None)` returns up to `limit × 4` candidates for in-Python ordering)
- Test: `backend/tests/test_alert_schedule.py`

**Interfaces:**
- Produces:
  - `priority(watch_kind, watch, today) -> tuple`. Smaller runs first: `(0 if pending else 1, days_to_go, target_gap_pct)`. `days_to_go` comes from the departure date or check-in date, or 60 when there is none. `target_gap_pct` = `(latest − target) / target`, or 1.0 without a target.
  - `next_interval(…) -> timedelta`:
    - The base is 1 day at ≤ 14 days to go, 2 days at ≤ 45, 4 days at ≤ 120, else 7 days.
    - It halves (minimum 1 day) when the latest price is within 10 % above the target.
    - It adds 1 day when the last 5 looks are within 1 %.
    - The existing jitter is kept.

- [ ] **Step 1: Write failing tests**: `test_interval_table` (parametrised over each band); `test_near_target_halves`; `test_pending_first`; `test_budget_short_checks_nearest_departure_first` (3 due, budget 1 → the nearest departure is checked); `test_flag_off_next_check_unchanged`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_alert_schedule.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then the whole suite.
- [ ] **Step 5: Commit** `feat(alerts): prioritised watches and adaptive re-check intervals`

### Task 11: Price story UI (namespace `priceStory`)

**Files:**
- Modify: `components/alerts2/PriceStory.jsx`, `utils/alertStory.js`
- Create: `components/alerts2/PriceChart.jsx`, `components/alerts2/TargetSlider.jsx`
- Test: `components/alerts2/PriceStory.test.jsx`, `utils/alertStory.test.js`

**Interfaces:**
- Consumes: `alertsApi.getStory/requestAdvice`, and the existing `updatePriceWatch` and `updateFareWatch` (PATCH `target_price`, `alert_mode`).
- Produces:
  - `PriceStory` shows:
    - The chart: an SVG line with the typical band shaded, a lowest-price marker, a target line and the baseline dot. Hovering or tapping scrubs a tooltip, and ←/→ step between points with an `aria-live` price and date.
    - A verdict chip (great/good/typical/high, with an icon and text, never colour alone).
    - The translated advice line from `advice.code`.
    - "checked N days ago".
    - A labelled estimate.
    - A "Get a timing tip ✨" button (flights only, AI-labelled).
  - `TargetSlider {min, max, value, points, step, onCommit}`: dragging previews "N of your last M checks were at or below this" (`countAtOrBelow`), and the value is committed on release.

- [ ] **Step 1: Write failing tests**: `alertStory` matches `story_cases.json` for `verdictFor`/`adviceFor` (imported from the backend fixture path, as `placeKey.test.js` does); `renders paused advice without verdict when stale and no live prices`; `keyboard scrub announces price`; `slider commits target once on release`; `tip button only for flights`; `reduced motion skips the draw-in`; `no chart with fewer than 2 points, shows few-checks copy`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/PriceStory.test.jsx src/utils/alertStory.test.js` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales for `priceStory`.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): interactive price story with target slider`

### Task 12: Drop moment (namespace `dropMoment`)

**Files:**
- Modify: `components/alerts2/DropMoment.jsx`, `context/AlertsContext.jsx` (exposes `latestDrop`: the newest unread notification with `data.drop`, not yet shown on this device; `markDropShown(id)`; the shown ids are stored in `localStorage` under `tp_drop_seen:<user_id>`, capped at 50)
- Test: `components/alerts2/DropMoment.test.jsx`, `context/AlertsContext.drop.test.jsx`

**Interfaces:**
- Consumes: the notification `data.drop` and `data.game` fields, and Task 13's `SavingsShareCard` (through the stub until it merges).
- Produces: a modal card that slides in with a falling-price animation. It counts up "−$57 (−12 %)" from the new price to the old one, shows "+15 XP" (hidden when `hide_game` is on), and shows a confetti burst on `target_hit`. Its actions are "See price story" (`/alerts?watch=<kind>:<id>`), "Book" (`links.book` when present), "Share" and "Close". A deep link `/alerts?drop=<notification_id>` (from a push) opens it with `via: push`. The card is focus-trapped, closes on Escape and returns focus.

- [ ] **Step 1: Write failing tests**: `shows once per notification per user`; `no card for notes without drop`; `target hit shows confetti, reduced motion shows final amount at once`; `xp hidden when hide_game`; `deep link opens with via push`; `escape closes and restores focus`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/DropMoment.test.jsx src/context/AlertsContext.drop.test.jsx` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): animated drop moment`

---

## Wave 4 — savings and watching UI

### Task 13: Savings tally and share card (namespace `savings`)

**Files:**
- Modify: `components/alerts2/SavingsTally.jsx`, `components/alerts2/SavingsShareCard.jsx`
- Create: `utils/savingsCard.js` (`drawSavingsCard(ctx, savings, strings, theme) -> void` at 1080×1080; `shareSavings(blob, text) -> 'native'|'download'|'copy'`)
- Test: `components/alerts2/SavingsTally.test.jsx`, `utils/savingsCard.test.js`

**Interfaces:**
- Consumes: `alertsApi.getSavings`.
- Produces:
  - `SavingsTally` shows a count-up of `total_usd` ("Drops caught: $245"), with `by_currency` chips, a progress ring to `next_milestone` with the three milestone ticks, drops and targets counters, the best catch, and a Share button.
  - The compact variant is a single line for `AlertsV2Header`.
  - Empty state: "Your first drop will show here".
  - Copy says "caught" and never "saved" unless the line is followed by "if you book at that price".

- [ ] **Step 1: Write failing tests**: `ring progress matches progress_pct`; `eur chip separate from usd total`; `empty state`; `share falls back to download without navigator.canShare`; `card text has no estimate and no title when the watch was deleted`; `reduced motion no count-up`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/SavingsTally.test.jsx src/utils/savingsCard.test.js` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): savings tally, milestones and share card`

### Task 14: One-tap watch button (namespace `quickWatch`)

**Files:**
- Modify: `components/alerts2/QuickWatchButton.jsx`
- Test: `components/alerts2/QuickWatchButton.test.jsx`

**Interfaces:**
- Consumes: `alertsApi.quickWatch`, the existing `deleteFareWatch`/`deletePriceWatch`, `useAlertsV2().livePrices`, and the `AlertsContext.showToast`.
- Produces: an eye/bell toggle (`aria-pressed`). Tapping it is optimistic: it shows "Watching" with a small bounce. A toast reads "We'll check this price for you — first check soon" with Undo (5 s, which deletes the watch). An existing watch shows "Already watching" and links to the story. A `409` shows the limit message. The button is hidden when `livePrices` is false or the user is signed out (a signed-out tap opens sign-in).

- [ ] **Step 1: Write failing tests**: `hidden when live_prices is false`; `optimistic on, rollback on error`; `undo deletes the created watch`; `existing shows already watching`; `double tap sends one request`; `409 shows limit text`; `telemetry has kind, action and surface, no title`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/QuickWatchButton.test.jsx` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): one-tap watch button`

### Task 15: Watch suggestions sheet (namespace `watchSuggest`)

**Files:**
- Modify: `components/alerts2/WatchSuggestions.jsx`
- Test: `components/alerts2/WatchSuggestions.test.jsx`

**Interfaces:**
- Consumes: `alertsApi.getSuggestions` and `alertsApi.quickWatch`.
- Produces: a bottom sheet (a dialog on desktop) titled "Want us to watch these prices?". It lists the suggestions as toggles, pre-ticked except `trip`, with already-watched rows disabled. "Watch N" quick-watches the ticked items in sequence, showing per-row progress and failure. "Not now" dismisses it. It is shown at most once per plan (`localStorage tp_suggest_seen:<user_id>:<plan_id>`), and never when `livePrices` is false or the list is empty.

- [ ] **Step 1: Write failing tests**: `not shown without live prices`; `once per plan per user`; `watch N creates ticked only`; `partial failure keeps the failed row with retry`; `telemetry shown, accepted and dismissed with count`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/WatchSuggestions.test.jsx` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): watch suggestions after saving a plan`

---

## Wave 5 — composition and integration

### Task 16: Alert preferences and digest opt-in (namespace `alertPrefs`)

**Files:**
- Modify: `components/alerts2/AlertPrefsPanel.jsx`
- Test: `components/alerts2/AlertPrefsPanel.test.jsx`

**Interfaces:**
- Consumes: `getAlertPrefs/putAlertPrefs`, and the account settings API (`PATCH` timezone).
- Produces: a panel with the following controls. Each one saves on change and rolls back on error:
  - the weekly digest switch and day picker;
  - "Only ping me for target hits" (`instant`);
  - quiet hours (two time inputs);
  - category caps (steppers, 1–10);
  - the group window (an off/15/30/60 select).

  When quiet hours are on and there is no account timezone, it offers "Use my time zone (Asia/Kolkata)" from `Intl.DateTimeFormat().resolvedOptions().timeZone`.

- [ ] **Step 1: Write failing tests**: `saves each field and rolls back on 422`; `offers browser timezone when missing`; `quiet hours inactive notice without timezone`; `telemetry field enum only`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/AlertPrefsPanel.test.jsx` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): alert preferences, quiet hours and digest opt-in`

### Task 17: Alerts hub 2.0 (namespace `alertsHub`; adds keys to `alerts`)

**Files:**
- Modify: `components/alerts2/AlertsV2Header.jsx`, `components/alerts2/WatchCardExtras.jsx`, `locales/*/alerts.json` (new keys only)
- Create: `components/alerts2/DealHunterTrack.jsx`, `utils/notificationGroups.js` (`groupDrops(notifications, windowMin) -> Array<{ids, kind, count, latest}>`)
- Test: `components/alerts2/AlertsHub.test.jsx`, `utils/notificationGroups.test.js`

**Interfaces:**
- Consumes: Tasks 11, 13 and 16 components, `gameApi` (badges with the `deal_`/`saver_`/`bullseye` ids), and `useAlertsV2`.
- Produces:
  - `AlertsV2Header` has the compact `SavingsTally`, the `DealHunterTrack` (next badge progress, hidden by `hide_game`), a "Live checks paused" calm banner when `livePrices` is false ("Your watches keep their last prices; each shows when it was checked"), a preferences button, sort chips (Moving / Departing soon / Newest), and the digest entry when the `?from=digest` deep link is present (`alert_digest_open`).
  - `WatchCardExtras` has the verdict chip, "checked N days ago", a "Price story" expander that renders `PriceStory`, and the `?watch=kind:id` deep link (auto-expand and scroll).
  - The bell's list groups drop notifications with `groupDrops`.

- [ ] **Step 1: Write failing tests**: `paused banner without live prices`; `deep link expands the story`; `sort departing soon`; `deal hunter hidden with hide_game`; `groupDrops merges within the window only`; `digest notification opens the hub with via email_link`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/alerts2/AlertsHub.test.jsx src/utils/notificationGroups.test.js` → FAIL.
- [ ] **Step 3: Implement**, with the 7 locales.
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): alerts hub with savings, Deal hunter track and story cards`

### Task 18: Results, Chat and Trip integration

**Files:**
- Modify: `pages/ResultsPage.jsx` (`QuickWatchButton` on the flight, hotel and activity cards next to the existing Watch buttons; `WatchSuggestions` after a successful plan save), `pages/ChatPage.jsx` (the same in plan sections and after save), `pages/TripPage.jsx` (the overview gets a "Prices" card: watched items with their verdict chips, a link to the hub and "Watch prices for this trip", which opens `WatchSuggestions`), `components/PlanViewModal.jsx` (the one-tap button on plan rows)
- Test: `pages/ResultsPage.quickWatch.test.jsx`, `pages/ChatPage.quickWatch.test.jsx`, `pages/TripPage.prices.test.jsx`

**Interfaces:**
- Consumes: Tasks 14 and 15 components, and the spec builders already used by `WatchFareButton`, `WatchHotelButton`, `WatchActivityButton` and `WatchTripButton` (reuse them, no new spec code).
- Produces: v2 controls only when `useAlertsV2().on`. The existing dialog buttons stay as the "more options" path.

- [ ] **Step 1: Write failing tests**: `flag off renders exactly the classic buttons`; `quick watch spec equals the dialog spec for a hotel`; `suggestions after save once`; `trip prices card lists watches for this plan_id`; `chat plan section has one-tap`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/pages/ResultsPage.quickWatch.test.jsx src/pages/ChatPage.quickWatch.test.jsx src/pages/TripPage.prices.test.jsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` and eslint → PASS.
- [ ] **Step 5: Commit** `feat(alerts): one-tap watch and suggestions across results, chat and trips`

---

## Wave 6 — docs and translation

### Task 19: Docs and CLAUDE.md sync

**Files:** `CLAUDE.md` (the price-watch bullet: v2 pipeline, the delivery rules, savings, quick-watch, digest, the flag; the table count grows by 5; the `/api/alerts/*` rows), `docs/API-Reference.md`, `docs/Configuration.md` (the four settings), `docs/Privacy.md` (the digest email, the savings ledger, no amounts in telemetry), `docs/Feature-Parity.md` (the Phase 3 rows for web, Android and iOS), `docs/Frontend.md`, `docs/Changelog.md`.
- [ ] **Step 1:** Write the docs. Every claim must match the merged code (grep the setting names and routes).
- [ ] **Step 2: Run** `mkdocs build --strict` → PASS.
- [ ] **Step 3: Commit** `docs(alerts): phase 3 docs and CLAUDE.md sync`

### Task 20: Translation review

One reviewer pass per language over the seven Phase 3 namespaces plus the new `game` and `alerts` keys. It checks tone (informal es/de, `vous` in fr), length (≤ 1.6× English on buttons) and plurals (`_one`/`_other`, and the i18next plural rules for hi, bn and zh). It never translates "Voyager", and it checks that "caught" vs "saved" keeps the honesty meaning.
- [ ] **Step 1:** Fix the strings. **Run** `cd frontend && npx vitest run src/i18n` → PASS.
- [ ] **Step 2: Commit** `i18n(alerts): phase 3 translation review`

---

## Wave 7 — verify and switch on

### Task 21: Browser end-to-end against the fake SerpAPI, mixed versions, review passes

- [ ] **Step 1:** Start the backend with `python backend/scripts/run_with_fake_serpapi.py` (fake on 8765, `--drop-after 1`), with `PRICE_ALERTS_V2_ENABLED=true` and a dummy `SERPAPI_KEY` that only the fake accepts. Never use the real key.
- [ ] **Step 2:** Walk the flow in the browser:
  1. Search, then one-tap a flight and a hotel. The fake's `/__calls` stays at 0.
  2. Save the plan, and the suggestions sheet appears. Watch two items.
  3. Trigger `run_due` twice: the baseline, then a drop.
  4. The drop moment appears, counting up, with XP.
  5. The tally, then the share card downloads.
  6. The price story: scrub with the keyboard, then drag the target.
  7. Prefs: quiet hours on, and a drop is held (check `alert_outbox`).
  8. The digest: set the clock to Monday 09:00 and see the notification.

  Check light and dark at 375 and 1280 px, in English and one more language, with reduced motion on.
- [ ] **Step 3:** Restart without `SERPAPI_KEY`. Expect the paused banner, the stale labels, no one-tap and no suggestions, with the story and tally intact.
- [ ] **Step 4:** Mixed versions:
  - Build the previous SPA (`git worktree` at `origin/main` before Task 1) against the new backend. It lists pending watches and the digest notification without error.
  - The new SPA against the old backend shows the classic Alerts page.
- [ ] **Step 5:** Three independent review passes on the branch diff (correctness, honesty and anti-spam, UX and accessibility). Fix the findings, and put the minors in `docs/superpowers/plans/2026-11-12-phase3-followups.md`.
- [ ] **Step 6: Commit** the fixes and the follow-ups file.

### Task 22: Switch on price alerts 2.0

**Files:** `core/config.py` (`price_alerts_v2_enabled: bool = True`), `deploy/gcp/app.env.example`, `docs/Configuration.md`, `backend/tests/test_client_config.py`.
- [ ] **Step 1:** Change the default and update the test (`price_alerts_v2 is True` by default). **Run** the whole backend suite → PASS.
- [ ] **Step 2: Commit** `feat(alerts): switch on price alerts 2.0`. The owner can revert it with `PRICE_ALERTS_V2_ENABLED=false` in `app.env`.

---

## Execution waves

Each wave starts when the previous one has merged to main. Inside a wave, at most 3 tasks run in parallel worktrees, and they own disjoint files (see the hotspot table).

| Wave | Tasks (parallel) | Gate |
|---|---|---|
| 0 — seams and contract | 1 backend seams · 2 frontend seams · 3 contract + golden cases + fake SerpAPI | When it merges, `docs/Alerts-API.md` is frozen and the mobile teams start |
| 1 — backend core | 4 story · 5 moments + savings + game · 6 delivery + prefs | Task 5's `after_insert` calls Task 6's `dispatch` through the stub, so the merge order doesn't matter |
| 2 — backend watching | 7 quick watch · 9 suggestions · 10 digest | 9's round-trip test needs 7: merge 7 first, or skip that test until 7 lands |
| 3 — scheduling + first UI | 8 adaptive checks · 11 price story UI · 12 drop moment | 8 alone touches `run_due` and `next_check` |
| 4 — watching UI | 13 savings + share · 14 one-tap · 15 suggestions sheet | — |
| 5 — composition | 16 prefs UI · 17 hub · 18 integration | 17 needs 11, 13 and 16's components (16 merges first, or 17 uses the stub) |
| 6 — docs | 19 docs ∥ 20 translation review | — |
| 7 — finish | 21 E2E + reviews → 22 switch on | 22 merges only after 21 is green |

Every PR is green and deployable alone. The backend v2 behaviour is off by default, the read routes have no UI until the flag, and frontend controls render only with `features.price_alerts_v2` (or the override).

## Deferred (later phases)

- Localised push and email text, and the global 3/day notification cap across categories: Phase 6 (§7).
- OG share pages and the 1080×1920 story-format share card: Phase 4. Phase 3 shares a client-rendered square PNG and text.
- Friend leaderboards for Deal hunter: Phase 5.
- APNs delivery of drop pushes: Phase 6/7. Android FCM already receives them, with the new `data` keys.
- Converting non-USD savings into one total (this needs a rate source with an honest date label).

## Owner questions

1. **SerpAPI in production.** Without a key, prod shows only the stored history: there is no one-tap watch, no suggestions and no new drops, so the drop moment and savings stay dormant. Will you add a key (the Free Plan is 250/month, already exhausted for November, or a paid plan) so the feature can actually delight in production?
2. **Wording.** Is the "caught a drop of $X" framing acceptable instead of "you saved $X"? We can't know whether the user booked. The share card says "I caught $245 in price drops with Voyager".
3. **Digest defaults.** Opt-in, Mondays 09:00 local, email + in-app. Should the digest also push (it is currently in-app only, to avoid noise)?


## Owner-question rulings (main controller, 2026-11-12)

1. **SerpAPI key in production:** this stays the owner's call. Ship everything config-gated, with the "live checks paused" state shown when no key is set. Nothing may fail or invent prices without a key.
2. **Savings wording:** use "caught a drop of $X". "You saved" is never used, because we can't know whether the user booked.
3. **Digest channels:** the digest goes out in-app and by email. Its push is off by default, with a user toggle in alert preferences.
