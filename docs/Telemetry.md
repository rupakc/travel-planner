# Telemetry

Product telemetry answers "which features are used, where do people drop out, what is slow or broken" for all Voyager clients (web today; Android and iOS later). What users are told is in [Privacy](Privacy.md); this page is the developer contract. The closed schema lives in `backend/app/telemetry/registry.py` (`EVENTS`), and a test fails if an event there is missing from this page.

It is separate from `POST /api/analytics/events` (signed-in only, writes log lines, unchanged).

## Envelope

`POST /api/telemetry`, JSON, optionally gzipped (`Content-Encoding: gzip`), auth optional:

```json
{
  "client": {
    "anon_id": "7f9c2b0e-3c1d-4b8a-9f10-5a2d7e6c4b11",
    "session_id": "1d4a6c52-8e07-4f3b-a2c9-0b6e5d7f8a90",
    "platform": "web",
    "app_version": "1.0.0",
    "locale": "de"
  },
  "events": [
    {"event": "screen_view", "ts": 1767225600000, "screen": "/chat", "props": {"route": "/chat"}}
  ]
}
```

| Field | Rule |
|---|---|
| `client.anon_id`, `client.session_id` | UUIDs. One session per batch. |
| `client.platform` | `web`, `android` or `ios`. |
| `client.app_version` | A token (see Prop types). |
| `client.locale` | A token of at most 16 characters (the web sends `<html lang>`, e.g. `de` or `zh-CN`). |
| `events[].event` | A name from the tables below. Unknown names are dropped. |
| `events[].ts` | Milliseconds since the epoch. A missing value, or one more than 7 days from server time, is replaced by the server time. |
| `events[].screen` | Optional route template (a token). Dropped when it is not one. |
| `events[].props` | Only the props listed for that event, each passing its type check. Anything else is dropped. |

