# Phase 0 — Foundations (theme + dark mode, i18n, telemetry, parity matrix) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web app the three foundations every later phase builds on: a token-driven theme with a
user-selectable dark mode, full UI translation into 7 languages, and a zero-cost telemetry pipeline (backend +
web SDK). Also write the cross-client feature-parity matrix.

**Architecture:** Every Tailwind colour family the app uses is remapped to CSS variables that flip under
`html.dark`, so the ~17k lines of existing JSX get dark mode without class rewrites; hand tuning follows.
i18n is `i18next` + `react-i18next` with one JSON file per *namespace per language*, so the extraction tasks
run in parallel without touching each other's files. English is bundled; other languages load lazily.
Telemetry is a new anonymous-capable `POST /api/telemetry` that validates every event against a closed registry
(no free text can get in) and appends to a separate `telemetry.db`. A small web SDK batches events in the
background with delegated auto-capture.

**Tech Stack:** FastAPI + SQLite (backend); React 18, Tailwind 3.4, Vite 6, vitest, i18next ^27 + react-i18next ^18 (frontend; peer `react >= 18`, checked on npm 2026-11-10 — pin a release at least 2 weeks old).

**Spec:** `docs/superpowers/specs/2026-11-10-voyager-reimagined-design.md` (§8 Telemetry, §9 Look, feel, language, §10 parity, §2 constraints).

## Global Constraints

- Two-way compatibility: the new SPA must work against the previous backend (`/api/config` or `/api/telemetry` 404 → telemetry silently off, no retries). The new backend must keep serving the previous SPA (`POST /api/analytics/events` unchanged).
- Telemetry never blocks or slows the UI: no `await` on the critical path, every SDK entry point wrapped in try/catch, work deferred with `requestIdleCallback` (falling back to `setTimeout(…, 1)`).
- Telemetry never carries free text the user typed, precise location, email/name, or other users' content. The server enforces this with a closed per-event prop schema.
- Telemetry is disclosed and can be switched off (Settings → Privacy). Users whose device timezone is EU/EEA/UK/CH get a one-time consent choice and are opted out until they choose.
- Raw telemetry is kept 90 days in `$DATA_DIR/telemetry.db` and is not backed up. Daily aggregates live in the main DB table `telemetry_daily` and are backed up with the user tables.
- Languages and codes: `en` English, `es` Spanish, `de` Deutsch, `fr` French, `hi` Hindi, `zh` Chinese (Simplified), `bn` Bengali. `en` is the fallback.
- **[call, deviates from spec §9]**: the canonical catalogue lives at `frontend/src/i18n/locales/<lang>/<ns>.json`, not a root `i18n/`. The SPA image build copies only `frontend/`, and the deploy inputs hash/path filters key on it. Plurals use i18next JSON v4 suffixes (`_one`, `_other`, …), which map 1:1 to Android `<plurals>` and iOS String Catalog plural variations. Update the spec text in Task 12.
- Light is the default theme; options are `system` / `light` / `dark`, stored in `localStorage` key `tp_theme`; the language lives in `tp_lang`.
- Never translate: brand "Voyager", airport/IATA codes, currency codes, place names coming from data, AI/static content strings from the backend (server strings stay English in Phase 0, except AI output per Task 11).
- Python 3.12, ruff clean; `npx eslint src/ --max-warnings 0`; `mkdocs build --strict`; every existing test keeps passing.

## Review Focus

1. **Storage/network hostile browsers** (Safari private mode with `localStorage` throwing, ad-blockers blocking `/api/telemetry`, offline): the app works, there's no console spam and no retry storm. → Test in Task 5.
2. **Old backend** (no `/api/config`, `/api/telemetry` → 404): the SDK disables itself for the session after the first 404. → Test in Task 5.
3. **PII sneaking in** (an `id` prop carrying `"jane@x.com"` or `"hello world"`, unknown props, oversized batches): it gets dropped server-side and the request still returns 204. → Test in Task 2.
4. **Dark mode leaking into print/PDF export and Leaflet maps**: print is always light, and map tiles are dimmed rather than inverted in a way that breaks markers. → Test in Task 6.
5. **Missing translation keys and long strings**: a key missing in `de` shows English, never the raw key, and every locale has every `en` key with matching `{{placeholders}}`. → Test in Task 7 (catalogue parity test).

---

### Task 1: Telemetry storage

