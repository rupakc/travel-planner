# Drag-and-Drop Itinerary Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the Results page itinerary, let users move an activity to another day or time of day (drag-and-drop, plus a keyboard/touch "Move to…" menu), swap two activities, remove one, undo, and reset — with every edit, note, plan pick, export, print view, share page and saved plan following the activity to its new place.

**Architecture:** A pure layout overlay `selections.itinerary_layout` records only *where each moved/removed activity now sits*, keyed by the activity's **original** slot key (`"<day_number>-<time_of_day>"`, the de-facto ID the whole app already uses). One pure function, `arrangeItinerary(itinerary, layout)`, turns the original itinerary plus the overlay into the arranged days; every reader renders those arranged days and looks up edits/notes by `slot.key` (the original key), so nothing is re-keyed on a move. The overlay carries a fingerprint of the itinerary it was made for and is ignored when it doesn't match (stream retry, a saved plan for another trip).

**Tech Stack:** React 18, native HTML5 drag-and-drop (no new library — the codebase already uses native DnD), Tailwind 4, vitest + jsdom (`createRoot` + `act`).

**Spec:** Backlog item #12 in `Future_Improvements.md` ("Drag-and-Drop Itinerary Editing"). Facts: `/private/tmp/claude-501/-Users-rupak-travel-planner/6a423640-de0e-4ae7-a160-af5d4cd4d6e9/scratchpad/research-12.md`. All design choices below are Claude's (the user delegated them).

## Design (binding)

Options weighed:
- (a) **Overlay of positions keyed by original slot key** — chosen. Edits/notes/plan picks/.ics UIDs (`slot-${key}`) stay attached to the activity with zero re-keying; old saved plans need nothing; one function to test.
- (b) Rewrite `selections.itinerary` and re-key edits/notes/itinerary_slots on every move — rejected: every move mutates four structures, .ics UIDs change (calendar duplicates), and the live Results itinerary is not `selections.itinerary`.
- (c) A DnD library (dnd-kit) — rejected: new dependency; native DnD is the codebase convention and the "Move to…" menu covers touch/keyboard.

Model:
- `slotKey(dayNumber, timeOfDay) = \`${dayNumber}-${timeOfDay}\``. Positions are the three standard times `morning`, `afternoon`, `evening` on each existing day. A slot whose `time_of_day` is not one of the three is displayed where it is and is not movable.
- `itinerary_layout = { fingerprint: string, positions: { [originalKey]: "<day>-<tod>" | null } }` — `null` = removed; a key absent from `positions` stays at its original position. `EMPTY_SELECTIONS.itinerary_layout = null`. Old plans without it behave exactly as today.
- `fingerprint` = short stable hash of the original itinerary's `day_number|time_of_day|activity` lines. A layout whose fingerprint differs from the itinerary being rendered is ignored (rendered as the original) and not written to.
- **Move** = put activity A at target position T. If T holds activity B, B moves to A's current position (swap). If T is empty (removed/free), A just moves. Moving to its own position is a no-op. Every day keeps at most one activity per time of day (TimelineView, .ics and print rely on this).
- **City rule (multi-city):** a move is allowed only when the source day's `city` and the target day's `city` are equal (case-insensitive, first comma segment) or either is missing. Swaps must satisfy the rule both ways.
- **Remove** = position `null`; the spot shows "Free time" and accepts drops. **Restore** puts a removed activity back at its original position if that is empty, else in the first empty position of its original day, else it stays removed (button disabled with a tooltip).
- **Arranged days:** same days, same order and day metadata (date, theme, city); each day's slots = activities now positioned there, sorted morning → afternoon → evening, each slot object is the original slot plus `key` (original key) and `time_of_day` (its new time). `removed: [{ key, slot }]` lists removed activities for the UI.
- **Costs:** for a day whose contents changed, `daily_estimated_cost_usd` = sum of its slots' cost (`itinerary_edits[key].cost ?? slot.estimated_cost_usd`, finite numbers only); untouched days keep the original value. `total_estimated_cost_usd` is recomputed the same way only when anything changed. Unchanged itinerary → identical numbers to today.
- **Plan picks follow:** after every move/remove/restore/undo/reset, each `itinerary_slots` entry is updated to its activity's current `day_number`/`time_of_day` (entries for removed activities are kept, unchanged — the user removes them from the drawer as today).
- **Undo:** an in-memory stack of previous layouts (max 20) in ResultsPage; "Undo" reverts the last move/remove/restore. **Reset** clears the layout (with Undo able to bring it back). Both cleared by a new search/remix.
- **Where editing happens:** Cards view itinerary only (it is already the edit/notes view). Timeline view, TripMap, drawer, PlanViewModal, SharePage, .ics and print all *display* the arranged itinerary. ChatPage is untouched (chat is knowledge-only; its itinerary is a different shape).
- **Health Check:** when the layout has changes, the Trip Health Check section shows one line: "Checked against the original itinerary — your moves aren't re-checked."
- **Interaction:**
  - Each movable slot row has a drag handle (`GripVertical`, `cursor-grab`) and is `draggable`; drag data uses the custom MIME `application/x-itinerary-slot` (never `application/json`, which the drawer treats as a plan). Valid drop targets (other slots and Free-time spots, honouring the city rule) highlight on dragover; invalid ones don't accept the drop.
  - Each movable slot has a "Move" button opening a small menu listing every valid target as "Day N · Morning" (swaps labelled "Day N · Morning (swap with <activity>)") plus "Remove from day". Fully keyboard operable; Escape closes it; focus returns to the button.
  - Section toolbar (only when the layout has changes): "N changes" · Undo · Reset. Removed activities listed under "Removed" with Restore.
  - Status messages in an `aria-live="polite"` region, e.g. "Moved Sagrada Família to Day 2 · Afternoon".
