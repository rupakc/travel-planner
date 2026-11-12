# Phase 2 follow-ups

Deferred items from the Phase 2 (journey) execution: reviewer minors, the final whole-branch review's Minor list, and the E2E findings. None blocks the journey being on. Grouped by area; pick up opportunistically.

## Owner / external actions

- Native-speaker review of the hi, bn and zh UI text and of the 34-language phrase list (owner ruling 4). The model-reviewed text shipped.
- Real-device check of the service worker and IndexedDB on Safari/iOS (only Chromium was exercised in the E2E). Confetti and the recap countries reveal were not observed in the E2E; look at them once.
- Mobile teams (Android phase 8, iOS phase 7): the client `placeKey` rule changed (non-ASCII names get a `-<8 hex>` FNV-1a suffix; see `docs/Trips-API.md` Client notes and the shared fixture); `GET /trips/{id}/offline-pack` may answer `404 offline_pack_disabled`; place `visited_at` is a never-cleared first-visit marker, use `visited`; extra field-level 422 codes are listed in Trips-API.md.
- `docs_homepage/index.html` still says "Travel Planner".

## Backend

- No per-user trip cap on `POST /trips` (final review M3). Rows can each hold a 256 KB snapshot.
- Stress-test progress (M5): use `resolve_today`, do not award `smart_planner` on the first ever score, make previous-score read/write atomic.
- Recap complete (M6) and check-in: the claim commits before `add_countries`/award; a crash between loses them with no retry.
- Check-in accepts a day of UTC +/-1 so "tomorrow" feeds the streak (M11); countries/recap are self-claimed via editable dates.
- `/trips/stats` and `list_trips` run `prep_summary` per plan (N+1); `pick_pinned` counts manual-phase trips; `POST /trips` returns a generic 422 for a bad title instead of `trip_title_invalid`; a plan rename via PUT clears the trip title (undocumented).
- `request.json()` is read before the 256 KB check in the snapshot/offline routes (Caddy bounds it at 32 MB) (M1). `GET offline-pack` writes (prep tick, award); documented only here (M13).
- Expenses: concurrent patch edge cases; `\d` accepts Unicode digits; JSON-number amounts get a generic 422; usd/category rounding differs by a cent.
- `_currency` is `null` without a rate; snapshot body read fully before the size check; a `null` snapshot value passes validation.
- Check-in: an award hook failure after insert is never retried; `GET /checkins` always returns `streak: null`.
- Phrases: Simplified Chinese only (Taiwan wants Traditional); country-map judgement calls BE/SK/BA/ME/RS/MO; is/tl/pt thank-you wording.
- Test hygiene: several tests have no RED record; stub-era seam tests; trip tables' idempotency test does not assert columns; `add_countries` does not validate country codes.

## Web: offline, auth, i18n

- Overlapping SW precache runs can leave no served shell; the 2 MB `sw-assets` cap silently drops files (add a build guard that the entry chunk is listed); a lazy chunk first needed offline after a deploy fails (M10).
- Outbox treats 409 as sent, so offline writes that hit `journal_limit`/`expense_limit`/`places_limit` vanish silently (M8). A 5xx from `/auth/me` signs the user out (M9). Device residue after a non-revoked 401 (packs, outbox, `tp_exp_pending:*`, `tp_quiz_*`, `tp_tour_done:*` stay) (M7). Web Locks two-tab test missing.
- `sizeKb` uses string length; telemetry `unsupported` / `open kb 0` semantics; PhaseMenu focus return; offline manual phase lost (pack has no phase).
- i18n: lazy-namespace gate loads even when it renders nothing; skeleton lacks an accessible name; `PREFETCH_PATHS` is broader than /account,/admin; the lazy list is written three times; branding test greps English only; fr/de buttons over 1.6x English length for "Enregistrer", "Überspringen", tab "Vorbereitung".

## Web: journey UI

- Trips hub: ring goal 0, multi-city "Day N" city, no focus trap/Escape mid-save, `d.trips` without `?.`, failed refetch flips `hasTrips` true to false, `useHasTrips` does not refresh after the first trip is saved mid-session, config-loading flash of Search at `/`.
- Prep: concurrent toggle rollback restores a whole snapshot; 409 does not reload; stale data on `trip.id` change; global `.confetti` selector; overdue amber on `na` rows.
- Today: directions query is name-only (no city); click emits `next_up` not `directions`; "Next up" still shows a slot already marked Visited; missing dates show a dash.
- Expenses: category chips lack arrow keys; generic `saveFailed` for all server errors; a synced row can linger; formError/failed/savingRef/busy leak across a trip switch; the queue test passes without the fix.
- Journal: queued entry without `created_at` sorts first in its day; double-failure stale rollback.
- Recap: invented `departure_date` today+45 for Discover; RecapMap dark border; over-budget is colour-only; repeat-completion test hits the mock; no trip-change guard on finish/share.
- Near me "I'm here": telemetry fires before save succeeds; a name over 120 chars fails with a generic error; visited set not reset on trip change; no offline/failure tests; uses the rounded user location as lat/lng (ruling R35); hidden for Maps-grounded items (R41) so visits cannot be marked on v2 results.
- Results/Chat integration: `savedTripId` clear untested; the stricter `searchMatchesPlan` skips the snapshot for legacy plans without origin; chat notifies trips changed before the snapshot PUT lands.
- Onboarding/coach/play: opening `/onboarding` directly does not mark it seen; seen flag not per user; passport saved on Skip; home airport is device-only and unread (wire into Explore origin prefill); JourneyCoach does an extra `GET /account`; `/game/me` fetched twice; stats failure hides sections silently; goal save bypasses the settings context.
- Explore/tabs: `scrollIntoView` may scroll the page; no active-tab-scroll test; prefill effect runs with the flag off; duplicate tour anchors; skeleton copy on /play,/you.
- Theme: gray-400 on dark gray-100 chips is 4.26:1 (below AA); gray-400 and gray-500 collapse in dark; `BestValuePackage` pairs `bg-teal-700` with `border-teal-600`; the E2E covered only part of the light/dark x 375/1280 grid in English.
- Completeness: nights default 1 makes 1 day = 100%; no layout-moved-slot test.

## Process notes

- Before the journey flipped on for everyone, E2E walked all 8 journey steps; mixed-version checks of the old SPA against the new backend were done by API calls, not in the old SPA's UI.
