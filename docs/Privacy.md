# Privacy

Voyager collects anonymous usage data so the project can find bugs and see which features are used. This page lists exactly what is collected, what never is, how long it is kept and how to switch it off. The list below comes from the closed event schema in `backend/app/telemetry/registry.py`: the server accepts only these events and these properties and silently drops everything else.

## What is collected

Every batch of events carries a small client block:

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

`tid` is the stable identifier of a button or control (for example `nav.search`), never its visible text.

## What is never collected

The schema has no field for any of these, and the server drops unknown fields:

- Free text you type (searches, chat messages, notes, names of places you enter).
- Precise location.
- Your email address or name.
- Other people's content.

## Retention

Raw events are kept for 90 days in a separate database file on the server (`telemetry.db`) and are not backed up. Daily aggregate counts (events, users and sessions per day, event and platform) are kept longer in the main database and are backed up with the user tables.

## Consent and how to switch it off

- If your device time zone is in the EU, EEA, UK or Switzerland, collection is off until you choose. Voyager shows a one-time prompt with **Allow** and **No thanks**.
- Everywhere else collection is on by default and can be switched off at any time.
- To change your choice, open **Preferences**, then **Privacy**, and use the **Help improve Voyager** switch.
- Choosing **No thanks** (or switching it off) stops collection and clears any events still waiting on your device. The denial itself is stored only on your device; nothing is sent about it.
- Telemetry can also be disabled on a self-hosted server with `TELEMETRY_ENABLED=false`.
