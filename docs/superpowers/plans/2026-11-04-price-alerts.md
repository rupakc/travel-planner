# Fare Watch & Price Alerts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A traveller can "watch" the fare for a trip (from the Flights section, the fare calendar, My Plan or a saved plan). The app re-checks live Google Flights prices on a schedule and tells them — in the app (bell + alerts page), optionally by email and by a browser notification — when the price drops, hits their target, or a cheaper nearby date appears, with a one-click way to re-plan or book. It must feel like a helpful friend watching prices, never spammy.

**Spec:** User request 2026-11-04 — feature #2 "Price alerts on saved trips", "very thoroughly and comprehensively … ENSURE THESE FEATURES DELIGHT USERS". Design choices are Claude's.

## Existing building blocks (verified)
- Live fares: `backend/app/services/serp_flights.py` — `search(api_key, request, filters)` (single-city, cached by `_main_key` incl. traveller count), `search_calendar(api_key, request, window=3)` (cheapest outbound-stage fare per date ±3, `_calendar_key`), `price_insights` (`lowest_price`, `price_level`, `typical_price_range`, `price_history`), `_cheapest`. `settings.serpapi_key`; `/health` reports `serpapi_configured`.
- Routes: `POST /api/flights/fare-calendar` (auth, light_ai bucket, 503 without SerpAPI). Rate limiting: `backend/app/core/rate_limit.py`.
- App startup: `backend/app/main.py` `lifespan` creates tables and starts background tasks (`asyncio.create_task(start_periodic_backup(...))`). SQLite in `$DATA_DIR/airports.db`; helpers in `backend/app/db/*_db.py`; `get_connection()` is a closing context manager. Backups exclude only regenerable place tables — new tables ARE backed up.
- Users have an optional `email` (`backend/app/db/users_db.py`); no email sending exists.
- Frontend: Flights section + `FareCalendarStrip.jsx` + price-insights chip in `ResultsPage.jsx`; My Plan drawer; saved plans (`PlanViewModal.jsx`, ChatPage drawer); header/nav in `App.jsx`; `services/api.js`; `track()` analytics.

## Design (binding)

### Data model (new tables, created in `lifespan`)
- `fare_watches`: id, user_id (FK), plan_id (nullable), origin_code, destination_code (resolved IATA, comma lists allowed), origin_label, destination_label, departure_date, return_date (nullable = one-way), num_travelers, cabin (default economy), flexible_days (0 or 3), alert_mode (`any_drop` | `below_target`), target_price (nullable), email_enabled (bool), status (`active` | `paused` | `expired` | `error`), baseline_price, last_price, lowest_price, lowest_price_date (for flexible), last_notified_price, google_price_level, google_typical_low, google_typical_high, check_count, last_checked_at, next_check_at, lease_until (for safe single-processor scheduling), last_error, created_at, updated_at.
- `fare_watch_history`: watch_id, checked_at, price (selected dates), cheapest_price, cheapest_departure_date, cheapest_return_date, price_level. Keep ≤ 120 rows per watch.
- `notifications`: id, user_id, kind (`fare_drop` | `fare_target` | `fare_low_level` | `fare_cheaper_date` | `watch_expired` | `watch_error`), title, body, data JSON (watch_id, prices, dates, deep links), created_at, read_at, emailed_at.
- Limits: `FARE_WATCH_MAX_ACTIVE_PER_USER` (default 10).

### Scheduler (`backend/app/services/fare_watch.py`)
- Started in `lifespan` only when `serpapi_key` is set and `FARE_WATCH_ENABLED` (default true); loop every `FARE_WATCH_TICK_SECONDS` (default 300): claim due watches (`status='active' AND next_check_at <= now AND (lease_until IS NULL OR lease_until < now)`) with an atomic UPDATE setting `lease_until` (safe if several workers ever run), process with a concurrency semaphore (3), then set `next_check_at = now + FARE_WATCH_INTERVAL_HOURS (default 12) ± 10% jitter`.
- **Quota guard:** `FARE_WATCH_DAILY_CALL_BUDGET` (default 200 SerpAPI calls/day, persisted counter in `meta`-like table keyed by UTC date); when exhausted, postpone remaining checks to the next day and log once. One check = 1 SerpAPI call for exact dates (outbound-stage price via the same code path the calendar uses), or the calendar's up-to-7 calls when `flexible_days=3` — cached results are reused and cost nothing.
- Departure date passed (or < today + 1) → status `expired` + a `watch_expired` notification (once).
- Repeated SerpAPI failures (3 in a row) → status `error` + `watch_error` notification with a "Retry" action; transient failures just reschedule sooner (1 h).
- **Trigger rules** (pure function `evaluate(watch, new_check) -> list[Notification]`, heavily unit-tested):
  1. `below_target`: price ≤ target and the last notification for this watch wasn't already at ≤ this price → `fare_target`.
  2. `any_drop`: price ≤ `last_notified_price or baseline` − max($15, 5 %) → `fare_drop` ("dropped $46").
  3. New lowest since watching AND Google `price_level == "low"` → `fare_low_level` ("Google says this is a low price for this route").
  4. Flexible watches: a nearby date is cheaper than the selected dates by ≥ max($25, 8 %) → `fare_cheaper_date`.
  - **Anti-spam:** at most one notification per watch per 24 h unless the price drops a further ≥ 5 % below the last notified price; never notify for increases (but record them); never notify on the first check after creation (that sets the baseline).
- Prices are per the request's traveller count — label everything "total for N travellers" consistently with the Flights section.

