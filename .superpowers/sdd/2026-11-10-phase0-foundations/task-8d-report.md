# Task 8d report: chat namespace

Branch feat/p0-i18n-chat (from feat/phase0-wave-a).

## Extracted
~170 catalogue entries (en/chat.json; 7 languages) from `frontend/src/pages/ChatPage.jsx`: starter prompts, error/empty/disclaimer copy, section cards (flights, hotels, activities, SIM, visa, tips, getting around, forex, itinerary), My Plan drawer, budget tracker, trip plan view, day cards, message actions.

## Behaviour notes
- Drawer save status is now stored as a key (`login|saved|updated|failed|sentBack|planSaved`) instead of English text; the red/green colour check is `=== 'failed'` rather than `.includes('fail')`.
- Plurals (nights, full days, travelers, itinerary slots) now use `_one/_other` (es/fr also `_many`, zh `_other`). English "1 nights" became "1 night".
- Numbers use `fmtNumber`; the date helper uses `fmtDate` from format.js (was hard-coded en-US).
- Backend enum-ish values (visa type, coverage/rating/cash dependency, time of day) are mapped through catalogue keys with `defaultValue` fallback to the raw value.
- Empty-state `<br />` became a `\n` with `whitespace-pre-line`.
- `data-tid` added to every button/link/toggle/input touched; aria-labels added to icon-only buttons (close, remove, delete, stop, send).
- Error messages stored in chat history are produced in the active language at creation time (not retranslated afterwards).

## Deliberately untranslated
- `utils/chatHistory.js`: all strings are synthesized for the model (API history stand-ins), not UI copy. Untouched.
- Streamed backend chat content, plan names/labels from `utils/planHelpers.js` (`budget.label` e.g. "$X under budget": owned by another task), `GB` unit, "$" currency symbol, place/airline/provider names, tab/route ids.

## Verification
- vitest full suite: 83 files, 1161 tests passed (existing tests unchanged).
- eslint src/ --max-warnings 0: clean.

## Concerns
- `budget.label` text in drawer/tracker stays English until planHelpers is extracted (8e).
- Hindi/Bengali strings are machine-quality; a native review is advisable.

## Fix round 1
- Changes: `ChatPage.jsx` flight card badge "In Plan" now `t('action.inPlan')`; key added to all 7 `chat.json` (en "In Plan", es "En el plan", de "Im Plan", fr "Dans le plan", hi "प्लान में", zh "已在计划中", bn "পরিকল্পনায় আছে").
- Re-grep of JSX text nodes (`>text<` and bare text lines) found nothing else; only remaining literal is the OpenStreetMap attribution (brand/link, left as is).
- Tests: `cd frontend && NODE_OPTIONS=--experimental-require-module npx vitest run` -> Test Files 83 passed (83), Tests 1161 passed (1161).
- Lint: `npx eslint src/ --max-warnings 0` -> exit 0, no output.