**Files:**
- Create: `backend/app/db/telemetry_db.py`
- Modify: `backend/app/main.py` (lifespan: create tables; start the maintenance loop from Task 3)
- Modify: `backend/app/db/vm_backup.py` and `backend/app/db/backup.py` (add `telemetry_daily` wherever the user-table list is defined)
- Test: `backend/tests/test_telemetry_db.py`

**Interfaces:**
- Produces:
  - `telemetry_db_path() -> Path` → `Path(settings.data_dir) / "telemetry.db"`
  - `create_telemetry_tables() -> None`. In telemetry.db: `telemetry_events(id INTEGER PK, ts INTEGER ms, received_at INTEGER ms, event TEXT, session_id TEXT, anon_id TEXT, user_id TEXT NULL, platform TEXT, app_version TEXT, locale TEXT, screen TEXT NULL, props TEXT json)` with indexes `(ts)`, `(event, ts)`. In the main DB (`get_connection`): `telemetry_daily(day TEXT, event TEXT, platform TEXT, events INTEGER, users INTEGER, sessions INTEGER, PRIMARY KEY(day,event,platform))` and `telemetry_rollups(day TEXT PRIMARY KEY, done_at TEXT)`.
  - `insert_events(rows: list[dict]) -> int` (one transaction, `executemany`, returns the count)
  - `rollup_day(day: str) -> int` (`YYYY-MM-DD` UTC; idempotent: replaces that day's rows, records `telemetry_rollups`; users = distinct `coalesce(user_id, anon_id)`)
  - `prune(before_ms: int) -> int`

- [ ] **Step 1: Write failing tests** `test_insert_and_rollup` (insert 3 events, 2 anon ids, 1 user, 2 sessions on one day → `rollup_day` gives `events=3, users=2, sessions=2`; running it twice gives the same rows), `test_prune_removes_only_older`, `test_telemetry_db_is_separate_file` (after insert, the main DB has no `telemetry_events` table).
- [ ] **Step 2: Run** `cd backend && python3 -m pytest -q tests/test_telemetry_db.py` → FAIL (module missing).
- [ ] **Step 3: Implement** with its own connection helper mirroring `database.get_connection` (WAL, `synchronous=NORMAL`, `busy_timeout=5000`).
- [ ] **Step 4: Run** the test file → PASS; run the full backend suite → PASS.
- [ ] **Step 5: Commit** `feat(telemetry): separate telemetry store with daily rollups`

### Task 2: Event registry + validation

**Files:**
- Create: `backend/app/telemetry/__init__.py`, `backend/app/telemetry/registry.py`
- Test: `backend/tests/test_telemetry_registry.py`

**Interfaces:**
- Produces:
  - `PROP_TYPES = {"id", "int", "float", "bool"} | {"enum:<a|b|c>"}`. `id` matches `^[A-Za-z0-9_.:/-]{1,64}$` (no spaces or `@`, so no sentences and no emails).
  - `EVENTS: dict[str, dict[str, str]]` (event → prop → type). It ships with at least the families from spec §8:
    `app_open`, `app_background`, `session_start`, `screen_view{route:id, referrer_route:id}`, `screen_time{route:id, ms:int}`,
    `ui_tap{tid:id, route:id}`, `ui_toggle{tid:id, route:id, on:bool}`, `ui_submit{tid:id, route:id}`,
    `search_submit{mode:enum:<search|chat|compare|link|discover>, travelers:int, nights:int, multi_city:bool}`,
    `search_first_section{ms:int}`, `search_complete{ms:int, sections:int, errors:int}`, `search_abandon{ms:int, sections:int}`,
    `section_expand{section:id}`, `plan_select{section:id}`, `link_out{section:id, domain:id}`,
    `share{target:id, object:id}`, `alert_event{action:id, kind:id}`, `onboarding_step{step:int, action:enum:<view|next|skip|done>}`,
    `theme_change{theme:enum:<system|light|dark>}`, `language_change{lang:enum:<en|es|de|fr|hi|zh|bn>}`, `consent{choice:enum:<granted|denied>}`,
    `feature_used{feature:id, page:id}` (bridge from the old `track()`),
    `perf{metric:enum:<ttfb|fcp|lcp|inp|cls|long_task|cold_start>, value:float, route:id}`, `error{kind:enum:<js|promise|api>, source:id, status:int}`.
  - `clean_event(raw: dict) -> dict | None`: unknown event → `None`. Unknown props or props failing their type are dropped, not the whole event. Strings longer than 64 are dropped. `ts` must be within ±7 days of server time, else replaced by the server time.
  - `clean_client(raw: dict) -> dict | None`: `anon_id` (UUID), `session_id` (UUID), `platform` enum `web|android|ios`, `app_version` id, `locale` id ≤ 16; invalid → `None`.

- [ ] **Step 1: Write failing tests**: `clean_event({"event":"ui_tap","props":{"tid":"jane@x.com","route":"/results"}})["props"] == {"route":"/results"}`; `"hello world"` dropped the same way; `clean_event({"event":"nope"}) is None`; an enum outside its set is dropped; `test_every_event_documented` (every `EVENTS` key appears in `docs/Telemetry.md`; that doc is written in Task 12, so mark this test `xfail(strict=True)` until then and flip it in Task 12).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (a pure module: no I/O).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(telemetry): closed event registry and validation`

### Task 3: Telemetry + config API, maintenance loop, admin summary

**Files:**
- Create: `backend/app/api/routes/telemetry.py`, `backend/app/api/routes/client_config.py`
- Modify: `backend/app/main.py` (routers; lifespan task), `backend/app/core/config.py`, `backend/app/core/rate_limit.py` (bucket `telemetry`), `backend/app/api/routes/admin.py`
- Test: `backend/tests/test_telemetry_api.py`, `backend/tests/test_client_config.py`

**Interfaces:**
- Consumes: Task 1 `insert_events`, `rollup_day`, `prune`; Task 2 `clean_event`, `clean_client`.
- Produces:
  - Settings: `telemetry_enabled: bool = True`, `telemetry_retention_days: int = 90`, `rate_limit_telemetry: int = 600`, `public_base_url: str = ""`.
  - `POST /api/telemetry`. Body `{"client": {...}, "events": [{"event","ts","screen","props"}]}`, max 100 events, raw body ≤ 64 KB (else 413), accepts `Content-Encoding: gzip` (decompressed ≤ 256 KB). Auth is optional (`get_optional_user`, so `user_id` is the user's id when signed in). Always 204 when well-formed, even if every event was dropped; 422 only for a malformed envelope; 404 when `telemetry_enabled` is false. Inserts via `asyncio.to_thread`. Not behind `require_ai_access`.
  - `GET /api/config` → `{"public_base_url": str, "telemetry": {"enabled": bool, "flush_interval_s": 15, "max_batch": 50}, "features": {"telemetry": true}}`. Public, no rate limit, `Cache-Control: max-age=300`. `public_base_url` defaults to the request's own base URL when the setting is empty.
  - Lifespan task `telemetry_maintenance()`: every hour, roll up every day since the last rollup, up to yesterday (UTC); prune `< now - retention`. Errors are logged, never raised.
  - `GET /api/admin/telemetry/summary?days=30` (admin) → `{"days": [{"day","users","sessions","events"}], "top_events": [{"event","events"}], "top_screens": [{"route","views"}]}` from `telemetry_daily`, plus today's live numbers from raw events.

- [ ] **Step 1: Write failing tests**: anonymous POST → 204 and a row stored with `user_id NULL`; signed-in → `user_id` set; a PII prop is not stored; 101 events → 422; gzip body accepted; `telemetry_enabled=False` → 404; `/api/config` shape; the admin summary needs admin (403 for a user) and returns the rolled-up counts; `POST /api/analytics/events` behaves exactly as before (the existing `test_analytics.py` still passes untouched).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Add the `telemetry` bucket to the `_bucket_limit` mapping.
- [ ] **Step 4: Run** backend suite + `ruff check backend/` → PASS.
- [ ] **Step 5: Commit** `feat(telemetry): ingest endpoint, client config, rollup loop, admin summary`

### Task 4: Theme tokens + dark mode mechanism

**Files:**
- Create: `frontend/design/tokens.json`, `frontend/scripts/build-tokens.mjs`, `frontend/src/theme/tokens.css` (generated, committed), `frontend/src/theme/ThemeContext.jsx`, `frontend/src/theme/themeStorage.js`
- Modify: `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/index.html`, `frontend/src/main.jsx`, `frontend/package.json` (script `tokens`)
- Test: `frontend/src/theme/tokens.test.js`, `frontend/src/theme/ThemeContext.test.jsx`

**Interfaces:**
- Produces:
  - `tokens.json`: `{ "palette": { "<family>": { "50": "#…", …, "950": "#…" } }, "dark": { "<family>": {…} }, "semantic": { "surface", "surface-raised", "text", "text-muted", "border", "accent": … } }`. The families are exactly those the code uses: `gray slate stone teal amber sky red emerald green violet rose cyan blue purple yellow indigo pink orange lime fuchsia`, plus `primary` (the current teal ramp), a new `accent` coral ramp, and `white`. Light values = Tailwind 3.4 defaults (so light mode looks identical to today). Dark values: neutral ramps reversed (50↔950, 100↔900, …) and nudged to a blue-grey night palette; colour ramps reversed with saturation reduced ~15 % for the light end; `white` → `#111827`-ish raised surface. `black` is *not* remapped (it's used for overlays).
  - `build-tokens.mjs` writes `tokens.css`: `:root { --c-gray-50: 249 250 251; … }` and `html.dark { … }` as space-separated RGB channels.
  - Tailwind: `darkMode: 'class'`; every family above becomes `{ 50: 'rgb(var(--c-gray-50) / <alpha-value>)', … }`.
  - `ThemeProvider`, `useTheme() -> { theme: 'system'|'light'|'dark', resolved: 'light'|'dark', setTheme(t) }`. It toggles `html.dark`, sets `color-scheme`, and updates `<meta name="theme-color">` (light `#ffffff`, dark the dark surface). `system` follows `matchMedia('(prefers-color-scheme: dark)')` live. Storage helpers swallow `localStorage` errors.
  - An inline script in `index.html`, before the CSS, applies `dark` from `tp_theme`/the system setting to prevent a flash.

- [ ] **Step 1: Write failing tests**: `tokens.test.js`: running the generator in memory equals the committed `tokens.css` (keeps generated output in sync); every family has 11 stops in both modes; WCAG contrast ≥ 4.5 for `gray-900` on `gray-50` and for `white` text on `teal-600` in both modes (a small `contrast(hexA, hexB)` helper in the test). `ThemeContext.test.jsx`: the default is `system`; `setTheme('dark')` adds `html.dark` and persists; a throwing `localStorage` still works in memory.
- [ ] **Step 2: Run** `cd frontend && npm test -- src/theme` → FAIL.
- [ ] **Step 3: Implement**; replace the hex colours in `.skeleton-shimmer` with variables.
- [ ] **Step 4: Run** the full `npm test` + eslint → PASS (light mode must leave existing tests untouched).
- [ ] **Step 5: Commit** `feat(theme): token-driven palette with class-based dark mode`

### Task 5: Web telemetry SDK

**Files:**
- Create: `frontend/src/telemetry/client.js`, `frontend/src/telemetry/autocapture.js`, `frontend/src/telemetry/consent.js`, `frontend/src/telemetry/perf.js`, `frontend/src/telemetry/routes.js`
- Modify: `frontend/src/utils/analytics.js` (`track()` also emits `feature_used`), `frontend/src/main.jsx` (`initTelemetry()` after render, in idle time), `frontend/src/App.jsx` (screen views on location change)
- Test: `frontend/src/telemetry/client.test.js`, `consent.test.js`, `autocapture.test.js`

**Interfaces:**
- Consumes: Task 3 `GET /api/config`, `POST /api/telemetry` (shapes above).
- Produces:
  - `initTelemetry({ appVersion }) -> void` (fetches `/api/config` once. A 404 or `enabled:false` → off for the session; consent denied → off).
  - `emit(event: string, props?: object) -> void` (never throws; no-op when off).
  - `setUserPresent(bool)` (no ids are stored client-side; the server derives `user_id` from the bearer token, which the client attaches when present).
  - Queue rules: flush every `flush_interval_s` or at `max_batch`; on `visibilitychange→hidden` use `navigator.sendBeacon` with a `Blob` (`application/json`), since `sendBeacon` can't send auth headers. Beacon flushes are therefore anonymous, so pending events are flushed with `fetch(…, {keepalive:true})` + auth first when signed in, with the beacon as fallback. The queue persists to `localStorage` key `tp_tq` (cap 500, oldest dropped). After 3 consecutive network failures, exponential backoff up to 5 min. 404 → disable.
  - `anon_id` in `localStorage` `tp_anon` (UUID via `crypto.randomUUID`, with a fallback); `session_id` rotates after 30 min idle.
  - `consent.js`: `consentRequired(tz = Intl.DateTimeFormat().resolvedOptions().timeZone) -> bool` (true for `Europe/*` except `Europe/Istanbul`, `Europe/Moscow`, `Europe/Minsk`, `Europe/Kiev`/`Europe/Kyiv`; plus `Atlantic/Reykjavik`, `Atlantic/Canary`, `Atlantic/Madeira`, `Atlantic/Azores`, `Atlantic/Faroe`); `getConsent() -> 'granted'|'denied'|null`; `setConsent(choice)` (emits `consent`); `telemetryAllowed() -> bool` (= choice granted, or no choice and not required).
  - `autocapture.js`: one delegated listener each for `click`, `change`, `submit` on `document` (capture phase, passive). Element id = closest `[data-tid]` value; else closest `[id]` as `id:<id>`; else `auto:<tagName lowercase>`. Never reads input values or text content. Route = `routeTemplate(location.pathname)` from `routes.js` (`/share/:token`, `/plans/:id`, … so tokens/ids never get sent).
  - `perf.js`: TTFB/FCP from navigation + paint timing; LCP, INP (approximated from `event` entries' max duration), CLS and long-task count from `PerformanceObserver` where supported; `error` events from `window.error` / `unhandledrejection` with `source` = script file basename + line, never the message.

- [ ] **Step 1: Write failing tests**: with `localStorage` throwing, `emit` doesn't throw and events stay in memory; a fetch rejection 3× → backoff, no 4th immediate call; the first POST 404 → later `emit` calls make no network calls; the `/api/config` 404 → off; consent: `consentRequired('Europe/Berlin') === true`, `('Asia/Kolkata') === false`, `('Europe/Istanbul') === false`; autocapture: clicking `<button data-tid="search.submit">Go</button>` inside a route emits `ui_tap{tid:'search.submit'}`, and an `<input>` change emits no value; `routeTemplate('/share/abc123') === '/share/:token'`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` + eslint → PASS.
- [ ] **Step 5: Commit** `feat(telemetry): background web SDK with auto-capture and consent`

### Task 6: Dark-mode polish across the app

**Files:**
- Modify: components/pages containing hard-coded hex colours (31 occurrences: `grep -rn "#[0-9a-fA-F]\{6\}" frontend/src --include=*.jsx`), `frontend/src/components/TripMap.jsx` (+ any other Leaflet use), `frontend/src/utils/planPrint.js`, `frontend/src/index.css`
- Test: `frontend/src/utils/planPrint.test.js` (extend), `frontend/src/theme/darkSurfaces.test.jsx`

**Interfaces:**
- Consumes: Task 4 variables/`useTheme`.
- Produces: the CSS class `.map-dark-tiles` (on `html.dark .leaflet-tile-pane { filter: brightness(.75) contrast(1.1) saturate(.8) }`, markers untouched). The print document always renders light (`planPrint` HTML sets `color-scheme: light` and inline light colours, and never inherits `html.dark`).

- [ ] **Step 1: Write failing tests**: the `planPrint` output contains `color-scheme: light` and no `var(--c-`; rendering `TripMap` in dark mode produces no inline hex colour from the old literal set.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: replace literals with `rgb(var(--c-…))` or Tailwind classes; review every page in dark mode with the `run` skill (screenshots of Search, Results, Chat, Alerts, Preferences, Share, Admin, Nearby in both themes) and fix any surface that reads wrong (e.g. `bg-white/80` glass headers, gradients `from-teal-50 to-sky-50`).
- [ ] **Step 4: Run** `npm test` + eslint → PASS; attach the screenshot list to the PR.
- [ ] **Step 5: Commit** `feat(theme): dark-mode pass over maps, print and literal colours`

### Task 7: i18n framework + common namespace

**Files:**
- Create: `frontend/src/i18n/index.js`, `frontend/src/i18n/format.js`, `frontend/src/i18n/languages.js`, `frontend/src/i18n/locales/<lang>/common.json` (7 files), `frontend/src/i18n/catalog.test.js`, `frontend/src/components/ui/LanguagePicker.jsx`, `frontend/src/components/ui/ThemeToggle.jsx`
- Modify: `frontend/package.json` (`i18next` ^27, `react-i18next` ^18), `frontend/src/main.jsx`, the vitest setup file (init i18n eagerly with `en`), `frontend/src/components/ui/NavBar.jsx`, `frontend/src/components/ui/AttributionFooter.jsx` (move their strings into `common`)
- Test: `catalog.test.js`, `frontend/src/i18n/format.test.js`, `NavBar.test.jsx` (extend)

**Interfaces:**
- Produces:
  - `LANGUAGES = [{code:'en', native:'English'}, {code:'es', native:'Español'}, {code:'de', native:'Deutsch'}, {code:'fr', native:'Français'}, {code:'hi', native:'हिन्दी'}, {code:'zh', native:'中文（简体）'}, {code:'bn', native:'বাংলা'}]`
  - `initI18n() -> Promise<void>`: `en` resources imported statically for every namespace (`import.meta.glob('./locales/en/*.json', {eager:true})`); others via `import.meta.glob('./locales/*/*.json')` lazy backend; `fallbackLng: 'en'`, `returnNull:false`, `returnEmptyString:false`, `interpolation.escapeValue:false`. Detection: `tp_lang` → `navigator.languages` (`zh-*` → `zh`) → `en`. On change: set `<html lang>` and lazy-load the Noto font (`Noto Sans Devanagari` for hi, `Noto Sans Bengali` for bn, `Noto Sans SC` for zh) by injecting one Google Fonts `<link>` once.
  - `setLanguage(code)` (persists `tp_lang`, emits `language_change`).
  - `format.js`: `fmtDate(d, opts)`, `fmtNumber(n, opts)`, `fmtCurrency(n, currency)`, `fmtRelative(ms)` (all `Intl.*` with `i18n.language`; `zh` → `zh-CN`, `hi` → `hi-IN`, `bn` → `bn-IN`).
  - Key convention: `ns:area.thing` (e.g. `common:nav.search`), English sentence case; interpolation `{{name}}`; plurals `_one`/`_other` (plus whatever `Intl.PluralRules` needs per language). Every interactive element touched gets a `data-tid` (`area.thing`) for telemetry.
  - `LanguagePicker` (native names), `ThemeToggle` (system/light/dark) in NavBar, emitting `theme_change` / `language_change`.
  - `catalog.test.js` (catalogue rules): for every namespace and language, the key set equals `en`'s (plural-aware: a language may need more or fewer plural suffixes per `Intl.PluralRules(lang).resolvedOptions().pluralCategories`); no empty values; `{{placeholders}}` match `en`; no value equals its key; JSON is valid.
- [ ] **Step 1: Write failing tests**: the catalogue rules; `fmtCurrency(1234.5,'EUR')` in `de` → contains `1.234,50`; in `hi` it uses Indian grouping for `fmtNumber(1234567)` (`12,34,567`); a key missing in `de` renders the English text; NavBar shows `Deutsch` in the picker and switches labels.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; translate `common` into all 6 languages.
- [ ] **Step 4: Run** `npm test` + eslint + `npm run build` (check `de`/`hi` chunks are split out of the main bundle) → PASS.
- [ ] **Step 5: Commit** `feat(i18n): i18next framework, language + theme pickers, common catalogue`

### Task 8: String extraction (parallel, one namespace per task)

Each sub-task is independent. It owns only its namespace files and its listed source files, so all of them run
in parallel worktrees once Task 7 is merged.

| Sub-task | Namespace | Source files |
|---|---|---|
| 8a | `search` | `pages/SearchPage.jsx`, `components/ui/AirportSearch.jsx`, `NationalitySearch.jsx`, `TagInput.jsx`, `TravelerPanel.jsx`, `components/RecentSearches.jsx`, `components/import/*` |
| 8b | `results` | `pages/ResultsPage.jsx` (lines 1–2200) |
| 8c | `results` sections | `pages/ResultsPage.jsx` (lines 2200–end): use the namespace `sections` to avoid colliding with 8b. 8b and 8c touch disjoint line ranges of one file, so 8c starts from 8b's merged result |
| 8d | `chat` | `pages/ChatPage.jsx`, `utils/chatHistory.js` (user-visible strings only) |
| 8e | `plan` | `PlanViewModal`, `PlanExport`, `CostBreakdown`, `BudgetPlanner`, `BestValuePackage`, `utils/planExport.js`, `utils/planPrint.js` |
| 8f | `itinerary` | `ItinerarySection`, `TimelineView`, `TripMap`, `WalkingToursSection` |
| 8g | `alerts` | `pages/AlertsPage.jsx`, `components/alerts/**`, `context/AlertsContext.jsx` (toast copy), `FareCalendarStrip` |
| 8h | `account` | `LoginPage`, `ChangePasswordPage`, `PreferencesPage`, `AdminPage` |
| 8i | `misc` | `SharePage`, `NearbyPage`, `CompareTable`, `FeedbackWidget`, `OnboardingTour`, `utils/tour.js`, `VerificationBadge`, `FromLinkChip`, `LinkPlanBanner`, `utils/verification.js` (labels shown in the UI) |

**Interfaces:**
- Consumes: Task 7 `useTranslation`, `format.js`, the key convention.
- Produces: `locales/en/<ns>.json` + 6 translations per namespace; hard-coded `toLocaleString('en-US', …)`/`toLocaleDateString` calls in those files switched to `format.js`; `data-tid` on every button/link/toggle in those files.

Steps for each sub-task:
- [ ] **Step 1:** Extract every user-visible literal (JSX text, `placeholder`, `title`, `aria-label`, `alt`, toast/confirm text) into `en/<ns>.json`. Leave alone: test ids, enum values compared in logic, backend-provided strings and URLs.
- [ ] **Step 2:** Run the namespace's existing tests. They must pass unchanged, since English is the test locale. If a test asserted on text that changed, the extraction changed copy, so fix the extraction, not the test.
- [ ] **Step 3:** Translate the namespace into es, de, fr, hi, zh, bn. Keep `{{placeholders}}`, brand and codes; use natural travel-app register (informal "tú" in es, "du" in de, "vous" in fr, neutral Hindi in Devanagari, standard Bengali, Simplified Chinese).
- [ ] **Step 4:** Run `npm test` (the catalogue rules must pass) + eslint → PASS.
- [ ] **Step 5:** Commit `feat(i18n): <ns> namespace in 7 languages`.

### Task 9: Translation review pass

**Files:** `frontend/src/i18n/locales/{es,de,fr,hi,zh,bn}/*.json`
- [ ] **Step 1:** For each language, a fresh reviewer agent reads `en` + that language side by side and fixes meaning errors, wrong register, untranslated strings, and wording likely to overflow (German/Bengali > 1.6× `en` length on buttons gets a shorter wording).
- [ ] **Step 2:** `npm test` → PASS. Screenshot Search + Results in `de` and `bn` to check for overflow.
- [ ] **Step 3:** Commit `fix(i18n): translation review`.

### Task 10: Privacy settings + consent prompt

**Files:**
- Create: `frontend/src/components/ConsentPrompt.jsx`, `frontend/src/i18n/locales/<lang>/privacy.json`
- Modify: `frontend/src/App.jsx` (mount the prompt), `frontend/src/pages/PreferencesPage.jsx` (sections Appearance — theme + language; Privacy — "Help improve Voyager" switch with a one-line explanation and a privacy policy link)
- Create: `docs/Privacy.md` (what is collected, the never-collected list, retention 90 days, how to switch off)
- Test: `frontend/src/components/ConsentPrompt.test.jsx`

**Interfaces:**
- Consumes: Task 5 `consentRequired`, `getConsent`, `setConsent`.
- Produces: a small bottom sheet (not a modal; doesn't block interaction), shown once when `consentRequired() && getConsent() === null`, with two equal-weight buttons "Allow" / "No thanks" (`data-tid` `privacy.allow` / `privacy.deny`).

- [ ] **Step 1: Write failing tests**: shown for `Europe/Paris`, not for `America/New_York`; after a choice it's never shown again; the Preferences switch flips `telemetryAllowed()`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(privacy): consent prompt and privacy settings`

### Task 11: AI output in the user's language

**Files:**
- Modify: `backend/app/schemas/request.py` (optional `locale: Literal['en','es','de','fr','hi','zh','bn'] | None = None` on `TravelSearchRequest` and the chat request model), `backend/app/agents/base_agent.py` (system-prompt suffix), the search cache key builder (include `locale`), `frontend/src/services/api.js` (send `locale: i18n.language` on search/chat)
- Test: `backend/tests/test_locale_prompt.py`

**Interfaces:**
- Produces: `language_instruction(locale: str | None) -> str` in `base_agent.py`. It returns `""` for `None`/`en`; otherwise exactly: `"Write every human-readable text value in {Language name in English}. Keep JSON keys, enum values, codes, URLs, prices, currency codes, dates and proper names of places exactly as you would in English output."`. An older SPA sends no `locale` and gets English, unchanged.

- [ ] **Step 1: Write failing tests**: the instruction is absent for `None`/`en` and present for `de`; two searches differing only in `locale` don't share a cache entry; an unknown locale → 422.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the backend suite → PASS.
- [ ] **Step 5: Commit** `feat(i18n): agents answer in the user's language`

### Task 12: Docs, parity matrix, spec + CLAUDE.md sync

**Files:**
- Create: `docs/Telemetry.md` (envelope, every event + props table, client rules, privacy), `docs/Internationalization.md`, `docs/Theming.md`, `docs/Feature-Parity.md`
- Modify: `mkdocs.yml` nav, `CLAUDE.md` (new routes, `telemetry.db`, i18n/theme dirs, settings), `docs/Configuration.md` (new settings), `docs/API-Reference.md`, the spec §9 sentence about the catalogue location/plural format, `backend/tests/test_telemetry_registry.py` (remove the `xfail`)
- [ ] **Step 1:** `Feature-Parity.md`: one row per user-facing feature (web today, from CLAUDE.md + pages), columns Web / Android / iOS with ✅ / ⏳ phase / —. Fill the Android column from the Android repo's README/feature list (`~/.local/bin/gh api repos/rupakc/travel-planner-android/readme`); iOS is all ⏳ Phase 7.
- [ ] **Step 2:** Run `mkdocs build --strict`, the backend suite (the registry doc test now passes) → PASS.
- [ ] **Step 3:** Commit `docs: telemetry, i18n, theming, feature parity`.

### Task 13: Admin analytics tab

**Files:**
- Create: `frontend/src/components/admin/TelemetrySummary.jsx` (+ `.test.jsx`), `frontend/src/i18n/locales/<lang>/admin.json` keys under `telemetry.*` (coordinate with 8h: 8h owns `account`; this task owns the separate namespace `adminTelemetry`)
- Modify: `frontend/src/pages/AdminPage.jsx` (new "Analytics" tab), `frontend/src/services/api.js` (`getTelemetrySummary(days)`)

**Interfaces:**
- Consumes: Task 3 `GET /api/admin/telemetry/summary`.
- Produces: an "Analytics" tab with stat tiles (users and sessions today, 7-day users), a 30-day daily-users chart (inline SVG; follow the `dataviz` skill), and top events and top screens tables. A 404 from an older backend → the tab is hidden.

- [ ] **Step 1: Write failing tests**: renders tiles from a mocked summary; the tab is hidden on 404.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(admin): telemetry analytics tab`

### Task 14: Sign-in buttons on the login page (owner request, 2026-11-10)

The OAuth flows themselves are Phase 1. This task puts the buttons in the UI now.

**Files:**
- Create: `frontend/src/components/auth/SocialSignInButtons.jsx` (+ `.test.jsx`), `frontend/src/components/auth/providerIcons.jsx` (inline SVG marks drawn to each provider's published brand guidelines: Google "G", Facebook "f", GitHub mark, Apple logo), `frontend/src/i18n/locales/<lang>/auth.json`
- Modify: `frontend/src/pages/LoginPage.jsx` (buttons above the username/password form, separated by "or"), `frontend/src/services/api.js` (`getAuthProviders()`)

**Interfaces:**
- Consumes: `GET /api/auth/providers` → `{"providers": [{"id": "google"|"facebook"|"github"|"apple", "configured": bool, "start_url": str|null}]}` (built in Phase 1; on 404 every provider counts as not configured).
- Produces: `<SocialSignInButtons mode="signin"|"signup" />`. Order: Apple, Google, Facebook, GitHub. Each is a full-width button with the provider mark and "Continue with {{provider}}", `data-tid="auth.provider.<id>"`, and it emits `ui_tap` via autocapture. Configured → navigate to `start_url`. Not configured → an inline, polite note under the buttons (`aria-live="polite"`): "{{provider}} sign-in is coming soon — use your username and password for now." No navigation and no error.

- [ ] **Step 1: Write failing tests**: four buttons render in order; with a 404 from providers, clicking Google shows the coming-soon note and doesn't navigate; with `configured:true` it navigates to `start_url`; the existing LoginPage tests still pass.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, in both themes, and translate `auth` into all 7 languages. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(auth): sign-in buttons for Apple, Google, Facebook, GitHub`

## Execution waves

- **Wave A (parallel):** Tasks 1+2 (one agent: backend storage + registry), Task 4 (theme), Task 7 (i18n framework).
- **Wave B (parallel, after A merges):** Task 3 (API), Task 5 (SDK; its interface with Task 3 is fixed above), Task 6 (dark polish), Task 8a, 8b, 8d–8i.
- **Wave C:** Task 8c (after 8b), Task 10, Task 11, Task 13, Task 14 (after 8h, which owns LoginPage strings).
- **Wave D:** Task 9 (one reviewer per language, in parallel), Task 12.
- Each wave ends with three review passes on the combined diff: spec compliance, correctness (`/code-review high`), and UX/visual (screenshots in both themes and in `de`/`bn`). One PR per wave, merged when CI is green.
