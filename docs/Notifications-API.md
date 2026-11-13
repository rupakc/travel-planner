# Notifications API

> Frozen with Phase 6 wave 0. **Changes:** later changes are additive only (new fields, endpoints, categories, kinds or error codes; nothing renamed, removed or re-typed). Every change needs a contract-change note in its PR and an update to this page in the same PR.

Notifications 2.0 adds server-side **categories**, **quiet hours** and a **daily cap**, localized trip-phase pushes (T-30, T-7, T-1 and a morning brief), a shared **text catalog** for on-device notifications, and APNs for iOS next to FCM for Android. It is additive to `/api/notifications*`, `/api/devices*` and `/api/alerts/preferences`, which keep their request fields, response keys and semantics.

## API contract

All paths are under `/api`, with JSON in and out. Every route needs `Authorization: Bearer <access_token>` and acts only on the caller's data. Errors use the Phase 1 envelope `{"detail", "error_code"}`.

### Discovery (additive)

`GET /config` gains `features.notifications_api: 1` (the routes below exist), `features.notifications_v2: bool` (`NOTIFICATIONS_V2_ENABLED`, default on: category checks, trip pushes and platform routing are active) and `features.apns: bool` (an Apple key is configured). Clients feature-detect `notifications_api` and hide the settings UI without it.

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

- `categories`: all default on. `nearby` is a client-side switch the apps honour for on-device local notifications; the server never sends it. `social` (idea saved, new follower) and `quiz` (head-to-head invite, head-to-head result) are sent by the server; `quiz` kinds are never sent to a user who hides the game. Additive: new notification kinds `social_idea_saved`, `social_new_follower`, `quiz_h2h_invite`, `quiz_h2h_result`; their text carries no handles or ids. Also additive: `social_idea_liked` and `social_idea_comment` (category `social`; sent to the idea's author, never for one's own action or across a block, at most one of each per idea per UTC day, only for published comments; link `/feed/{idea_id}`; `social_idea_saved` also links `/feed/{idea_id}`) and `quiz_daily` (category `quiz`; a once-per-local-day reminder at 12:00-20:00 in the user's timezone, only for users who played in the last 30 days and still have today's daily quiz open; never when the game is hidden or `PLAY_ENABLED`/`GAME_ENABLED` are off; link `/play`). Clients must ignore kinds they do not know. The catalog gains the matching `social_idea_liked`, `social_idea_comment` and `quiz_daily` templates in the 7 languages.
- `quiet_hours` is the same value as `alert_prefs.quiet_hours` (`GET/PUT /alerts/preferences`): a change through either route shows in both. It is evaluated in the account `timezone`; `timezone` is `null` when unset or invalid, and then quiet hours are not applied and the morning brief is skipped.
- `daily_cap` (1 to 10, default 3) counts non-price pushes per user per local day. Price drops are exempt and keep the per-kind caps of `/alerts/preferences`. Additive refinement: `social` and `quiz` pushes also share a sub-cap of 2 per local day (never more than `daily_cap`), and they count toward the daily cap only through that sub-cap, so a flood of social or quiz pushes can never block trip reminders, the morning brief, weather or nearby pushes; social and quiz pushes are themselves dropped (`reason` `cap`) once the day's total reaches `daily_cap`. Because trip and other pushes ignore the social and quiz counts, a day's total can reach `daily_cap` plus 2 (for example 3 trip pushes after 2 social ones); social and quiz are only blocked once the total is at or above `daily_cap`. Request and response shapes are unchanged.
- `push.fcm` / `push.apns`: whether the server can deliver to that platform. `devices`: the caller's registered device count.

`PUT /notification-settings` takes any subset of `categories.<name>.enabled` (bool), `quiet_hours` (`enabled`, `start`, `end`, as in `/alerts/preferences`) and `daily_cap`, and answers with the full object above. `timezone`, `quiet_hours_active`, `push` and `devices` are read-only and ignored. Failures answer `422 notification_settings_invalid` (unknown category or key, wrong type, bad `HH:MM`, cap outside 1 to 10).

### Text catalog

`GET /notifications/catalog?locale=xx` answers `{"locale": "es", "templates": {"nearby_arrival": "Estás cerca de {place}: {item} está a {minutes} min", ...}}`: every template the server sends plus on-device ones, with `{name}` placeholders. `locale` is `en es de fr hi zh bn`; an unknown or missing locale answers `en` (the response's `locale` says which). Template keys: `trip_t30`, `trip_t7`, `trip_t1`, `trip_morning`, `nearby_arrival`, `weather_rain`, `weather_heat`, `weather_cold`. New keys may appear; apps ignore keys they do not know.

### Devices (additive)

`POST /devices` accepts `platform: "android" | "ios"` (an iOS token is the APNs device token as a hex string). Existing android registrations are unchanged.

### Notification rows and push data (additive)

Rows from `/notifications` and the push `data` payload gain `category` and `plan_id` (`null` for price drops). New kinds: `trip_t30`, `trip_t7`, `trip_t1`, `trip_morning`, `weather_rain`, `weather_heat`, `weather_cold` (category `weather`, link `/trips/{id}/today`; sent only for a trip on the road with an outdoor itinerary slot today, once per slot and condition per day, when the server runs with `WEATHER_PUSH_ENABLED=true`; they follow the `weather` category switch, quiet hours and daily cap; template keys carry `{slot}` and `{time}`; weather data by Open-Meteo.com, CC BY 4.0); clients ignore a kind they do not know. `link` is a web path (`/trips/{id}`, `/trips/{id}/today`, `/feed`, `/feed/{idea_id}`, `/play/h2h/{match_id}`) that apps map to a screen.

### Delivery rules

Category pushes: category enabled? then dedupe (one per user, plan and kind ever; the morning brief per plan and local day) then quiet hours (held until the window ends, dropped if held over 12 h) then the daily cap, then send. The in-app row is always written. Price drops: `price_drops` enabled, then the Phase 3 rules. Text is rendered in the user's `language` setting, else the newest device `locale`, else `en`. With `hide_game` no game wording appears. Trip pushes go out inside the local day window only: T-30 and T-7 between 09:00 and 21:00 local (retried on later days of their 25-30 and 5-7 day windows), T-1 only the day before the trip, the morning brief (which also covers the first trip day) between 08:00 and 11:00 local; the T-30 and T-7 text shows the days left. An invalid or missing timezone counts as none (UTC for T-x, no morning brief). While `NOTIFICATIONS_V2_ENABLED` is off (it is on by default) the behaviour is the Phase 3 behaviour unchanged.

### Privacy

The server never receives or stores location, and nothing location-like goes into telemetry. Apps must not send coordinates to any new endpoint; "near you" notifications are built on-device from the catalog and the existing `POST /nearby`.

### Telemetry

`notif_settings_view`, `notif_category_toggle`, `notif_quiet_hours_change`, `notif_cap_change`, `notif_open`: see `Telemetry.md`.
