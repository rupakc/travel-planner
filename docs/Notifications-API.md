# Notifications API

> Frozen with Phase 6 wave 0. **Changes:** later changes are additive only (new fields, endpoints, categories, kinds or error codes; nothing renamed, removed or re-typed). Every change needs a contract-change note in its PR and an update to this page in the same PR.

Notifications 2.0 adds server-side **categories**, **quiet hours** and a **daily cap**, localized trip-phase pushes (T-30, T-7, T-1 and a morning brief), a shared **text catalog** for on-device notifications, and APNs for iOS next to FCM for Android. It is additive to `/api/notifications*`, `/api/devices*` and `/api/alerts/preferences`, which keep their request fields, response keys and semantics.

## API contract

All paths are under `/api`, with JSON in and out. Every route needs `Authorization: Bearer <access_token>` and acts only on the caller's data. Errors use the Phase 1 envelope `{"detail", "error_code"}`.

### Discovery (additive)

`GET /config` gains `features.notifications_api: 1` (the routes below exist), `features.notifications_v2: bool` (`NOTIFICATIONS_V2_ENABLED`: category checks, trip pushes and platform routing are active) and `features.apns: bool` (an Apple key is configured). Clients feature-detect `notifications_api` and hide the settings UI without it.

### Settings

`GET /notification-settings`:
```json
{"categories": {"price_drops": {"enabled": true}, "trip_reminders": {"enabled": true},
                "morning_brief": {"enabled": true}, "weather": {"enabled": true},
                "nearby": {"enabled": true}, "social": {"enabled": true}, "quiz": {"enabled": true}},
 "quiet_hours": {"enabled": true, "start": "22:00", "end": "07:00"},
 "daily_cap": 3, "timezone": "Asia/Kolkata", "quiet_hours_active": true,
 "push": {"fcm": false, "apns": false}, "devices": 2}
```

- `categories`: all default on. `nearby` is a client-side switch the apps honour for on-device local notifications; the server never sends it. `social` and `quiz` are stored and returned and have no sender yet.
- `quiet_hours` is the same value as `alert_prefs.quiet_hours` (`GET/PUT /alerts/preferences`): a change through either route shows in both. It is evaluated in the account `timezone`; `timezone` is `null` when unset or invalid, and then quiet hours are not applied and the morning brief is skipped.
- `daily_cap` (1 to 10, default 3) counts non-price pushes per user per local day. Price drops are exempt and keep the per-kind caps of `/alerts/preferences`.
- `push.fcm` / `push.apns`: whether the server can deliver to that platform. `devices`: the caller's registered device count.

`PUT /notification-settings` takes any subset of `categories.<name>.enabled` (bool), `quiet_hours` (`enabled`, `start`, `end`, as in `/alerts/preferences`) and `daily_cap`, and answers with the full object above. `timezone`, `quiet_hours_active`, `push` and `devices` are read-only and ignored. Failures answer `422 notification_settings_invalid` (unknown category or key, wrong type, bad `HH:MM`, cap outside 1 to 10).

### Text catalog

`GET /notifications/catalog?locale=xx` answers `{"locale": "es", "templates": {"nearby_arrival": "Estás cerca de {place}: {item} está a {minutes} min", ...}}`: every template the server sends plus on-device ones, with `{name}` placeholders. `locale` is `en es de fr hi zh bn`; an unknown or missing locale answers `en` (the response's `locale` says which). Template keys: `trip_t30`, `trip_t7`, `trip_t1`, `trip_morning`, `nearby_arrival`. New keys may appear; apps ignore keys they do not know.

### Devices (additive)

`POST /devices` accepts `platform: "android" | "ios"` (an iOS token is the APNs device token as a hex string). Existing android registrations are unchanged.

### Notification rows and push data (additive)

Rows from `/notifications` and the push `data` payload gain `category` and `plan_id` (`null` for price drops). New kinds: `trip_t30`, `trip_t7`, `trip_t1`, `trip_morning`; clients ignore a kind they do not know. `link` is a web path (`/trips/{id}`, `/trips/{id}/today`) that apps map to a screen.

### Delivery rules

Category pushes: category enabled? then dedupe (one per user, plan and kind ever; the morning brief per plan and local day) then quiet hours (held until the window ends, dropped if held over 12 h) then the daily cap, then send. The in-app row is always written. Price drops: `price_drops` enabled, then the Phase 3 rules. Text is rendered in the user's `language` setting, else the newest device `locale`, else `en`. With `hide_game` no game wording appears. While `NOTIFICATIONS_V2_ENABLED` is off the behaviour is the Phase 3 behaviour unchanged.

### Privacy

The server never receives or stores location, and nothing location-like goes into telemetry. Apps must not send coordinates to any new endpoint; "near you" notifications are built on-device from the catalog and the existing `POST /nearby`.

### Telemetry

`notif_settings_view`, `notif_category_toggle`, `notif_quiet_hours_change`, `notif_cap_change`, `notif_open`: see `Telemetry.md`.