- **Analytics:** `track('itinerary_slot_moved', 'results', { method: 'drag'|'menu', swap: bool })`, `track('itinerary_slot_removed', 'results', {})`, `track('itinerary_layout_reset', 'results', {})`.

Non-goals: ChatPage itinerary, re-running the Health Check, adding new activities, more than one activity per time of day, editing in Timeline view, backend changes.

## Global Constraints

- No new dependencies. No backend changes (selections are stored as opaque JSON).
- Frontend tests: `cd frontend && NODE_OPTIONS=--experimental-require-module npx vitest run`; lint `npx eslint src/ --max-warnings 0`; build `npm run build`. Pure-logic tests start with `// @vitest-environment node`; component tests `// @vitest-environment jsdom`, `createRoot` + `act`, mock `../utils/analytics`. jsdom has no `DataTransfer`: tests pass a plain object `{ setData, getData, types, dropEffect, effectAllowed }` on synthetic events.
- Itineraries with no layout must render, export, print and share byte-for-byte as before (existing planExport/planPrint tests must pass unchanged).
- Baseline before this work: whatever `main` has after the best-value package merge (frontend count recorded in the ledger), backend 333.

## Review Focus

1. Saved plans and share links created before this change (no `itinerary_layout`) — must look exactly as before.
2. A layout from another itinerary (fingerprint mismatch) — ignored, never applied to the wrong activities, never crashes.
3. Edits/notes/plan picks on a moved or swapped activity — follow the activity everywhere (card, drawer, .ics, print, share, saved-plan modal).
4. Multi-city trips — no cross-city moves through drag or menu, including the swapped partner.
5. Days whose slots carry odd `time_of_day` values or fewer than three slots — rendered, the odd ones not movable, free positions droppable.

---

### Task 1: Layout model (pure logic)

**Files:**
- Create: `frontend/src/utils/itineraryLayout.js`
- Test: `frontend/src/utils/itineraryLayout.test.js`
- Modify: `frontend/src/utils/planHelpers.js` (add `itinerary_layout: null` to `EMPTY_SELECTIONS`)

