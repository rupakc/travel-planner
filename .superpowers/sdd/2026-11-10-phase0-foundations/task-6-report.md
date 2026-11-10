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
