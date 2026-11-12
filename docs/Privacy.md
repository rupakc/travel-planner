# Privacy

Voyager collects usage data, tied to a random device ID (and to your account when you are signed in), so the project can find bugs and see which features are used. This page lists exactly what is collected, what never is, how long it is kept and how to switch it off. The list below comes from the closed event schema in `backend/app/telemetry/registry.py`: the server accepts only these events and these properties and silently drops everything else.

## What is collected

Every batch of events carries a small client block. The telemetry tables store no IP address and no user agent.

The `anon_id` is a persistent device identifier, so events from one browser can be linked to each other, and to your account when you are signed in. (This is pseudonymous, not anonymous.)

The client block:

| Field | Meaning |
|---|---|
| `anon_id` | A random UUID generated in your browser, stored on the device. Not derived from you. |
| `session_id` | A random UUID for the current visit. |
| `platform` | `web`, `android` or `ios`. |
| `app_version` | The app build. |
| `locale` | The interface language. |

Each event also has a timestamp and, when known, the screen it happened on (a route template such as `/chat` or `/share/:token`, never the full URL or the share token). If you are signed in, the server stores your account id with the event; if you are not, it stores none.

### Events and properties

Property values are short tokens (letters, digits and `_ . : / -`, no spaces or `@`), numbers, booleans, or one of a fixed set of choices.

| Event | Properties |
|---|---|
| `app_open`, `app_background`, `session_start` | none |
| `screen_view` | `route`, `referrer_route` |
| `screen_time` | `route`, `ms` |
| `ui_tap` | `tid`, `route` |
| `ui_toggle` | `tid`, `route`, `on` |
| `ui_change` | `tid`, `route` |
| `ui_submit` | `tid`, `route` |
| `search_submit` | `mode` (search, chat, compare, link or discover), `travelers`, `nights`, `multi_city` |
| `search_first_section` | `ms` |
| `search_complete` | `ms`, `sections`, `errors` |
| `search_abandon` | `ms`, `sections` |
| `section_expand` | `section` |
| `plan_select` | `section` |
| `link_out` | `section`, `domain` |
| `share` | `target`, `object` |
| `alert_event` | `action`, `kind` |
| `onboarding_step` | `step`, `action` (view, next, skip or done) |
| `theme_change` | `theme` (system, light or dark) |
| `language_change` | `lang` (en, es, de, fr, hi, zh or bn) |
| `consent` | `choice` (granted or denied) |
| `feature_used` | `feature`, `page` |
| `perf` | `metric` (ttfb, fcp, lcp, inp, cls, long_task or cold_start), `value`, `route` |
| `error` | `kind` (js, promise or api), `source`, `status` |
| `auth_start` | `method` (password, apple, google, facebook or github), `mode` (signin, signup or link) |
| `auth_result` | `method`, `mode`, `result` (ok, error, cancelled, coming_soon, needs_username or pending), `code` |
| `signup_step` | `step` (form, check_email, username or done) |
| `email_verify` | `result` (ok, expired, invalid, used, resent or email_changed) |
| `password_reset` | `step` (request or confirm), `result` (ok, error, expired, invalid or used) |
| `account_action` | `action` (avatar_upload, avatar_remove, name_change, settings_change, export, delete, link, unlink, signout_all, email_verify_request or change_password) |
| `quota_block` | `bucket` (search, chat, compare, discover, light_ai or import), `reason` (daily_quota or unverified) |
| `game_award` | `rule`, `points` |
| `badge_earned` | `badge` |
| `level_up` | `level` |
| `game_view` | `surface` (account, nav or celebration) |

`tid` is the stable identifier of a button or control (for example `nav.search`), never its visible text.

## Account data

When you create an account Voyager stores: your username, display name, email address and whether it is verified, a bcrypt hash of your password (never the password), your sign-in method and any linked Google, GitHub, Facebook or Apple identity (provider ID and email, plus an encrypted Apple token that is needed only to revoke access when you delete your account), your settings and onboarding answers, your avatar, active sessions (hashed refresh tokens, device name), and your game progress (XP, badges, streaks). Plans, preferences, recent searches, taste profile, feedback, fare and price watches, notifications and registered devices are stored as before. Verification and reset tokens are stored only as hashes.