**Interfaces — Produces:**
- `TIMES = ['morning', 'afternoon', 'evening']`
- `slotKey(dayNumber, timeOfDay) -> string`
- `itineraryFingerprint(itinerary) -> string`
- `activeLayout(itinerary, layout) -> layout | null` (null when layout missing, malformed, or fingerprint mismatch)
- `arrangeItinerary(itinerary, layout, edits = {}) -> { ...itinerary, days, removed: [{ key, slot }], changed: boolean }` — returns the input's days (each slot given `key`) and `changed: false` when no active layout.
- `moveTargets(itinerary, layout, key) -> [{ day_number, time_of_day, swapWith: { key, activity } | null }]` (valid targets only, excluding the current position)
- `moveSlot(itinerary, layout, key, dayNumber, timeOfDay) -> layout` (returns the same layout object for an invalid move)
- `removeSlot(itinerary, layout, key) -> layout`
- `restoreSlot(itinerary, layout, key) -> layout`
- `layoutChangeCount(itinerary, layout) -> number` (activities not at their original position, removed included)
- `syncPlannedSlots(itinerarySlots, arranged) -> itinerarySlots` (new array; same objects when nothing changed)

- [ ] **Step 1: Failing tests** (fixture: 3 days × 3 slots, day 3 in another city for city-rule tests): no layout → arranged equals input days with `key`s and `changed:false`; move into empty spot; move onto occupied spot swaps both; move to own spot no-op; cross-city move and cross-city swap rejected (layout unchanged, not in `moveTargets`); remove → slot absent, listed in `removed`, its spot is a target for others; restore to original, restore to first free spot of original day, restore impossible → unchanged; fingerprint mismatch → `activeLayout` null and arrange returns original; malformed layout (`positions` not an object, target string for a nonexistent day) ignored safely; odd `time_of_day` ('late night') rendered, not movable, not a target; day cost recomputed only for changed days, using `edits[key].cost` override and skipping junk; `layoutChangeCount`; `syncPlannedSlots` updates day/time for a moved key and keeps entries for removed keys; `EMPTY_SELECTIONS.itinerary_layout === null`.
- [ ] **Step 2:** run the file — FAIL. **Step 3:** implement. **Step 4:** file + full suite + lint pass.
- [ ] **Step 5: Commit** `feat(itinerary): layout overlay model for moving activities`.

### Task 2: Readers display the arranged itinerary

**Files:**
- Modify: `frontend/src/utils/planExport.js` (`planItineraryDays`, `itineraryEvents`), `frontend/src/utils/planPrint.js`, `frontend/src/pages/SharePage.jsx` (poster ~L147-160, cards ~L383-410), `frontend/src/components/PlanViewModal.jsx` (snapshot itinerary ~L440)
- Test: `frontend/src/utils/planExport.test.js`, `frontend/src/utils/planPrint.test.js`

**Interfaces — Consumes:** Task 1 `arrangeItinerary`, `slotKey`.

- [ ] **Step 1: Failing tests:** with `selections.itinerary_layout` moving `'1-morning'` to `'2-evening'` (swap) and an edit + note on `'1-morning'`: `planItineraryDays` returns arranged days; the .ics event for that activity has `id 'slot-1-morning'`, day 2's date and evening hours, the edited summary and the note; the swapped activity lands on day 1 morning; a removed activity produces no event and no print row; print shows the moved activity under Day 2 with its edit/note. Existing tests unchanged and passing.
- [ ] **Step 2–4:** implement: `planItineraryDays(selections, itinerary)` applies `arrangeItinerary(source, selections?.itinerary_layout, selections?.itinerary_edits)` to whichever source it picks (live, snapshot); readers use `slot.key ?? slotKey(day.day_number, slot.time_of_day)` for edits/notes/UIDs. SharePage and PlanViewModal render `arrangeItinerary(sel.itinerary, sel.itinerary_layout, sel.itinerary_edits).days` and use `slot.key` the same way (no new tests for pages; keep their diffs minimal). Full suite + lint + build.
- [ ] **Step 5: Commit** `feat(itinerary): exports, print, share and plan viewer follow moved activities`.

### Task 3: Itinerary editor component (extract + drag/drop + move menu)

**Files:**
- Create: `frontend/src/components/ItinerarySection.jsx` — move `ItinerarySection` out of `frontend/src/pages/ResultsPage.jsx` (search `function ItinerarySection`) **unchanged first** (own commit: `refactor(itinerary): move ItinerarySection into its own file`, ResultsPage imports it; verify the app renders identically), then extend it.
- Test: `frontend/src/components/ItinerarySection.test.jsx`