A bad `client` block, a body that is not an object or more than 100 events is `422`. Individual bad events and props are dropped silently, so a well-formed batch always answers `204`. A body over 64 KB (256 KB once gunzipped) is `413`. `404` means telemetry is disabled on the server. The server adds `received_at` and, for a signed-in caller, `user_id`; no IP address and no user agent are stored. Details: [API Reference](API-Reference.md#post-apitelemetry).

### Prop types

| Type | Accepts |
|---|---|
| token (`id`) | A string of 1-64 characters from `A-Z a-z 0-9 _ . : / -` (no spaces and no `@`, so free text and e-mail addresses cannot pass) |
| `int` | An integer within ±2^53 (not a boolean) |
| `float` | A finite number within ±2^53 |
| `bool` | `true` or `false` |
| enum | One of the listed values |

## Events

The Web column says whether the web app emits the event today. Events marked "not yet" are accepted by the server so Android, iOS and later web phases can send them without a backend change.

### Lifecycle and navigation

| Event | Props | Web | Meaning |
|---|---|---|---|
| `app_open` | none | yes | Collection started (page load, or consent granted later). |
| `app_background` | none | yes | Page hidden; the queue is flushed. |
| `session_start` | none | yes | First event after 30 minutes idle. |
| `screen_view` | `route` (token), `referrer_route` (token) | yes | Route changed; `referrer_route` is the previous route. |
| `screen_time` | `route` (token), `ms` (int) | yes | Time on the previous route, sent when leaving it or hiding the page. |

### Interaction

Auto-captured by one delegated listener (`frontend/src/telemetry/autocapture.js`); input values and text content are never read.

| Event | Props | Web | Meaning |
|---|---|---|---|
| `ui_tap` | `tid` (token), `route` (token) | yes | Click on a button, link or other interactive element. |
| `ui_toggle` | `tid`, `route`, `on` (bool) | yes | Checkbox, radio or switch changed. |
| `ui_change` | `tid`, `route` | yes | Text input, select or textarea changed (never to what). |
| `ui_submit` | `tid`, `route` | yes | Form submitted. |

`tid` is the closest `data-tid`; otherwise `id:<id>` when the element has a static-looking id (no digits, no 8+ character hex segment); otherwise `auto:<tag>`. It is never the visible text.

### Search and chat funnel

| Event | Props | Web | Meaning |
|---|---|---|---|
| `search_submit` | `mode` (`search`, `chat`, `compare`, `link`, `discover`), `travelers` (int), `nights` (int), `multi_city` (bool) | not yet | A search or plan was started. |
| `search_first_section` | `ms` (int) | not yet | Time to the first streamed section. |
| `search_complete` | `ms` (int), `sections` (int), `errors` (int) | not yet | Stream finished. |
| `search_abandon` | `ms` (int), `sections` (int) | not yet | User left before it finished. |

### Engagement

| Event | Props | Web | Meaning |
|---|---|---|---|
| `section_expand` | `section` (token) | not yet | A result section was opened. |
| `plan_select` | `section` (token) | not yet | An item was added to My Plan. |
| `link_out` | `section` (token), `domain` (token) | not yet | A provider link was opened. |
| `share` | `target` (token), `object` (token) | not yet | Something was shared. |
| `alert_event` | `action` (token), `kind` (token) | not yet | A fare or price alert action. |
| `onboarding_step` | `step` (int), `action` (`view`, `next`, `skip`, `done`) | not yet | Onboarding progress. |
| `feature_used` | `feature` (token), `page` (token) | yes | Mirror of every `track(feature, page)` call in `utils/analytics.js`; the metadata is not sent. |

### Settings, consent, performance, errors

| Event | Props | Web | Meaning |
|---|---|---|---|
| `theme_change` | `theme` (`system`, `light`, `dark`) | yes | Theme chosen. |
| `language_change` | `lang` (`en`, `es`, `de`, `fr`, `hi`, `zh`, `bn`) | yes | Language chosen. |
| `consent` | `choice` (`granted`, `denied`) | grant only | The web sends only a grant. A denial is kept on the device and nothing is sent. |
| `perf` | `metric` (`ttfb`, `fcp`, `lcp`, `inp`, `cls`, `long_task`, `cold_start`), `value` (float), `route` (token) | yes, except `cold_start` | Web metrics from the browser timing APIs; `lcp`, `inp`, `cls` and `long_task` (a count) are sent when the page is hidden. `cold_start` is for the mobile apps. |
| `error` | `kind` (`js`, `promise`, `api`), `source` (token), `status` (int) | `js` and `promise` | `source` is a script basename and line (`app.js:42`) or `unknown`, never the message. At most 20 per page load. `api` is not emitted yet. |

## Client rules

These apply to every client; the web implementation is `frontend/src/telemetry/`.

- Telemetry never blocks, slows or breaks the UI. Every entry point swallows its own errors and nothing on a user path awaits it.
- Fetch `GET /api/config` once at start. A `404`, an error or `telemetry.enabled: false` turns telemetry off for the session, with no retries. This is how a client tolerates an older or self-hosted backend.
- Events queue in memory and are sent every `telemetry.flush_interval_s` (15) or at `telemetry.max_batch` (50) events, clamped to the server limit of 100. The web client sends in idle time.
- When the page is hidden the rest is sent with `fetch(keepalive)` plus the bearer token when signed in, otherwise `navigator.sendBeacon` (which cannot carry headers, so those events are anonymous).
- The queue is capped at 500 events. It is persisted to `localStorage` (`tp_tq`) only when the page is hidden or a send fails, and claimed at the next start; stored events older than 7 days are discarded.
- Three failures in a row back off exponentially; a `429` honours `Retry-After`. A `4xx` other than 408 and 429 drops that batch (it would fail forever).
- `anon_id` is a persistent random UUID (`tp_anon`). The session ID lives in `sessionStorage` and rolls over after 30 minutes idle.
- Routes are templates (`/share/:token`, `/plans/:id`, `/alerts/:id`, `/other`), never raw URLs, so tokens and ids never leave the browser.
- Props are filtered client-side with the same token, number and boolean rules, so free text never leaves even if a caller passes it by mistake.
- Without consent nothing is queued or sent (below).

## Consent

`consentRequired()` is true for devices in an EU, EEA, UK or Switzerland time zone (every `Europe/*` zone except Istanbul, Moscow, Minsk and Kiev/Kyiv, plus Reykjavik, Canary, Madeira, Azores and Faroe). Those devices send nothing until the user chooses in the one-time prompt (`ConsentPrompt`). Elsewhere telemetry is on and can be switched off in Preferences, Privacy (`PrivacySwitch`). The choice is stored in `localStorage` as `tp_consent` (`granted` or `denied`). A denial clears the queue and stops the collectors; a later grant starts them. The wording users see is in [Privacy](Privacy.md).

## Storage and retention

| What | Where | Kept |
|---|---|---|
| Raw events (`telemetry_events`) | `$DATA_DIR/telemetry.db`, its own SQLite file in WAL mode so ingestion never contends with user data | `TELEMETRY_RETENTION_DAYS` (default 90); not backed up |
| Daily rollups (`telemetry_daily`, `telemetry_daily_totals`, `telemetry_rollups`) | `airports.db` | Indefinitely; backed up with the user tables |

An hourly lifespan task (`backend/app/telemetry/maintenance.py`) rolls up every finished UTC day, re-rolls the trailing 7 days (late events from offline clients) and prunes raw events past retention. `telemetry_daily_totals` rows with `platform = '*'` hold exact distinct users and sessions across all events and platforms.

## Reading it

`GET /api/admin/telemetry/summary?days=30` (admin) returns daily users, sessions and events, top events, top screens and `users_7d`, the distinct users over the last 7 UTC days. The web admin page shows it as the Analytics tab, hidden when the endpoint answers `404`. Settings: `TELEMETRY_ENABLED`, `TELEMETRY_RETENTION_DAYS`, `RATE_LIMIT_TELEMETRY` (see [Configuration](Configuration.md)).

## Adding an event

1. Add it to `EVENTS` in `backend/app/telemetry/registry.py` with typed props. Ship the backend first: an event the deployed backend does not know is dropped silently.
2. Add a row here (the registry test enforces that the name appears on this page).
3. Add it to the event table in [Privacy](Privacy.md).
4. Update the clients.
