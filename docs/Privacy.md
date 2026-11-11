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
