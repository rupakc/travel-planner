# Configuration

The backend is configured through environment variables, read by pydantic-settings in `backend/app/core/config.py`. Variable names are the upper-case field names. Every setting has a default, so the app always starts; the ones marked *needed* below must be set for it to be useful.

Settings are read from the process environment and from a `.env` file in the **working directory** (`env_file=".env"`, unknown keys ignored). For `start.sh` and a manual `uvicorn` run that is `backend/.env`. For Docker Compose, put the values in your shell or a root `.env`, which Compose uses for variable substitution (see [Setup and Installation](Setup-and-Installation.md)).

---

## Core

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET_KEY` | `""` | **Needed.** HS256 signing key for login tokens (24 h lifetime). Changing it logs everyone out. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| `CORS_ORIGINS` | `["http://localhost:5174","http://localhost:5173"]` | Allowed browser origins, as a JSON list. |
| `AGENTS_DIR` | `<repo>/.agents` | Directory of the agent definition files. A relative path that does not exist falls back to `<repo>/.agents`. |
| `AGENT_MAX_CONCURRENCY` | `6` | Global cap on concurrent model calls across all agents. |
| `CACHE_TTL_SECONDS` | `1800` | TTL of the in-memory result cache. |
| `CACHE_MAXSIZE` | `500` | Maximum entries in that cache. |

## LLM

Every model call goes through `backend/app/core/llm.py`; see [Architecture](Architecture.md#models).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `gemini`: Gemini on Vertex AI with Application Default Credentials (no API key). `anthropic`: Claude via `ANTHROPIC_API_KEY`, for local development or a rollback. `auto`: `gemini` when `GCP_PROJECT` is set; otherwise `anthropic` when `ANTHROPIC_API_KEY` is set; otherwise `gemini` if Application Default Credentials resolve a project, else `anthropic`. The choice is resolved once, logged at startup (`LLM provider: gemini (auto: GCP_PROJECT set) …`) and shown by `/health/agents` as `llm_provider` / `llm_provider_reason`. |
| `GCP_PROJECT` | `""` | **Needed for Gemini.** Google Cloud project that runs Vertex AI, e.g. `voyager-prod-ohzkl`; setting it also makes `auto` choose Gemini. Empty falls back to `GOOGLE_CLOUD_PROJECT` or the ADC project. |
| `GCP_LOCATION` | `global` | Vertex AI location. `global` routes to any region with capacity; `us` and `eu` keep processing in that multi-region. |
| `GEMINI_MODEL_AGENT` | `gemini-3.5-flash-lite` | Model for every specialist agent, itinerary, stress test, packing, pricing advisor, link import, discovery, layover, chat itinerary and chat routing/extraction. |
| `GEMINI_MODEL_CHAT` | `gemini-3.8-flash` | Model for chat conversational answers and the planning narrative. |
| `GEMINI_THINKING_AGENT` | `minimal` | Thinking level of the agent model: `minimal`, `low`, `medium` or `high`. |
| `GEMINI_THINKING_CHAT` | `low` | Thinking level of the chat model: `low`, `medium` or `high` (Gemini 3.8 Flash rejects `minimal`). On Gemini, a level the model refuses stops the app at startup with a clear error. |
| `ANTHROPIC_API_KEY` | `""` | **Needed for Claude** (`LLM_PROVIDER=anthropic`, or `auto` without `GCP_PROJECT`). Unused on Gemini. |

With Gemini, the credentials need the Vertex AI User role (`roles/aiplatform.user`) on the project. Locally, run `gcloud auth application-default login` once. If no credentials are found, every AI section fails and `/health/agents` reports the error.

## Storage and backup

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `backend/data` | Directory of the single SQLite file `airports.db`, which holds every table (users, plans, preferences, place data and so on). Created automatically. |
| `TELEMETRY_ENABLED` | `true` | Product telemetry. `false` makes `POST /api/telemetry` answer `404` (clients then switch themselves off) and `GET /api/config` report it disabled. Raw events live in `$DATA_DIR/telemetry.db` (not backed up); daily aggregates in the `telemetry_daily` table of `airports.db`. |
| `TELEMETRY_RETENTION_DAYS` | `90` | Raw telemetry events older than this are pruned by the hourly maintenance loop, which also rolls up each finished UTC day. |
| `TELEMETRY_MAX_DB_MB` | `1024` | Global disk guard: while `telemetry.db` plus its WAL is larger than this, `POST /api/telemetry` still answers `204` but drops the batch (one warning per hour in the log). The size is re-read about once a minute. |
| `TELEMETRY_MAX_EVENTS_PER_DAY` | `200000` | Global daily cap: once this many events have been stored in the current UTC day (all callers together), further batches are dropped the same way until midnight UTC. |
| `PUBLIC_BASE_URL` | `""` | Absolute origin returned by `GET /api/config` (for share links). Empty: the request's own base URL. |
| `BACKUP_BUCKET` | `""` | Google Cloud Storage bucket for SQLite backups. Empty disables backup and restore. Uses Application Default Credentials. |
| `BACKUP_MODE` | `cloudrun` | `cloudrun` (legacy, for ephemeral disks): restore at every start, upload every 60 s with a generation-safe merge, force an upload on shutdown. `vm` (production): the disk is authoritative. The app restores only when `airports.db` is missing (stray `-wal`/`-shm` removed first), never merges, and uploads the user tables (everything except the regenerable place data) only when their SHA-256 changed, plus once at a clean shutdown. In `vm` mode, `DATA_DIR` must contain the marker file `.voyager-data-disk` written when the disk was provisioned, or the app refuses to start. A missing DB that can't be fetched from GCS also refuses to start. `GET /health` then reports `backup_ok` and `backup`. |
| `BACKUP_INTERVAL_SECONDS` | `300` | `vm` mode: how often the user tables are exported and compared. `backup_ok` turns false after 3 missed intervals or on any failed cycle. |
| `BACKUP_EXPORT_DIR` | system temp | `vm` mode: scratch directory for the export (a tmpfs in production, so the slow disk is never touched). |

## Live data (optional)

| Variable | Default | Meaning |
|---|---|---|
| `SERPAPI_KEY` | `""` | SerpAPI key for live Google Flights fares, the fare calendar and Google's price insights. Empty means flights are LLM estimates and `POST /api/flights/fare-calendar` returns 503. `GET /health` reports `serpapi_configured`. |
| `SERPER_KEY` | `""` | Serper.dev key for Places-to-See data (Google Places) and the second tier of activity and place link resolution. Empty means Places to See is LLM-only. |

Other web lookups (link enrichment for hotels and activities, the forex agent's rate searches, walking-tour city-page discovery, and identifying an unknown airport code) go through DuckDuckGo via the `ddgs` package and need no key.

## Fare watch and email alerts (optional)

Fare watch re-checks watched fares in the background and needs `SERPAPI_KEY`. Price watches for hotels, activities and whole trips use the **same** settings, scheduler and SerpAPI budget: there is no separate price-watch configuration, and the daily budget, the per-user share and the active limit count all kinds of watch together. Email alerts need an SMTP server; without one, alerts still appear in the app.

| Variable | Default | Meaning |
|---|---|---|
| `FARE_WATCH_ENABLED` | `true` | Starts the fare-watch scheduler at startup (only when `SERPAPI_KEY` is set). `false` stops background checks and hides "Watch fare" (`GET /health` reports `fare_watch_available`). The test suite sets it to `false`. |
| `FARE_WATCH_TICK_SECONDS` | `300` | How often the scheduler looks for watches that are due. |
| `FARE_WATCH_INTERVAL_HOURS` | `12` | Time between two checks of one watch, ±10 % jitter. |
| `FARE_WATCH_DAILY_CALL_BUDGET` | `200` | SerpAPI calls per UTC day that all watches (fare, hotel, activity and trip) may spend together (scheduled checks, baselines and "Check now"). A fare check costs 1 call for exact dates or up to 7 with nearby dates; a hotel or activity check 1, a trip check up to 8; creating a price watch holds its worst case (hotel 2, activity 2, trip 10) and gives back what it didn't spend. Answers cached in the last 30 min cost nothing. When spent, remaining checks move to the next day and "Check now" answers `429`. Searches and the fare calendar are not counted. |
| `FARE_WATCH_MAX_ACTIVE_PER_USER` | `10` | Active watches per user, of every kind together (paused and ended ones don't count). |
| `FARE_WATCH_USER_DAILY_SHARE` | `0.3` | Largest share of `FARE_WATCH_DAILY_CALL_BUDGET` one user's watches may spend per UTC day (at least 1 call), so one account can't use up everyone's checks. Over it, that user's checks wait for the next day and their "Check now" answers `429`. |
| `SMTP_HOST` | `""` | SMTP server for alert emails. Empty disables email (`GET /health` reports `email_alerts_available`). |
| `SMTP_PORT` | `587` | SMTP port. |
| `SMTP_USERNAME` | `""` | Login user; empty skips `AUTH`. |
| `SMTP_PASSWORD` | `""` | Login password. Never logged. |
| `SMTP_FROM` | `""` | `From` header, e.g. `Voyager <alerts@example.com>`. Falls back to `SMTP_USERNAME`, then `alerts@localhost`. |
| `SMTP_STARTTLS` | `true` | Upgrade the connection with STARTTLS before logging in. |
| `APP_BASE_URL` | `http://localhost:5174` | Public URL of the frontend, used for the links in alert emails ("See flights", "Re-plan", and the stop-emails link, which goes to `APP_BASE_URL/api/...`, so the frontend's host must proxy `/api`). That link opens a confirmation page (GET) and the change is a POST, which is also the RFC 8058 one-click target named in the `List-Unsubscribe` / `List-Unsubscribe-Post` headers. Account emails are not verified: setting one is signed-in only and rate-limited. |

