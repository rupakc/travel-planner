# Phase 6 — Notifications Implementation Plan

> **For agentic workers:** use superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Immersive, respectful notifications. Server-side categories, quiet hours and caps; localized trip-phase pushes (T-30, T-7, T-1, morning brief); price drops that respect the same controls; APNs for iOS (inert until the owner sends an Apple key); one client contract for iOS and Android.

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md` §7, §5a, §6 (anti-spam), §8, §11 row 6. **Builds on:** `services/push.py` (FCM), `alert_delivery.py` (quiet hours/caps/outbox, shared), `alerts_db.alert_prefs`, `notifications_db`, `devices_db`, Phase 2 `trip_prep`/`trip_phase`/`trip_snapshots`.

## Rulings (prudent defaults; owner can change by config)

1. **Flag.** `NOTIFICATIONS_V2_ENABLED` (`settings.notifications_v2_enabled`, default `false`; switched on after the final review). The new routes always exist. The flag gates only behaviour: category checks on price pushes, the trip-push loop, and APNs/FCM routing by platform. Off = today's behaviour byte for byte. `GET /config` gains `features.notifications_api: 1`, `features.notifications_v2: bool`, `features.apns: bool` (key configured).
2. **Categories** (per-user toggles, all default on): `price_drops`, `trip_reminders` (T-30/T-7/T-1), `morning_brief`, `weather`, `nearby` (a client-side switch the apps honour for on-device local notifications; the server never sends it), plus reserved `social`, `quiz` (stored and returned, no sender until Phase 5).
3. **One source of truth for quiet hours**: they stay in `alert_prefs.quiet_hours` (Phase 3). The new settings routes read and write that same value, so both UIs agree. Quiet window is evaluated in the account `timezone`. With no timezone, quiet hours are not applied, and the morning brief is **skipped**; T-x reminders go out from 09:00 UTC.
4. **Caps.** New global `daily_cap` (int 1–10, default 3) counts non-price pushes per user per local day. Price drops are exempt from it and keep Phase 3's per-kind caps. Held-over-quiet items are re-checked against the cap when released.
5. **Held items.** A push in quiet hours is held until the window ends and sent then; if held more than 12 h it is dropped. The in-app row is always written, and the user sees it in the notification list.
6. **Dedupe.** One push per `(user, plan, kind)` ever, enforced by a unique key in a new `notify_log` table. Morning brief is per `(plan, local day)`.
7. **Localization.** Text is rendered server-side from `services/notify_text.py` in the 7 languages: user setting `language`, else the newest device `locale`, else `en`. The same templates are served by `GET /notifications/catalog` so apps localize on-device notifications from one source.
8. **Location privacy.** The server never receives or stores location, and nothing location-like enters telemetry. "Localized recommendations" are (a) the morning brief, using the plan's own destination, today's itinerary slot and a static country tip; (b) on-device "near you" notifications built from the catalog template and the existing `/nearby` (coarse place data). The contract tells apps not to send coordinates anywhere new.
9. **Gamified touches.** The morning brief deep-links to Today (check-in). Push text never mentions streaks or points, and never shows a "streak at risk" nudge (guardrail: never punishing). With `hide_game` no game wording appears at all.
10. **APNs** is built (`services/apns.py`, ES256 JWT via PyJWT, HTTP/2 via `httpx[http2]`) and inert until `APNS_TEAM_ID`, `APNS_KEY_ID`, `APNS_KEY_P8` (or `APNS_KEY_FILE`) and `APNS_BUNDLE_ID` (default `io.github.rupakc.travelplanner`) are set; `APNS_SANDBOX` toggles the host. `/devices` additively accepts `platform: "ios"`. Tests use `httpx.MockTransport`, never Apple.
11. **Deferred** (follow-ups): live weather-change detection (needs a polling budget; `weather` covers the T-1 and morning-brief weather line from the stored snapshot), web push (VAPID), social/quiz senders, `notify_log` per-day analytics.

## Global constraints

- Additive schema only (`CREATE TABLE IF NOT EXISTS`); new tables `notify_prefs`, `notify_log` join the GCS user-table backup set. Old SPA and Android app keep working with the new backend (extra `data` keys, new kinds are ignored by the old UI; check `notifications` rendering tolerates unknown `kind`). The new SPA on the old backend hides the section (feature-detect `features.notifications_api`).
- No SerpAPI, FCM or Apple traffic in any test; fakes only. `ruff check backend/`, `cd frontend && npx eslint src/ --max-warnings 0`, `mkdocs build --strict`, pytest, vitest all green.
- i18n: every new UI string in all 7 languages, one new namespace `notifications` (register in `routeNamespaces.js` for `/account`). Light default, dark via tokens only.
- Telemetry: closed registry + `docs/Telemetry.md` rows; props enums/bools/ints only. New events: `notif_settings_view {}`, `notif_category_toggle {category: enum, on: bool}`, `notif_quiet_hours_change {enabled: bool}`, `notif_cap_change {cap: int}`, `notif_open {category: enum, source: enum push|inapp}` (for apps on tap). Elements carry `data-tid`.
- Commits as rupakc; message ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## API contract (`docs/Notifications-API.md`, additive-only once merged)

All under `/api`, bearer auth, Phase 1 error envelope `{"detail","error_code"}`.

- `GET /notification-settings` → `{"categories": {"price_drops": {"enabled": true}, "trip_reminders": {...}, "morning_brief": {...}, "weather": {...}, "nearby": {...}, "social": {...}, "quiz": {...}}, "quiet_hours": {"enabled": true, "start": "22:00", "end": "07:00"}, "daily_cap": 3, "timezone": "Asia/Kolkata"|null, "quiet_hours_active": bool, "push": {"fcm": bool, "apns": bool}, "devices": 2}`.
- `PUT /notification-settings` (any subset of `categories.<name>.enabled`, `quiet_hours` fields, `daily_cap`; `timezone`, `quiet_hours_active`, `push`, `devices` read-only and ignored) → same object. `422 notification_settings_invalid`.
- `GET /notifications/catalog?locale=xx` → `{"locale": "es", "templates": {"nearby_arrival": "Estás cerca de {place}: {item} está a {minutes} min", …}}` (every template the server sends plus on-device ones; unknown locale → `en`).
- `POST /devices` accepts `platform: "android" | "ios"` (APNs token as hex string).
- Notification rows (`/notifications`) and push `data` gain `category` and `plan_id`; kinds `trip_t30`, `trip_t7`, `trip_t1`, `trip_morning`. `link` is a web path (`/trips/{id}`, `/trips/{id}/today`); apps map it.
- Delivery order for category pushes: user enabled? → dedupe → quiet hours (hold) → global cap → send. Price drops: `price_drops` enabled? → Phase 3 rules.

## Tasks

Wave 0: T1 alone (foundation, merges first). Wave 1: T2 ∥ T3 ∥ T5 (disjoint files). Wave 2: T4 (needs T2). Each task = one PR via worktree `.claude/worktrees/p6-tN`, TDD, merge on green CI.

### T1 — Foundation: flag, settings store, routes, registry, contract (sonnet)
Files: `core/config.py` (flag, `apns_*`), `db/notify_db.py` (`notify_prefs(user_id PK, data JSON)`, `notify_log(id, user_id, plan_id, kind, dedupe_key UNIQUE, category, status, due_at, sent_at, dropped_reason, notification_id)`; tables created in `main.py` lifespan; add both to the vm_backup user-table list), `services/notify_settings.py` (defaults, validate, merge, view incl. quiet hours via `alerts_db`), `api/routes/notification_settings.py` (+ catalog route reading `notify_text.catalog(locale)`; T1 ships a stub `services/notify_text.py` with `en` only and the `catalog()`/`render(key, locale, **params)` signatures that T2 fills in), `client_config.py`, telemetry registry + `docs/Telemetry.md`, `docs/Notifications-API.md`, `docs/Feature-Parity.md`, `mkdocs.yml` nav, `account_data` export/delete includes the new tables. Tests: defaults, partial PUT, validation, quiet-hours sync with `/alerts/preferences`, auth, other user isolation, registry test.

### T2 — Delivery core + text (sonnet)
`services/notify_text.py` (all templates × 7 languages: trip_t30/t7/t1, morning brief with optional `{slot}`/`{tip}`/`{weather}` lines, `nearby_arrival`, price-drop group strings reused as-is), `services/notify_center.py`: pure `decide(category, prefs, tz, counts, now)` reusing `alert_delivery.quiet_until`, `enqueue_category(user_id, plan_id, kind, category, key, title, body, data, now)` (dedupe, writes the in-app row, `notify_log`), `flush_due(now)` (hold release, cap recheck, stale drop, sends via `push.send_to_user`, claim-once); gate `alert_delivery.plan` on the `price_drops` toggle when the flag is on; hook `flush_due` into `alert_delivery._loop`. Tests incl. golden quiet-hours edges (23:30 Asia/Kolkata, spring-forward New York, no tz), cap, dedupe, double flush, all 7 languages have every key and placeholders match.

### T3 — APNs + platform routing (sonnet)
`services/apns.py` (`configured()`, ES256 provider token cached 50 min, `send(token, title, body, data)`, HTTP/2 POST `/3/device/{token}`, `apns-topic`, `apns-push-type: alert`, `apns-priority`, dead tokens `410`/`BadDeviceToken`/`Unregistered` pruned, never logs full tokens), `devices_db.devices_for(username)` → `[(token, platform)]`, `push.send_to_user` splits by platform when the flag is on (FCM unchanged for android; iOS to APNs), `/devices` `platform` Literal adds `ios`, `requirements.txt` adds `httpx[http2]` (h2). Tests with `MockTransport` and a generated P-256 key. No test touches the network.

### T4 — Trip-phase pushes (sonnet, after T2)
`services/trip_pushes.py`: `run_due(now)` scans the users' plans with a start date. T-30 (only if the visa prep item is not done and a visa is needed), T-7 (packing not done), T-1 (check-in + weather line from the snapshot), morning brief at 08:00 local on each trip day (first itinerary slot of the day, a static country tip, weather line; skipped without tz or after the trip). Uses `trip_prep.prep_payload`, `trip_phase.day_index`, `notify_center.enqueue_category`. Hooked into the loop every 5 min behind the flag, prunes `notify_log` > 60 days. Tests with fixed `now`, a trip in each state, done items suppress, double run once.

### T5 — Web settings UI (sonnet; contract only, backend may lag)
`frontend/src/services/notificationsApi.js`, `components/account/NotificationsSection.jsx` mounted in `AccountPage` (feature-detected), category toggles, quiet-hours with timezone shown, daily-cap stepper, "push not available on this device yet" note when `devices == 0`, `notifications.json` × 7, `routeNamespaces.js`, telemetry events, tests. Tokens only, ≥ 44 px targets, keyboard and aria labels.

### T6 — E2E, final review, flag on
Local stack (fake SerpAPI, fake push transports), browser pass on Account → Notifications; one opus whole-branch review; fix findings; set `notifications_v2_enabled` default `true` if safe (no FCM/APNs creds in prod means pushes stay inert; in-app rows only); follow-ups doc.