- **Avatars** are resized to 256 px WebP and kept on the server's disk (`$DATA_DIR/avatars`). They are not part of the GCS backup, which covers only the database.
- **Retention.** An account that never confirms its email is deleted after 7 days. Expired tokens are purged hourly. Refresh tokens expire after 60 days of inactivity and at most 365 days after sign-in.
- **Export.** **Account** → **Export my data** (`GET /api/account/export`) downloads everything above as one JSON file.
- **Deletion.** **Account** → **Delete account** (`DELETE /api/account`, confirmed with your password, or your username if you have none) removes your account and everything in the export, your avatar file and your telemetry events, and revokes Apple tokens. Backups made before the deletion are not rewritten and age out with the normal backup rotation. The last remaining admin cannot be deleted.
- **Daily AI allowance.** To apply the daily limits the server counts, per account and per UTC day, how many AI requests you made in each bucket. No request content is stored.

## Trips, expenses and journal

If you use trips, the server stores them with your account: trip titles, destinations and dates, your prep checklist ticks, expenses (amount, currency, category, note, day), journal entries and moods, your star ratings and notes for places, which places you visited, the countries (and so continents) of trips you checked in to or completed a recap for, and the offline snapshot of a trip's emergency card, currency, visa and packing facts. All of it is included in **Export my data** and removed by **Delete account**.

- **Offline packs** are kept in your browser (IndexedDB and the cache of the app's service worker), not sent anywhere. They are cleared when you sign out, and when an administrator switches the offline pack off.
- **No location history.** A check-in records a day and the trip's city, never your coordinates. Coordinates stored with a place are the place's, supplied by the app.

## Price alerts

Beyond the watches and notifications above, price alerts 2.0 stores, per account: your alert preferences (weekly digest on or off, weekday, whether the digest also pushes, instant alerts, quiet hours, daily caps, grouping window), a **savings ledger** (one row per observed price drop on one of your watches: the watch, the prices before and after, the currency and the time; drops between observed prices only, never estimates), a queue of pushes and emails waiting for quiet hours or grouping, a record of which weeks your digest was sent, and a cached price tip per flight watch. The **weekly digest** is opt-in; it is sent to your account email (if verified and the server has SMTP) and shown in the app, and as a push only if you turn that on. Its email carries a stop link. The savings figure is a tally of "drops caught", not a record of what you booked. All of it is included in **Export my data** and removed by **Delete account**. The alert telemetry events (`alert_story_view`, `alert_target_set`, `alert_advice`, `alert_drop_seen`, `alert_quick_watch`, `alert_suggest`, `alert_savings_share`, `alert_prefs_change`, `alert_digest_open`) carry only enums, counts and flags, never an amount, a price, a title or a place. Sharing the "I caught $X" card happens in your browser; the server sees nothing of it.

## What is never collected

The schema has no field for any of these, and the server drops unknown fields:

- Free text you type (searches, chat messages, notes, names of places you enter).
- Precise location.
- Your email address or name.
- Other people's content.

## Server request logs

Separately from telemetry, the app's request-log line records only the HTTP method, path, status code, duration and username (or `anonymous`), with no IP address or user agent; uvicorn's standard access log is not disabled in the app container, and it records the connecting client address.

## Retention

Raw events are kept for 90 days in a separate database file on the server (`telemetry.db`) and are not backed up. Events already sent stay on the server until that 90-day retention ends, even after you switch collection off; there is no way yet to ask for them to be deleted. Daily aggregate counts (events, users and sessions per day, event and platform) are kept longer in the main database and are backed up with the user tables.

## Consent and how to switch it off

- If your device time zone is in the EU, EEA, UK or Switzerland, collection is off until you choose. Voyager shows a one-time prompt with **Allow** and **No thanks**.
- Everywhere else collection is on by default and can be switched off at any time.
- To change your choice, use the **Privacy choices** link in the footer of any page (including the sign-in page and shared trip pages, so it works without an account), or, when signed in, open **Preferences**, then **Privacy**, and use the **Help improve Voyager** switch.
- Choosing **No thanks** (or switching it off) stops collection and clears any events still waiting on your device. The denial itself is stored only on your device; nothing is sent about it.
- The same switch covers the app's older feature-usage log (`POST /api/analytics/events`, which records the feature, page and your username in the server log when you are signed in): while collection is off, nothing is sent there either.
- Telemetry can also be disabled on a self-hosted server with `TELEMETRY_ENABLED=false`.