### Price alerts 2.0

See [Alerts API](Alerts-API.md). With the flag off, fare and price watches, email and push behave exactly as before; the `/api/alerts/*` read routes are always served.

| Variable | Default | Meaning |
|---|---|---|
| `SHARING_V2_ENABLED` | `true` | Share links 2.0 (Phase 4): `/api/shares*` and the new-style `GET /api/share/{token}` fallback. Off, they answer 404 (`sharing_disabled` for the authenticated routes) and `features.sharing` is `0`; legacy plan share tokens keep working either way. Contract: [Sharing API](Sharing-API.md). Set `PUBLIC_BASE_URL` in production: share links, `og:url` and the absolute `og:image` of the crawler page are built from it (else the request's base URL, which behind a proxy may not be the public host). |
| `SOCIAL_ENABLED` | `false` | Phase 5: profiles, follows and blocks (and later the ideas feed and moderation) under `/api/social/*`. Off, every route answers `404 social_disabled` and `features.social` is `0`. Handles, privacy and limits: [Social API](Social-API.md). No AI call is ever made. |
| `PLAY_ENABLED` | `false` | Phase 5: quizzes, head-to-head, leaderboards and weekly challenges under `/api/play/*`. Off, they answer `404 play_disabled` and `features.play` is `0`; it also needs `GAME_ENABLED`. |
| `PRICE_ALERTS_V2_ENABLED` | `true` | Turns on the v2 pipeline: drop facts, savings rows, Deal-hunter XP, delivery rules (quiet hours, caps, grouping), the outbox flush loop, the weekly digest and adaptive scheduling. Reported as `features.price_alerts_v2`; the web UI shows it only when this is true (or for one browser with `localStorage.tp_alerts2 = "1"`). Runbook: turning it off discards pushes and emails held at that moment (quiet hours, group window); in-app alerts stay. Held items more than 12 h past due are dropped as `stale` instead of sent. |
| `ALERT_DIGEST_HOUR_LOCAL` | `9` | Local hour (user's account timezone) from which a user's weekly digest is due on their chosen weekday. |
| `ALERT_FLUSH_INTERVAL_S` | `60` | How often the delivery loop sends held (quiet-hours, grouped) pushes and emails. |
| `ALERT_ADVICE_TTL_HOURS` | `24` | How long an AI price tip for a flight watch is cached. |

Without `SERPAPI_KEY`, `features.live_prices` is false: stories, savings, the digest and suggestions work from stored data, every price shows "checked N days ago", and one-tap watch answers `503 live_prices_off`.

## Push alerts (optional)

Fare- and price-watch alerts can also be pushed to the Android app's registered devices (`/api/devices`) through Firebase Cloud Messaging (FCM HTTP v1). Without it, alerts still appear in the app and by email, and the Android app polls `/api/notifications`.

| Variable | Default | Meaning |
|---|---|---|
| `FCM_SERVICE_ACCOUNT_FILE` | `""` | Path to a Firebase service-account JSON key (Firebase console → Project settings → Service accounts → Generate new private key) for the project the Android app is registered in. Its `project_id` picks the FCM project. Empty, or a path that does not exist, disables push (`GET /health` reports `push_configured`). Keep the file out of the repo (`*service-account*.json` and `*-key.json` are git-ignored) and readable only by the backend. The key is read once: restart the backend after rotating it. |
| `FCM_USE_ADC` | `false` | With no key file: send with Application Default Credentials (on the VM, its service account through the metadata server; it needs FCM send rights, e.g. `roles/firebasecloudmessaging.admin`). The key file wins when both are set. |
| `FCM_PROJECT_ID` | `""` | FCM project for ADC mode; empty uses `GOOGLE_CLOUD_PROJECT`, which the entrypoint sets from the metadata server. |
| `NOTIFICATIONS_V2_ENABLED` | `true` | Notifications 2.0: category checks on price pushes, trip pushes (T-30, T-7, T-1, morning brief) and iOS/Android push routing. Trip pushes run inside the alert loop, so they also need `PRICE_ALERTS_V2_ENABLED=true` (the loop does not start without it). With no FCM/APNs credentials only in-app rows are written. `false` restores the Phase 3 behaviour. |
| `APNS_TEAM_ID` | `""` | Apple developer Team ID for iOS pushes (APNs token auth). Inert until `APNS_TEAM_ID`, `APNS_KEY_ID` and a key (`APNS_KEY_P8` or `APNS_KEY_FILE`) are all set; only used when `NOTIFICATIONS_V2_ENABLED=true`, which routes iOS devices to APNs and Android devices to FCM. |
| `APNS_KEY_ID` | `""` | Key ID of the APNs auth key (.p8). |
| `APNS_KEY_P8` | `""` | The .p8 key contents (PEM; `\n` escapes accepted). Wins over `APNS_KEY_FILE`. |
| `APNS_KEY_FILE` | `""` | Path to the .p8 key file. |
| `APNS_BUNDLE_ID` | `io.github.rupakc.travelplanner` | The iOS app's bundle id (`apns-topic`). |
| `APNS_SANDBOX` | `false` | Use Apple's sandbox host (development builds). |

## Accounts

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Username of the seeded admin. |
| `ADMIN_PASSWORD` | `""` | Password for the seeded admin. Empty means no admin is created. Used only when that user does not exist yet; the seeded admin is not forced to change it. |
| `ADMIN_EMAIL` | `""` | Optional email for the seeded admin. |

With `SIGNUP_ENABLED=true` and email delivery available, anyone can create an account with `POST /api/auth/signup` (a verification email is sent first) unless `SIGNUP_MODE=invite`; admins can still create users from the Admin page, and those accounts count as verified for AI. Contract: [Accounts API](Accounts-API.md).

### Sign-up, sessions and email links

| Variable | Default | Meaning |
|---|---|---|
| `SIGNUP_ENABLED` | `false` | Operator opt-in for native (password) sign-up. While false, `POST /api/auth/signup` answers `503 email_unavailable` and `GET /api/config` reports `signup_available: false`, even when SMTP is set for fare alerts. OAuth sign-up and password reset are not affected. |
| `SIGNUP_MODE` | `open` | `open`, or `invite` (sign-up and OAuth sign-up need an invite code from `POST /api/admin/invites`). |
| `EMAIL_LOG_LINKS` | `false` | Dev only: with `SMTP_HOST` unset, log verification and reset links instead of sending them (also on when the base URL host is `localhost`). |
| `ACCOUNT_TOKEN_TTL_MINUTES` | `30` | Lifetime of verify-email and password-reset tokens (single use). |
| `PENDING_PURGE_DAYS` | `7` | An unverified (pending) account is deleted after this many days; the hourly maintenance task also purges expired tokens. |
| `REFRESH_TOKEN_DAYS` | `60` | Mobile refresh-token lifetime (rotated on use). |
| `REFRESH_FAMILY_MAX_DAYS` | `365` | Absolute lifetime of a refresh-token family from sign-in. |
| `MOBILE_ACCESS_TOKEN_MINUTES` | `60` | Access-token lifetime for `client` ios/android (web stays 24 h). |
| `PUBLIC_BASE_URL` / `APP_BASE_URL` | see above | Every absolute URL (email links, OAuth `redirect_uri`, avatar URLs) is `PUBLIC_BASE_URL`, else `APP_BASE_URL`, without a trailing `/`. |

### Sign-in providers (all optional)

A provider is on only when **all** its credentials are non-empty; otherwise its button shows "coming soon". Secrets go in Secret Manager in production. Setup per provider: [Deployment on GCP](Deployment-GCP.md#sign-in-providers-and-email).

| Variable | Default | Meaning |
|---|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `""` | Google web OAuth client. |
| `GOOGLE_NATIVE_CLIENT_IDS` | `[]` | JSON list of the iOS/Android client IDs accepted by `POST /api/auth/oauth/google/id-token`. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `""` | GitHub OAuth app. |
| `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` | `""` | Meta app with Facebook Login. |
| `FACEBOOK_GRAPH_VERSION` | `v24.0` | Graph API version used for the profile call. |
| `FACEBOOK_EMAIL_TRUSTED` | `false` | Treat Facebook's email as verified. Off by default, so a Facebook email never auto-links to an existing account. |
| `APPLE_SERVICES_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` | `""` | Sign in with Apple: Services ID, team, key ID and the `.p8` key contents. |
| `APPLE_NATIVE_CLIENT_IDS` | `[]` | JSON list of iOS bundle IDs accepted by `POST /api/auth/oauth/apple/id-token`. |
| `OAUTH_MOBILE_REDIRECTS` | `["voyager://auth/callback"]` | Exact-match allow-list of mobile `redirect_uri` values (`<base>/auth/callback` is always allowed). |

### Daily AI quota and game

A signed-in user who has not verified their email cannot use AI routes (`403 email_unverified`). Verified users also have a per-UTC-day allowance per bucket on top of the 10-minute windows; `0` means unlimited, and admins are exempt.

| Variable | Default | Meaning |
|---|---|---|
| `AI_DAILY_QUOTA_ENABLED` | `true` | Master switch for the daily quota. |
| `AI_DAILY_QUOTA_SEARCH` | `20` | Per day: `/api/search`, `/api/search/sync` and chat full plans. |
| `AI_DAILY_QUOTA_CHAT` | `100` | Per day: `/api/chat`. |
| `AI_DAILY_QUOTA_COMPARE` | `40` | Per day: `/api/compare/destination`. |
| `AI_DAILY_QUOTA_DISCOVER` | `20` | Per day: `/api/discover`. |
| `AI_DAILY_QUOTA_LIGHT_AI` | `200` | Per day: the light-AI routes. |
| `AI_DAILY_QUOTA_IMPORT` | `20` | Per day: `/api/import/extract`. |
| `GAME_ENABLED` | `true` | XP, badges, levels and streaks (`GET /api/game/*` answer 404 when off). |
| `GAME_RULES_PATH` | `""` | Alternative rules file; empty uses `backend/app/game/rules.json`. |

### Trips and the journey

See [Trips API](Trips-API.md). `GET /api/config` reports the two flags as `features.journey` and `features.offline_pack`.

| Variable | Default | Meaning |
|---|---|---|
| `JOURNEY_UI_ENABLED` | `true` | Turns on the journey UI in the web app: Trips hub, trip screen with phases, Explore, Play and You tabs. The trips API is always served. The owner can set `JOURNEY_UI_ENABLED=false` in `app.env` and restart the app to turn it off, with no rebuild. |
| `OFFLINE_PACK_ENABLED` | `true` | Kill switch for the offline pack. `false` makes every client unregister `/sw.js`, clear its caches and delete saved packs on its next load (see [Deployment on GCP](Deployment-GCP.md#offline-pack-and-the-journey-flag)). |
| `READY_WINDOW_DAYS` | `14` | Days before the start date at which a dated trip becomes Ready. |
| `TRIP_MAX_EXPENSES` | `2000` | Expenses per trip (`409 expense_limit` beyond). |
| `TRIP_MAX_JOURNAL` | `500` | Journal entries per trip (`409 journal_limit`). |
| `TRIP_MAX_PLACES` | `1000` | Rated or visited places per trip (`409 places_limit`). |
| `TRIP_SNAPSHOT_MAX_BYTES` | `262144` | Largest offline snapshot per trip (`413 snapshot_too_large`). |

## Rate limits

AI-calling endpoints are rate-limited per signed-in user, or per client IP for anonymous callers, in an in-process sliding window (`backend/app/core/rate_limit.py`). See [API Reference](API-Reference.md#rate-limits) for the endpoints in each bucket.

| Variable | Default | Applies to |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Master switch. The test suite sets it to `false`. |
| `RATE_LIMIT_WINDOW_SECONDS` | `600` | Window length. |
| `RATE_LIMIT_SEARCH` | `10` | `/api/search`, `/api/search/sync`, and full trip plans started from chat (`/api/chat` also charges its own bucket) |
| `RATE_LIMIT_CHAT` | `30` | `/api/chat` |
| `RATE_LIMIT_COMPARE` | `30` | `/api/compare/destination` |
| `RATE_LIMIT_DISCOVER` | `10` | `/api/discover` |
| `RATE_LIMIT_IMPORT` | `20` | `/api/import/extract` (plan from a link, text or screenshots) |
| `RATE_LIMIT_TELEMETRY` | `120` | `POST /api/telemetry` (batches per caller; a real web client sends about 40 per 10 minutes; not an AI route, so never behind `ALLOW_ANONYMOUS_AI`). The total across callers is bounded by `TELEMETRY_MAX_DB_MB` and `TELEMETRY_MAX_EVENTS_PER_DAY`. |
| `RATE_LIMIT_LIGHT_AI` | `60` | Single-agent routes, `/*/filtered`, `/api/flights/fare-calendar`, `/api/stress-test`, `/api/layover`, `/api/events`, `/api/walking-tours`, creating a fare watch, its "Check now", `/api/nearby`, `/api/live-check` and changing the account email |
| `RATE_LIMIT_SOCIAL_WRITE` | `30` | Phase 5: social writes per user (profile, follow, block, ideas, comments, reports); not an AI route. |
| `RATE_LIMIT_SOCIAL_READ` | `120` | Phase 5: social reads per user (profiles, lists, feed). |
| `RATE_LIMIT_PLAY` | `60` | Phase 5: every `/api/play/*` route per user. |
| `RATE_LIMIT_ADMIN` | `120` | Phase 5: the admin moderation queue and decisions per user. |
| `RATE_LIMIT_SHARE_PUBLIC` | `120` | Public share routes (`GET /api/share/{token}`, `/page` and `/card.png`), per client IP. |
| `RATE_LIMIT_SHARE_MANAGE` | `30` | `/api/shares` create, list and revoke, per signed-in user. |
| `RATE_LIMIT_LOGIN` | `10` | `/api/auth/login` attempts per client IP |
| `RATE_LIMIT_LOGIN_FAILURES` | `10` | Failed logins per username **from one client IP** per window; over it that IP waits for that username (checked before bcrypt, even for a correct password). Failures from other IPs never lock the real user out. |
| `RATE_LIMIT_LOGIN_FAILURES_GLOBAL` | `200` | Failed logins per username from all IPs together: a backstop against distributed guessing |
| `RATE_LIMIT_AUTH_EMAIL` | `10` | Verify-email and password-reset requests per client IP |
| `RATE_LIMIT_EMAIL_ADDRESS` | `3` | Emails sent to one address per window (verify, reset, resend), so nobody can be mail-bombed |
| `RATE_LIMIT_SIGNUP` | `5` | `/api/auth/signup` per client IP |
| `RATE_LIMIT_OAUTH` | `30` | `/api/auth/oauth/*` per client IP |
| `RATE_LIMIT_REFRESH` | `60` | `/api/auth/refresh` per client IP |
| `RATE_LIMIT_ACCOUNT` | `30` | Account writes: profile, settings, onboarding, avatar, delete |

Counters live in process memory: they reset on restart and are not shared between processes or instances, so a multi-instance deployment would need a shared store. Anonymous callers are keyed by the connecting address; behind a reverse proxy all anonymous traffic shares one key unless the proxy address is replaced (for example with uvicorn `--proxy-headers`).

## Production (container entrypoint)

The image starts with `python -m app.entrypoint`, which execs uvicorn (one worker, `--timeout-graceful-shutdown 5`).

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_MANAGER_SECRETS` | `""` | Comma-separated env vars to read from Secret Manager at start (Application Default Credentials), into the process environment only, never a file. The secret id is the lower-cased, dashed name (`JWT_SECRET_KEY` → `jwt-secret-key`), or give it as `ENV=secret-id`. A secret with no version is skipped; a variable already set wins. Any other error stops the start. |
| `GOOGLE_CLOUD_PROJECT` | from ADC | Project for Secret Manager (and FCM ADC). The entrypoint sets it from the metadata server when missing. |
| `FORWARDED_ALLOW_IPS` | `""` | Addresses or networks of the reverse proxy whose `X-Forwarded-For` is trusted (production: the compose network `172.30.0.0/24`). Empty turns proxy headers off. `*` and `0.0.0.0/0` are refused. |
| `ALLOW_ANONYMOUS_AI` | `true` | `false` (production) makes every AI route answer `401` unless signed in. |
| `SSE_KEEPALIVE_SECONDS` | `15` | `/api/search` and `/api/chat` send a `: keepalive` comment after this much silence. When the client disconnects, every task the stream started is cancelled. |
| `PORT`, `GRACEFUL_SHUTDOWN_SECONDS` | `8001`, `5` | uvicorn port and graceful-shutdown timeout. |

The entrypoint refuses to start when `JWT_SECRET_KEY` is empty after the secrets are read.

## Logging

`LOG_FORMAT` is read directly with `os.getenv` in `backend/app/main.py`, not through Settings. The default, `json`, gives one JSON object per line (stdlib `logging` with a custom formatter in `backend/app/core/logging_config.py`). Any other value gives plain-text logs.

---

## Frontend

The frontend reads no environment variables at build or run time.

- **Dev:** Vite proxies `/api` and `/health` to `http://localhost:8001` (`frontend/vite.config.js`).
- **Container:** nginx renders `frontend/nginx.conf.template` with `BACKEND_URL` (envsubst) and proxies `/api/` and `/health` to it. Proxy buffering is off so SSE streams, with a 120 s read timeout. `/api/` allows request bodies up to 32 MB (`client_max_body_size 32m`) for screenshot imports; the backend itself refuses import bodies over 30 MB.

Browser storage used by the app: `tp_token` (login token), `tp_recent_searches_open`, `tp_tour_done:<username>`, `chat_history_<username>`, and the packing-list checkbox state.

---

## Examples

`backend/.env` for local development:

```env
# Claude: an Anthropic key and no GCP_PROJECT (LLM_PROVIDER=auto picks anthropic)
ANTHROPIC_API_KEY=sk-ant-...
# …or Gemini on Vertex AI (after `gcloud auth application-default login`):
# GCP_PROJECT=voyager-prod-ohzkl
JWT_SECRET_KEY=3f0c...   # 64 hex characters
ADMIN_PASSWORD=LocalDevPassword123
# Optional
SERPAPI_KEY=
SERPER_KEY=
FCM_SERVICE_ACCOUNT_FILE=   # e.g. /path/to/firebase-service-account.json (git-ignored name)
RATE_LIMIT_ENABLED=false
LOG_FORMAT=text
```

Values set by `docker-compose.yml`: `LLM_PROVIDER` (default `auto`), `GCP_PROJECT`, `GCP_LOCATION` (default `global`), `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY` (default `change-me-in-compose`), `ADMIN_PASSWORD` (default `admin-dev-password`), `DATA_DIR=/data`, `BACKUP_BUCKET=` (empty) and `CORS_ORIGINS=http://localhost:8080` for the backend, and `BACKEND_URL=http://backend:8001` for the frontend.

Production on the VM (see [Deployment on GCP](Deployment-GCP.md)): `deploy/gcp/compose.yaml` sets `DATA_DIR=/data` (the disk), `BACKUP_MODE=vm`, `BACKUP_EXPORT_DIR=/tmp` (tmpfs), `AGENTS_DIR`, `FORWARDED_ALLOW_IPS=172.30.0.0/24` and `LOG_FORMAT=json`. Everything else is in `/opt/voyager/app.env` (`deploy/gcp/app.env.example`): `SECRET_MANAGER_SECRETS`, `BACKUP_BUCKET`, `ALLOW_ANONYMOUS_AI=false`, `FCM_USE_ADC=true`, `LLM_PROVIDER=gemini`, `GCP_PROJECT`, `GCP_LOCATION`, the SMTP settings and `FARE_WATCH_DAILY_CALL_BUDGET=6`.