**Interfaces:**
- Consumes: Task 1 exports.
- Produces: `ItinerarySection({ data, selections, onNoteChange, onSlotEdit, onSlotPlan, onMoveSlot, onRemoveSlot, onRestoreSlot, onUndoLayout, onResetLayout, canUndo })` where `data` is the **original** itinerary; the component computes `arrangeItinerary(data, selections.itinerary_layout, selections.itinerary_edits)` itself. Callbacks: `onMoveSlot(key, dayNumber, timeOfDay, method)` with method `'drag'|'menu'`, `onRemoveSlot(key)`, `onRestoreSlot(key)`. All existing edit/note/plan behaviour keeps working and now uses `slot.key`. TripMap inside it receives the arranged days.

- [ ] **Step 1: Failing tests:** renders arranged order; slot rows are `draggable` with a handle; a synthetic dragstart sets `application/x-itinerary-slot` and a drop on another slot calls `onMoveSlot(key, day, tod, 'drag')`; a drop carrying only `application/json` is ignored; dragover on an invalid (cross-city) target is not accepted (no `preventDefault`); "Move" menu lists exactly `moveTargets`, choosing one calls `onMoveSlot(..., 'menu')`, Escape closes and returns focus; "Remove from day" calls `onRemoveSlot`; Free-time placeholder rendered for empty positions and accepts drops; toolbar with "N changes", Undo (disabled when `!canUndo`), Reset appears only when changed; Removed list with Restore; edit/note/Plan buttons on a moved activity use its original key; an odd-`time_of_day` slot has no handle/Move.
- [ ] **Step 2–4:** implement; keep the current visual design; handle at row start, Move button with the other action pills; drop highlight `ring-2 ring-teal-400 bg-teal-50`; live-region status text. Full suite + lint.
- [ ] **Step 5: Commit** `feat(itinerary): drag-and-drop and move menu in the itinerary card`.

### Task 4: Wire into ResultsPage, Timeline, Health Check, docs

**Files:**
- Modify: `frontend/src/pages/ResultsPage.jsx` (selections state init and `runSearch` reset literal include `itinerary_layout: null`; handlers; `selectionsForSave` already spreads selections — verify the layout is saved with the snapshot; Timeline view and drawer itinerary slot list display arranged data; StressTestSection note), `docs/Frontend.md`, `CLAUDE.md`
- Modify if needed: `frontend/src/components/TimelineView.jsx` (only if it needs `key`s; it receives arranged `itineraryData`)

**Interfaces — Consumes:** Tasks 1 and 3.

- [ ] **Step 1:** handlers in ResultsPage: `handleMoveSlot(key, day, tod, method)`, `handleRemoveSlot(key)`, `handleRestoreSlot(key)`, `handleUndoLayout()`, `handleResetLayout()`. Each computes the next layout from `results.itinerary` + current layout (initialising `{ fingerprint: itineraryFingerprint(results.itinerary), positions: {} }` when none is active), pushes the previous layout on an undo stack (`useState`, max 20, cleared in `runSearch` and `handleLoadPlan`), and does ONE `setSelections` that sets `itinerary_layout` and `itinerary_slots: syncPlannedSlots(...)`. Track analytics per Design.
- [ ] **Step 2:** pass the new props to `ItinerarySection`; pass `arrangeItinerary(results.itinerary, selections.itinerary_layout, selections.itinerary_edits)` to `TimelineView`; StressTestSection shows the Design's note when `layoutChangeCount > 0`.
- [ ] **Step 3:** full suite, lint, build, backend suite.
- [ ] **Step 4:** docs: Frontend.md ResultsPage paragraph on itinerary editing; CLAUDE.md My Plan line mentions moved activities persisting via `itinerary_layout`.
- [ ] **Step 5: Commit** `feat(itinerary): move, remove, undo and reset itinerary activities on Results`.

End-to-end (controller, Chrome): real search; drag morning→other day's afternoon (swap), menu move, remove + restore, undo, reset; edit + note on a moved activity; add it to plan; drawer shows new day/time; save plan → reopen in saved-plan viewer; share page; .ics download contents; print view; Timeline view; multi-city cross-city drop refused; old saved plan unchanged; 375px; console clean.
