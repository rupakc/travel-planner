# Task 8f report: itinerary namespace
- Strings: ~84 keys in en/itinerary.json (plural groups: toolbar.changes, timeline.durationLong, tours.reviews, extras.fit). 7 languages; es/fr carry _many, zh only _other.
- Files: ItinerarySection, TimelineView, TripMap, WalkingToursSection (+ locales/*/itinerary.json).
- Formatting: toLocaleString/toLocaleDateString replaced with fmtNumber/fmtDate; USD amounts via fmtNumber currency (en output unchanged, e.g. "$20").
- transitLabel (utils/schedule.js, outside scope) is no longer used by ItinerarySection; its text is rebuilt locally from the `transit` object via t(). The util is untouched (still tested).
- Left untranslated: day.date (ISO string from backend, shown raw), data names, provider names, emoji.
- Tests: vitest 83 files / 1161 tests pass unchanged; eslint clean.
- Concern: time-of-day labels now come from the catalog (capitalised), including the map popup (was lowercase "morning"); unknown values fall back to raw.

## Fix round 1
- de `time.afternoon` "Mittags" -> "Nachmittags".
- ItinerarySection day date now `fmtDate(day.date + 'T12:00:00', {year:'numeric', month:'short', day:'numeric'})` (English shows e.g. "May 1, 2026" instead of ISO; no existing test asserted the raw string).
- `utils/schedule.js` `transitLabel` now builds text via `i18n.t('itinerary:transit.*')` at call time; ItinerarySection's local `transitText` removed and it imports `transitLabel` again (one copy).
- Commands: `NODE_OPTIONS=--experimental-require-module npx vitest run` -> 83 files passed, 1161 tests passed; `npx eslint src/ --max-warnings 0` -> no output (clean).
