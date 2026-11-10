# Task 8i report: namespace `misc`

Status: done. 190 source strings (en), each translated into es/de/fr/hi/zh/bn (plural forms expanded per language).

Files: SharePage, NearbyPage, CompareTable, FeedbackWidget, OnboardingTour, VerificationBadge, FromLinkChip, LinkPlanBanner, utils/verification.js (gave-up summary via i18n.t at call time), locales/*/misc.json. utils/tour.js has no UI copy (nothing to extract).

Tests: vitest full suite 83 files / 1161 tests pass, existing tests unchanged; eslint --max-warnings 0 clean.

Left as-is on purpose
- Backend verification label/summary/check strings and detail text.
- Tour step titles/bodies: defined outside my files (only the card chrome is translated).
- NearbyPage: section titles/empty lines are translated by id (a backend-supplied title is shown as is). Geolocation and network/grounding errors are translated by code. Other API errors (rate limit, 404, 502, ...) still come from utils/liveResults.js in English (not in my file list; also used by alerts).
- compare.js fmtUsd/fmtDuration (out of scope file) still format en-style.

Behaviour notes
- SharePage: dates via fmtDate, numbers via fmtNumber (`$` + number). Fixed "1 activities planned" / "1 transport picks" via plurals.
- Added aria-labels to the feedback star buttons and panel close; data-tid on all buttons/links touched.
- LinkPlanBanner / InspiredBy / Near-me attribution use <Trans> with a self-closing component tag (<src/>).

Concerns
- Share-card PNG canvas wraps on spaces only: Chinese (no spaces) lines can overflow the card width; Devanagari/Bengali depend on system fonts in canvas.
