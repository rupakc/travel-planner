# Task 8g report: `alerts` namespace

Status: DONE (with concerns below).

- Strings: 322 catalogue keys (plural groups counted per form) in `frontend/src/i18n/locales/{en,es,de,fr,hi,zh,bn}/alerts.json`. es/fr carry `_many` copies, zh only `_other`.
- Files touched: `pages/AlertsPage.jsx`, `components/FareCalendarStrip.jsx`, everything under `components/alerts/` (AlertEmailField, AlertToast, LiveCheck, NotificationBell, PriceWatchDialog, Sparkline, WatchActivityButton, WatchCard, WatchDialog, WatchDialogParts, WatchDialogShell, WatchFareButton, WatchHotelButton, WatchTripButton, alertKinds.js, cards/*, dialogs/*). New helper `components/alerts/localized.js`.
- `context/AlertsContext.jsx`: no copy of its own (toast title/body come from the backend), so unchanged.
- `data-tid` added to every button, link and input in these files (`alerts.*`, `fare-calendar.*`).
- Tests: full vitest 83 files / 1161 tests pass unchanged; `eslint src/ --max-warnings 0` clean.

## Price-honesty wording
Observed vs estimated, "Checked … ago", "Next check …", the no-live-price block ("Our AI estimate was … — an estimate, not a live price, so we can’t watch it"), "Estimates are fixed and never trigger alerts" and the trip "live / estimate" caption are all in the catalogue with the same distinctions in every language. "Checked {{when}}" and "Next check {{when}}" use `agoLabel` / `untilLabel` in `localized.js`, which reproduce the English short forms and translate the rest.

## Decisions
- `components/alerts/localized.js` (new, inside the allowed folder): localized ago/until, status chip (from `watchStatus().key`), change-since-start text, day and date-range labels. English still delegates to `utils/fareWatch` / `utils/fareCalendar` so English output is byte-identical (tests pass); other languages use `fmtDate` / `Intl.DateTimeFormat#formatRange`.
- `alertKinds.js`: tests compare `ALERT_KINDS[..].action` to English strings and `alertKindFor` by identity, so the constant stays English and the UI translates through `actionText()`.
- Trans tag renamed `<pagelink>`: `<link>` is a void HTML element in the Trans parser and swallowed its content.
- Callbacks (`load`, `onCheck`, ...) use `i18n.t('alerts:..')` so a language switch doesn't change `load` identity and refetch.

## Left untranslated (outside the 8g file list, English in every language)
These strings live in shared utils no sub-task owns, so they still render in English:
- `utils/priceWatch.js`: `priceCheckMessage`, `checkTarget`/`checkPriceTarget` validation errors.
- `utils/tripWatch.js`: trip row labels/details, badge text (`rowBadge`: Live / Estimate and tooltips), `groupTotals` bar labels, `whatChanged`, `totalDifference` reasons.
- `utils/liveResults.js`: `liveErrorMessage`. `utils/hotelWatch.js` preview text, `utils/activityWatch.js` helpers, `utils/fareWatch.js` `routeLabel`, `notificationLink` etc., `checkTarget` errors.
- Backend-provided strings: notification title/body, `watch.problem`, `result.message`, live-check summary/disclaimer when supplied by the API, provider names.
- `name@example.com` placeholder, "Google Flights"/"Google Hotels"/"GetYourGuide"/"Viator" brand names, currency codes.

## Concerns
- The util strings above should be extracted in a follow-up task (they are user-visible on the Alerts page and in the watch dialogs).
- Hindi/Bengali "watch" is rendered as ट्रैक/ট্র্যাক (travel-app usage); de uses "beobachten"/"Preisalarm"; zh uses 关注 / 价格提醒. Worth a native-speaker skim.
- Non-English date ranges rely on `Intl.DateTimeFormat#formatRange` (fine in current browsers; falls back to ISO dates on error).
