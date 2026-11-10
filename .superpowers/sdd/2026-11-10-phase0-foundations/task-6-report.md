# Task 6 report: dark-mode polish

Branch feat/p0-dark-polish (from feat/phase0-wave-a). Tests 1129/1129, eslint clean, build OK.

## Changes
- TDD: `src/theme/darkSurfaces.test.jsx` (TripMap in dark mode has no literal hex; index.css has the tile dim rule) and an extended `planPrint.test.js` (color-scheme light, no `var(--c-`, no dark class). Both failed first.
- `index.css`: `html.dark .leaflet-tile-pane { filter: brightness(.75) contrast(1.1) saturate(.8) }` (markers/popups untouched) plus dark popup surface. Applied directly on html.dark; no separate `.map-dark-tiles` class was added.
- `planPrint.js`: `:root{color-scheme: light}` and `<meta name="color-scheme" content="light">`; its inline light hex colours are deliberately kept (separate Blob window, always light).
- Hex literals converted to `rgb(var(--c-…))`: TripMap, ChatPage map (palette, origin dot, polyline, popups), ImportMap, import/kinds.js, ImportPreview, Sparkline, ResultsPage price-history SVG.
- SharePage trip card: gradient is fixed brand colours with white text; since `--c-white` is a dark surface in dark mode, the card sets `--c-white: 255 255 255` inline so its text stays white.

## Remaining hex (intentional)
planPrint.js STYLES; ResultsPage emergency-card print HTML (own light window); SharePage card gradient palette + canvas drawing; ThemeContext THEME_COLOR.

## Screenshots (scratchpad, 1280x800, API mocked via Playwright routes)
Dir: /private/tmp/claude-501/-Users-rupak-travel-planner/e830f1ab-f3ee-4003-b08a-05000d457ca4/scratchpad/
shot-{light,dark}-{search,chat,alerts,preferences,admin,nearby,share-abc}.png (14 files). Dark pages looked right; the share-card text bug was found and fixed after the screenshot (share-abc dark predates the fix). Not captured: Results page and live Leaflet tiles (need SSE search data / network); covered by unit tests only.

## Fix round 1
1. Pin numbers: TripMap, ImportMap `pinIcon` (now exported) and ImportPreview use `rgb(var(--c-white))` instead of `white`. Tests in darkSurfaces.test.jsx assert the variable and no `color:white`/`#fff`. (kinds.js colours left as theme-mapped 600/700 stops; the number colour now flips to the dark surface so contrast holds.)
2. SearchPage "Paste the link" pill: added `dark:bg-amber-500/15 dark:ring-amber-500/40 dark:hover:bg-amber-500/25`.
3. OnboardingTour spotlight: added `dark:ring-teal-600`.
4. Print: build-tokens.mjs emits `@media print { html.dark { <light values> } }`; tokens.css regenerated (`npm run tokens`); tokens.test.js asserts the block (existing sync test covers regeneration).
5. Screenshots (dark, tour dismissed via `tp_tour_done:demo`, API mocked incl. SSE search stream; scratchpad dir .../scratchpad/):
   fix1-dark-search.png, fix1-dark-share.png (white text fixed), fix1-dark-results.png (Search again -> mocked stream), fix1-dark-alerts-sparkline.png (4-point history).
   Observation: Results top bar (`from-slate-500 to-slate-600 text-white`) becomes a pale bar with dark text in dark mode; readable, not changed.
Verification: vitest 84 files / 1131 tests pass; eslint clean; build OK.