### Notifications delivery
- **In-app:** `GET /api/notifications?unread_only=` (paginated), `POST /api/notifications/read` (ids or all), `GET /api/notifications/unread-count`. Header bell with unread badge in `App.jsx`, dropdown with the latest 10 (icon per kind, relative time, primary action), "Mark all as read", link to the Alerts page. Poll unread count every 60 s while the tab is visible (pause when hidden; refresh on focus).
- **Browser notifications:** when the app is open and the user has granted permission, show a native notification for new fare notifications (asked contextually — after creating the first watch, with an explanatory inline prompt, never on page load).
- **Email (optional):** SMTP via stdlib `smtplib` in a thread (`asyncio.to_thread`) when `SMTP_HOST` is configured (`SMTP_PORT` default 587, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` default true) and the watch has `email_enabled` and the user has an email. Multipart text + HTML (inline-styled, no remote images): headline, route, dates, old → new price with the delta, lowest seen, a tiny inline-SVG-free text sparkline (e.g. ▁▂▄▂▁), CTA links ("See flights", "Re-plan with this fare") to `APP_BASE_URL` (new setting, default `http://localhost:5174`), and an unsubscribe-from-this-watch link (signed token endpoint `GET /api/fare-watches/unsubscribe?token=` that turns off email for that watch without login). Failures logged, never break checks.
- Users without an email can add one on the Preferences page (new field, validated) — the create-watch dialog links there.

### API (auth required; ownership enforced on every route → 404 for others' resources)
- `POST /api/fare-watches` — from a `TravelSearchRequest`-like body (origin, destination, dates, travellers) or `{ plan_id }`; resolves codes via the existing request validators (typed cities work); takes an immediate first check (baseline) inline if quota allows (else schedules it), returns the watch with history.
- `GET /api/fare-watches` (with latest history + sparkline points), `GET /api/fare-watches/{id}`, `PATCH /api/fare-watches/{id}` (status pause/resume, alert_mode, target, email_enabled, flexible_days), `DELETE /api/fare-watches/{id}`, `POST /api/fare-watches/{id}/check` ("Check now", rate-limited `light_ai`, also subject to the daily budget).
- 503 with a friendly detail when SerpAPI isn't configured; multi-city trips → 422 "Fare watch works for single-destination trips for now".

### Frontend (delight is a requirement)
1. **"Watch this fare" entry points:** a bell-plus button in the Flights section header (next to Fare calendar / Filters), on the fare-calendar strip ("Watch these dates"), on a selected flight in My Plan, and on saved-plan cards / PlanViewModal. If already watched → "Watching · $412" state that opens the watch.
2. **Create dialog:** shows the current price and Google's typical range bar with today's price marked; options "Tell me about any drop" (default) / "Tell me when it's below $___" (pre-filled with the low end of the typical range, validated), "Include nearby dates (±3 days)" toggle with an explanation, "Also email me" (disabled with a link to add an email if none; hidden if SMTP isn't configured — expose `email_alerts_available` in `/health` or a small config endpoint). Success state with a friendly confirmation and (first time only) the browser-notification prompt.
3. **Alerts page (`/alerts`, nav item with badge):** a card per watch — route with city names, dates, travellers, current price (big), change since watching (green/red), lowest seen, Google price level chip, a small SVG sparkline of price history with the target line, last checked ("2 h ago"), next check, status chip (Watching / Paused / Price dropped! / Expired / Problem). Actions: Check now (with spinner, respects rate limit message), Pause/Resume, Edit (target/mode/flex/email), Delete (confirm inline, not a modal dialog), **Re-plan with this fare** (runs the normal search with the watch's dates or the cheapest nearby dates), **Book on Google Flights** (existing booking URL format). Group by Active / Past. Empty state that explains the value with an illustration-free friendly design and a CTA to search.
4. **Notification UX:** bell dropdown items read naturally ("✈️ Berlin → Lisbon dropped to $142 (−$46) for 1–8 Dec — the lowest we've seen"), clicking opens the Alerts page scrolled to that watch and marks it read; toast for new alerts while the app is open (one at a time, dismissible).
5. **Quality bar:** responsive to 360 px, keyboard accessible, ARIA live regions for toasts/badge changes, reduced motion respected, consistent Tailwind/lucide style, no layout shift, no polling while hidden. Analytics via `track()` (watch_created/mode/flex, watch_checked_now, alert_clicked/kind, watch_replanned, watch_booked).

### Docs
Trip-Planning-Features.md (Fare watch & alerts), API-Reference.md (all endpoints), Configuration.md (all new settings: FARE_WATCH_*, SMTP_*, APP_BASE_URL), Architecture.md (scheduler, tables — update the table count), Deployment.md (single-worker note, SMTP), CLAUDE.md one line, Changelog, README feature bullet.

## Global Constraints
No new dependencies (stdlib smtplib/email, existing httpx). No network in tests (mock SerpAPI `_call`, SMTP via a fake). Scheduler testable with an injected clock; tests must not start the real loop. Backend pytest + ruff; frontend vitest + eslint + build. Existing tests stay green. Never log SMTP passwords or full emails.

---
### Task 1: Tables + trigger rules (`evaluate`) + check logic with quota/expiry/error handling (+unit tests with fake clock and mocked SerpAPI)
### Task 2: Scheduler loop with leasing + lifespan wiring + API routes + notifications API + unsubscribe token + email sender (+tests)
### Task 3: Frontend: watch buttons, create dialog, Alerts page with sparkline, bell + dropdown + toasts + browser notifications, Preferences email field (+tests)
### Task 4: Docs
